"""Bookings end to end through HTTP, with a fake agent: no browser and no LLM.

The `FakeLauncher` behaves like the real runner on disk: it writes `status.json` with
`awaiting_approval` and a screenshot, waits for `approval.json`, then writes `result.json`.
"""

import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.launcher import LaunchSpec
from app.agent.runner import read_approval
from app.core.config import Settings, get_settings
from app.core.domain.errors import BookingError
from app.core.domain.trips import (
    AgentOutcome,
    BookingKind,
    BookingStatus,
    ContributionStatus,
    EventKind,
    MemberRole,
    TransportMode,
    TripStatus,
)
from app.core.http_security import CSRF_HEADER_NAME
from app.db.client import Database
from app.db.identifiers import identifier_of, to_object_id
from app.models.bookings import AgentRun, Booking
from app.models.trips import Contribution, Trip, TripEvent, TripMember
from app.routes.dependencies import get_booking_service
from app.services.bookings import BookingService, running_monitors

PASSWORD = "correct-horse-battery-staple"
PNG = b"\x89PNG\r\n\x1a\nfake-frame"
TRAIN_MINOR = 120_000
STAY_MINOR = 60_000


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class FakeHandle:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    async def wait(self) -> int:
        # Polls the file like the real runner does — the file IS the interface under test.
        for _ in range(1000):
            decision = read_approval(str(self.run_dir))
            if decision is not None:
                break
            await asyncio.sleep(0.01)
        else:
            return 1
        outcome = AgentOutcome.DONE if decision else AgentOutcome.HANDOFF
        result = {
            "outcome": outcome.value,
            "reason": "simulated confirmation" if decision else "The organizer rejected it.",
            "steps": 8,
            "cost_usd": 0.0,
            "confirmation_ref": "SIM-ABC123" if decision else "",
        }
        _write(self.run_dir / "result.json", result)
        return 0


class FakeLauncher:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.started: list[LaunchSpec] = []

    async def start(self, spec: LaunchSpec) -> FakeHandle:
        self.started.append(spec)
        run_dir = self.runs_dir / spec.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "07-done.png").write_bytes(PNG)
        status = {"milestone": "review", "reached": ["search", "review"], "step": 7}
        _write(run_dir / "status.json", {**status, "outcome": "awaiting_approval"})
        return FakeHandle(run_dir)


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    path = tmp_path / "runs"
    path.mkdir()
    return path


@pytest.fixture
def launcher(runs_dir: Path) -> FakeLauncher:
    return FakeLauncher(runs_dir)


@pytest.fixture
def booking_app(
    app: FastAPI, database: Database, runs_dir: Path, launcher: FakeLauncher
) -> Iterator[FastAPI]:
    def service() -> BookingService:
        return BookingService(database, launcher, runs_dir, poll_s=0.01)

    app.dependency_overrides[get_booking_service] = service
    yield app


@pytest.fixture
async def drain_monitors(database: Database) -> AsyncIterator[None]:
    """No monitor may outlive its test — it depends on `database`, so it is torn down first."""
    yield
    tasks = running_monitors()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _register(client: AsyncClient, email: str) -> str:
    await client.get("/api/auth/session")
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "organization_name": "Friends"},
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    user_id: str = response.json()["id"]
    return user_id


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token is not None
    return {CSRF_HEADER_NAME: token}


@pytest.fixture
async def friend(booking_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """A second browser: another signed-in person."""
    transport = ASGITransport(app=booking_app)
    async with AsyncClient(transport=transport, base_url="http://test") as other:
        yield other


async def _seed_trip(
    organizer_id: str,
    member_ids: list[str],
    status: TripStatus,
    booking_status: BookingStatus = BookingStatus.PENDING,
    paid_minor: int | None = None,
) -> tuple[Trip, Booking, Booking]:
    user_ids = [to_object_id(organizer_id), *(to_object_id(m) for m in member_ids)]
    owners = [oid for oid in user_ids if oid is not None]
    total = TRAIN_MINOR + STAY_MINOR
    trip = await Trip(
        title="Prague weekend",
        origin="Warszawa",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
        group_size=len(owners),
        organizer_id=owners[0],
        invite_code=secrets.token_hex(6),
        status=status,
        total_minor=total,
    ).insert()
    share = total // len(owners)
    for index, user_id in enumerate(owners):
        role = MemberRole.ORGANIZER if index == 0 else MemberRole.MEMBER
        await TripMember(
            trip_id=identifier_of(trip),
            user_id=user_id,
            display_name=f"Person{index} Nowak",
            role=role,
        ).insert()
        paid = share if paid_minor is None else paid_minor
        await Contribution(
            trip_id=identifier_of(trip),
            user_id=user_id,
            amount_minor=share,
            paid_minor=paid,
            status=ContributionStatus.PAID if paid >= share else ContributionStatus.PENDING,
        ).insert()
    train = await Booking(
        trip_id=identifier_of(trip),
        kind=BookingKind.TRANSPORT,
        mode=TransportMode.RAIL,
        title="EC 113 Warszawa -> Praha",
        supplier="PKP Intercity",
        supplier_url="http://localhost:8200/api/demo-supplier/rail",
        goal="Book 2nd-class tickets Warszawa -> Praha on 2026-11-20.",
        amount_minor=TRAIN_MINOR,
        status=booking_status,
    ).insert()
    stay = await Booking(
        trip_id=identifier_of(trip),
        kind=BookingKind.STAY,
        title="Old Town apartment",
        supplier="Booking.com",
        supplier_url="https://www.booking.com",
        goal="Two nights for the group.",
        amount_minor=STAY_MINOR,
        status=booking_status,
    ).insert()
    return trip, train, stay


async def _until(predicate: Callable[[], Awaitable[bool]], what: str) -> None:
    for _ in range(300):
        if await predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


async def _booking_status(client: AsyncClient, trip: Trip, booking: Booking) -> str:
    response = await client.get(f"/api/trips/{trip.id}/bookings")
    assert response.status_code == 200, response.text
    by_id = {item["id"]: item for item in response.json()["bookings"]}
    status: str = by_id[str(booking.id)]["status"]
    return status


async def _kinds(trip: Trip) -> list[EventKind]:
    events = await TripEvent.find(TripEvent.trip_id == identifier_of(trip)).to_list(100)
    return [event.kind for event in events]


@pytest.mark.usefixtures("drain_monitors")
async def test_start_await_approve_confirm_books_the_trip(
    booking_app: FastAPI, client: AsyncClient, launcher: FakeLauncher, runs_dir: Path
) -> None:
    organizer = await _register(client, "org@example.com")
    trip, train, stay = await _seed_trip(organizer, [], TripStatus.BOOKING)
    # The stay was replaced earlier: a cancelled booking must not block "trip booked".
    await stay.set({"status": BookingStatus.CANCELLED})

    started = await client.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/start", headers=_csrf(client)
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run"]["run_id"]
    assert run_id == f"b{train.id}-1"
    assert launcher.started[0].vault["email"] == "org@example.com"
    assert launcher.started[0].vault["passenger_1_first_name"] == "Person0"

    async def awaiting() -> bool:
        return await _booking_status(client, trip, train) == BookingStatus.AWAITING_APPROVAL

    await _until(awaiting, "awaiting approval")
    status = (await client.get(f"/api/agent-runs/{run_id}/status")).json()
    assert status["live"]["outcome"] == "awaiting_approval"
    assert status["run"]["milestone"] == "review"
    assert status["run"]["steps"] == 7

    approve = await client.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/approve",
        json={"approved": True},
        headers=_csrf(client),
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == BookingStatus.APPROVED
    assert read_approval(str(runs_dir / run_id)) is True

    async def confirmed() -> bool:
        return await _booking_status(client, trip, train) == BookingStatus.CONFIRMED

    await _until(confirmed, "confirmed")
    listing = (await client.get(f"/api/trips/{trip.id}/bookings")).json()
    assert listing["trip_status"] == TripStatus.BOOKED
    item = next(b for b in listing["bookings"] if b["id"] == str(train.id))
    assert item["confirmation_ref"] == "SIM-ABC123"
    assert item["run"]["outcome"] == AgentOutcome.DONE
    kinds = await _kinds(trip)
    for kind in (
        EventKind.BOOKING_STARTED,
        EventKind.BOOKING_AWAITING_APPROVAL,
        EventKind.BOOKING_CONFIRMED,
    ):
        assert kind in kinds


@pytest.mark.usefixtures("drain_monitors")
async def test_rejection_hands_off(
    booking_app: FastAPI, client: AsyncClient, launcher: FakeLauncher
) -> None:
    organizer = await _register(client, "org@example.com")
    trip, train, _ = await _seed_trip(organizer, [], TripStatus.BOOKING)
    await client.post(f"/api/trips/{trip.id}/bookings/{train.id}/start", headers=_csrf(client))

    async def awaiting() -> bool:
        return await _booking_status(client, trip, train) == BookingStatus.AWAITING_APPROVAL

    await _until(awaiting, "awaiting approval")
    reject = await client.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/approve",
        json={"approved": False},
        headers=_csrf(client),
    )
    assert reject.json()["status"] == BookingStatus.HANDOFF

    async def finished() -> bool:
        run = await AgentRun.find_one(AgentRun.booking_id == identifier_of(train))
        return run is not None and run.outcome is AgentOutcome.HANDOFF

    await _until(finished, "handoff")
    assert await _booking_status(client, trip, train) == BookingStatus.HANDOFF
    # A handoff can be retried: a fresh run with the next attempt number.
    retry = await client.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/start", headers=_csrf(client)
    )
    assert retry.json()["run"]["run_id"] == f"b{train.id}-2"


async def test_start_is_rejected_while_the_trip_is_still_paying(
    booking_app: FastAPI, client: AsyncClient, launcher: FakeLauncher
) -> None:
    """Rule #1: the agent buys nothing before everyone has paid."""
    organizer = await _register(client, "org@example.com")
    trip, train, _ = await _seed_trip(organizer, [], TripStatus.PAYING, paid_minor=0)
    response = await client.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/start", headers=_csrf(client)
    )
    assert response.status_code == 409
    assert response.json()["code"] == BookingError.TRIP_NOT_READY
    assert launcher.started == []


async def test_only_the_organizer_starts_and_approves(
    booking_app: FastAPI, client: AsyncClient, friend: AsyncClient
) -> None:
    organizer = await _register(client, "org@example.com")
    member = await _register(friend, "member@example.com")
    trip, train, _ = await _seed_trip(
        organizer, [member], TripStatus.BOOKING, BookingStatus.AWAITING_APPROVAL
    )
    listing = await friend.get(f"/api/trips/{trip.id}/bookings")
    assert listing.status_code == 200
    assert listing.json()["is_organizer"] is False

    start = await friend.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/start", headers=_csrf(friend)
    )
    assert start.status_code == 403
    approve = await friend.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/approve",
        json={"approved": True},
        headers=_csrf(friend),
    )
    assert approve.status_code == 403
    assert approve.json()["code"] == BookingError.NOT_ORGANIZER


async def test_non_members_see_nothing(
    booking_app: FastAPI, client: AsyncClient, friend: AsyncClient, runs_dir: Path
) -> None:
    organizer = await _register(client, "org@example.com")
    await _register(friend, "stranger@example.com")
    trip, train, _ = await _seed_trip(organizer, [], TripStatus.BOOKING, BookingStatus.RUNNING)
    run_id = f"b{train.id}-1"
    await AgentRun(
        run_id=run_id, booking_id=identifier_of(train), trip_id=identifier_of(trip)
    ).insert()
    (runs_dir / run_id).mkdir()
    (runs_dir / run_id / "01.png").write_bytes(PNG)

    frame = await client.get(f"/api/agent-runs/{run_id}/frame")
    assert frame.status_code == 200
    assert frame.content == PNG
    assert frame.headers["content-type"] == "image/png"
    assert frame.headers["cache-control"] == "no-store"

    for path in (
        f"/api/agent-runs/{run_id}/frame",
        f"/api/agent-runs/{run_id}/status",
        f"/api/trips/{trip.id}/bookings",
    ):
        response = await friend.get(path)
        assert response.status_code == 404, path


@pytest.mark.parametrize(
    "run_id", ["..%2F..%2Fetc", "..", "a.b", "x" * 65, "%2E%2E", "b1%2F..%2F..%2Fsecret"]
)
async def test_run_id_path_traversal_is_rejected(
    booking_app: FastAPI, client: AsyncClient, run_id: str
) -> None:
    await _register(client, "org@example.com")
    for suffix in ("frame", "status"):
        response = await client.get(f"/api/agent-runs/{run_id}/{suffix}")
        assert response.status_code in (404, 422), (run_id, response.status_code)


async def test_service_refuses_run_ids_outside_the_pattern(
    database: Database, runs_dir: Path, launcher: FakeLauncher
) -> None:
    service = BookingService(database, launcher, runs_dir)
    for run_id in ("../secret", "a/b", "", "x" * 65):
        result = await service.frame(run_id, "0" * 24)
        assert getattr(result, "error", None) == BookingError.RUN_NOT_FOUND


async def _disrupt(client: AsyncClient, trip: Trip, percent: float) -> dict[str, object]:
    response = await client.post(
        f"/api/trips/{trip.id}/demo/disruption",
        json={"delay_minutes": 140, "price_change_percent": percent},
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_dearer_rebooking_resplits_exactly_and_asks_for_top_ups(
    booking_app: FastAPI, client: AsyncClient, friend: AsyncClient
) -> None:
    organizer = await _register(client, "org@example.com")
    member = await _register(friend, "member@example.com")
    trip, train, _ = await _seed_trip(
        organizer, [member], TripStatus.BOOKED, BookingStatus.CONFIRMED
    )
    body = await _disrupt(client, trip, 3.33)

    new_train = 123_996  # 120 000 * 1.0333
    assert body["total_minor"] == new_train + STAY_MINOR
    shares = body["shares"]
    assert isinstance(shares, list)
    assert sum(share["share_minor"] for share in shares) == new_train + STAY_MINOR
    assert {share["status"] for share in shares} == {ContributionStatus.PENDING}
    assert body["trip_status"] == TripStatus.PAYING

    old = await Booking.get(identifier_of(train))
    assert old is not None and old.status is BookingStatus.CANCELLED
    replacements = body["replacements"]
    assert isinstance(replacements, list) and len(replacements) == 1
    replacement_view = replacements[0]
    replacement = await Booking.get(replacement_view["id"])
    assert replacement is not None
    assert replacement.replaces_booking_id == identifier_of(train)
    assert replacement.amount_minor == new_train
    assert replacement.status is BookingStatus.PENDING
    contributions = await Contribution.find(Contribution.trip_id == identifier_of(trip)).to_list(10)
    assert sum(c.amount_minor for c in contributions) == new_train + STAY_MINOR

    resplit = await TripEvent.find_one(
        TripEvent.trip_id == identifier_of(trip), TripEvent.kind == EventKind.RESPLIT
    )
    assert resplit is not None
    assert resplit.message.startswith("New share: 919.98 PLN each (+19.98 PLN).")
    assert [m["delta_minor"] for m in resplit.payload["members"]] == [1_998, 1_998]
    assert EventKind.DISRUPTION in await _kinds(trip)


@pytest.mark.usefixtures("drain_monitors")
async def test_cheaper_rebooking_marks_refunds_and_goes_straight_to_rebooking(
    booking_app: FastAPI, client: AsyncClient, launcher: FakeLauncher
) -> None:
    organizer = await _register(client, "org@example.com")
    trip, _, _ = await _seed_trip(organizer, [], TripStatus.BOOKED, BookingStatus.CONFIRMED)
    body = await _disrupt(client, trip, -10)
    assert body["total_minor"] == 108_000 + STAY_MINOR
    assert body["trip_status"] == TripStatus.REBOOKING
    shares = body["shares"]
    assert isinstance(shares, list)
    assert shares[0]["status"] == ContributionStatus.REFUND_DUE

    replacements = body["replacements"]
    assert isinstance(replacements, list)
    replacement = replacements[0]
    start = await client.post(
        f"/api/trips/{trip.id}/bookings/{replacement['id']}/start", headers=_csrf(client)
    )
    assert start.status_code == 202, start.text


async def test_disruption_needs_a_confirmed_booking(
    booking_app: FastAPI, client: AsyncClient
) -> None:
    organizer = await _register(client, "org@example.com")
    trip, _, _ = await _seed_trip(organizer, [], TripStatus.BOOKING)
    response = await client.post(
        f"/api/trips/{trip.id}/demo/disruption",
        json={"delay_minutes": 140, "price_change_percent": 5},
        headers=_csrf(client),
    )
    assert response.status_code == 409
    assert response.json()["code"] == BookingError.NOTHING_TO_DISRUPT


async def test_a_confirmed_train_can_be_disrupted_before_the_stay_is_booked(
    booking_app: FastAPI, client: AsyncClient
) -> None:
    """The demo books the train first; the delay scene must not wait for the stay."""
    organizer = await _register(client, "org@example.com")
    trip, train, _ = await _seed_trip(organizer, [], TripStatus.BOOKING)
    await train.set({"status": BookingStatus.CONFIRMED})
    body = await _disrupt(client, trip, 5)
    assert body["cancelled_booking_ids"] == [str(train.id)]


async def _orphan(
    client: AsyncClient, runs_dir: Path, booking_status: BookingStatus
) -> tuple[Trip, Booking, Path]:
    """A booking whose agent run was RUNNING when the backend died: no monitor watches it."""
    organizer = await _register(client, "org@example.com")
    trip, train, _ = await _seed_trip(organizer, [], TripStatus.BOOKING, booking_status)
    run_id = f"b{train.id}-1"
    await AgentRun(
        run_id=run_id, booking_id=identifier_of(train), trip_id=identifier_of(trip)
    ).insert()
    await train.set({"current_run_id": run_id})
    run_dir = runs_dir / run_id
    run_dir.mkdir()
    return trip, train, run_dir


async def test_an_orphaned_run_with_a_result_is_applied(
    booking_app: FastAPI, client: AsyncClient, runs_dir: Path
) -> None:
    trip, train, run_dir = await _orphan(client, runs_dir, BookingStatus.APPROVED)
    result = {"outcome": "done", "reason": "ok", "steps": 9, "confirmation_ref": "SIM-1"}
    _write(run_dir / "result.json", result)

    listing = (await client.get(f"/api/trips/{trip.id}/bookings")).json()
    item = next(b for b in listing["bookings"] if b["id"] == str(train.id))
    assert item["status"] == BookingStatus.CONFIRMED
    assert item["confirmation_ref"] == "SIM-1"
    assert item["run"]["status"] == "finished"
    assert EventKind.BOOKING_CONFIRMED in await _kinds(trip)


async def test_a_purchase_reported_without_an_approval_is_not_confirmed(
    booking_app: FastAPI, client: AsyncClient, runs_dir: Path
) -> None:
    trip, train, run_dir = await _orphan(client, runs_dir, BookingStatus.AWAITING_APPROVAL)
    _write(run_dir / "result.json", {"outcome": "done", "reason": "ok", "steps": 9})

    listing = (await client.get(f"/api/trips/{trip.id}/bookings")).json()
    item = next(b for b in listing["bookings"] if b["id"] == str(train.id))
    assert item["status"] == BookingStatus.HANDOFF
    assert EventKind.BOOKING_CONFIRMED not in await _kinds(trip)


async def test_a_lost_run_fails_its_booking(
    booking_app: FastAPI, client: AsyncClient, runs_dir: Path
) -> None:
    trip, train, _ = await _orphan(client, runs_dir, BookingStatus.AWAITING_APPROVAL)

    listing = (await client.get(f"/api/trips/{trip.id}/bookings")).json()
    item = next(b for b in listing["bookings"] if b["id"] == str(train.id))
    assert item["status"] == BookingStatus.FAILED
    assert item["run"]["outcome"] == AgentOutcome.ERROR
    assert item["run"]["reason"] == "agent process lost (backend restarted)"
    # A failed booking can be started again from the UI.
    start = await client.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/start", headers=_csrf(client)
    )
    assert start.status_code == 202, start.text


@pytest.mark.usefixtures("drain_monitors")
async def test_an_orphaned_but_alive_agent_gets_a_new_monitor(
    booking_app: FastAPI, client: AsyncClient, runs_dir: Path
) -> None:
    trip, train, run_dir = await _orphan(client, runs_dir, BookingStatus.RUNNING)
    (run_dir / "agent.pid").write_text(str(os.getpid()), encoding="utf-8")  # alive: us
    _write(run_dir / "status.json", {"milestone": "review", "step": 5})

    async def synced() -> bool:
        run = await AgentRun.find_one(AgentRun.booking_id == identifier_of(train))
        return run is not None and run.steps == 5

    assert await _booking_status(client, trip, train) == BookingStatus.RUNNING
    await _until(synced, "the re-attached monitor to sync status.json")
    assert len(running_monitors()) == 1
    assert await _booking_status(client, trip, train) == BookingStatus.RUNNING
    assert len(running_monitors()) == 1, "a second listing must not attach a second monitor"


async def test_demo_routes_are_absent_outside_dev_and_test(
    booking_app: FastAPI, client: AsyncClient, settings: Settings
) -> None:
    organizer = await _register(client, "org@example.com")
    trip, _, _ = await _seed_trip(organizer, [], TripStatus.BOOKED, BookingStatus.CONFIRMED)
    production = settings.model_copy(update={"app_env": "prod"})
    booking_app.dependency_overrides[get_settings] = lambda: production

    assert (await client.get("/api/demo-supplier/rail")).status_code == 404
    response = await client.post(
        f"/api/trips/{trip.id}/demo/disruption",
        json={"delay_minutes": 140, "price_change_percent": 5},
        headers=_csrf(client),
    )
    assert response.status_code == 404
