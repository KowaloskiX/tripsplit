"""The demo director over HTTP, on a fast clock: it plays a whole group trip through the real
services, and every rule of the product still holds after each of its moves."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.background import BackgroundRunner
from app.core.config import Settings, get_settings
from app.core.domain.trips import BookingKind, BookingStatus, EventKind, TripStatus
from app.core.http_security import CSRF_HEADER_NAME
from app.db.identifiers import to_object_id
from app.harness.invariants import InvariantContext, Snapshot, Violation, check_all, load_snapshot
from app.repositories.bookings import BookingRepository
from app.routes.demo_director import get_director_tuning
from app.services.demo_director import DirectorTimings, DirectorTuning, initials_of

PASSWORD = "correct-horse-battery-staple"
TRIP = {
    "title": "Weekend in Prague",
    "origin": "Warszawa",
    "destination": "Prague",
    "brief": "weekend in Prague for 6 from Warsaw, cheap, good food",
    "date_from": "2026-11-20",
    "date_to": "2026-11-22",
    "group_size": 6,
    "display_name": "Łukasz Organizer",
}
FAST = DirectorTimings(beat_s=(0.0, 0.0), poll_s=0.01, research_wait_s=10.0,
                       payment_wait_s=10.0, booking_wait_s=0.05)  # fmt: skip


class Member:
    def __init__(self, client: AsyncClient, settings: Settings) -> None:
        self.client = client
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        token = self.client.cookies.get(self._settings.effective_csrf_cookie_name)
        assert token is not None, "the CSRF cookie is missing"
        return {CSRF_HEADER_NAME: token}

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return await self.client.post(path, json=body or {}, headers=self._headers())

    async def delete(self, path: str) -> Any:
        return await self.client.delete(path, headers=self._headers())

    async def get(self, path: str) -> Any:
        return await self.client.get(path)


type MemberFactory = Callable[[str], Awaitable[Member]]


class InvariantWatch:
    """Snapshots the trip at every pause of the director and checks every harness invariant
    against the move it just made — the harness's own definition of "rules still hold"."""

    def __init__(self) -> None:
        self.trip_id: str | None = None
        self.before: Snapshot | None = None
        self.violations: list[Violation] = []
        self.checks = 0

    async def sleep(self, _seconds: float) -> None:
        await asyncio.sleep(0)
        trip_oid = to_object_id(self.trip_id) if self.trip_id else None
        if trip_oid is None:
            return
        after = await load_snapshot(trip_oid)
        trail = [self.before.trip.status] if self.before is not None else []
        context = InvariantContext(
            before=self.before, after=after, status_trail=[*trail, after.trip.status], holds=False
        )
        self.violations += check_all(context, known={})
        self.checks += 1
        self.before = after


@pytest.fixture
def watch(app: FastAPI) -> InvariantWatch:
    observer = InvariantWatch()
    app.dependency_overrides[get_director_tuning] = lambda: DirectorTuning(observer.sleep, FAST)
    return observer


@pytest.fixture
async def member_factory(app: FastAPI, settings: Settings) -> AsyncIterator[MemberFactory]:
    clients: list[AsyncClient] = []

    async def create(email: str) -> Member:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        await client.get("/api/auth/session")
        member = Member(client, settings)
        response = await member.post(
            "/api/auth/register",
            {"email": email, "password": PASSWORD, "organization_name": email.split("@")[0]},
        )
        assert response.status_code == 201, response.text
        return member

    yield create
    for client in clients:
        await client.aclose()


async def _drain(app: FastAPI) -> None:
    runner: BackgroundRunner = app.state.background
    await runner.drain()


async def _trip(organizer: Member) -> str:
    response = await organizer.post("/api/trips", TRIP)
    assert response.status_code == 201, response.text
    trip_id: str = response.json()["trip_id"]
    return trip_id


async def _direct(organizer: Member, trip_id: str, **body: Any) -> dict[str, Any]:
    response = await organizer.post(f"/api/trips/{trip_id}/demo/director", {"pace": "fast", **body})
    assert response.status_code == 202, response.text
    progress: dict[str, Any] = response.json()
    return progress


async def _progress(organizer: Member, trip_id: str) -> dict[str, Any]:
    response = await organizer.get(f"/api/trips/{trip_id}/demo/director")
    assert response.status_code == 200, response.text
    progress: dict[str, Any] = response.json()
    return progress


async def _phones(member: Member, trip_id: str) -> dict[str, Any]:
    response = await member.get(f"/api/trips/{trip_id}/demo/phones")
    assert response.status_code == 200, response.text
    phones: dict[str, Any] = response.json()
    return phones


async def _status(organizer: Member, trip_id: str) -> str:
    response = await organizer.get(f"/api/trips/{trip_id}")
    status: str = response.json()["trip"]["status"]
    return status


async def test_the_full_script_plays_the_whole_trip_through_the_rules(
    app: FastAPI, member_factory: MemberFactory, watch: InvariantWatch
) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _trip(organizer)
    watch.trip_id = trip_id

    started = await _direct(organizer, trip_id, script="full")
    assert started["state"] == "running"
    assert started["features"] == {"auto_book": False, "wallet": False}
    await _drain(app)

    progress = await _progress(organizer, trip_id)
    assert progress["state"] == "done", progress["error"]
    assert progress["phase"] == "finished"
    phases = [beat["phase"] for beat in progress["beats"]]
    for phase in ("joining", "researching", "voting", "paying", "booking", "disruption"):
        assert phase in phases, f"no beat in {phase}"
    # No AUTO_BOOK and nobody bought: the director hands over and skips the disruption.
    assert progress["beats"][-1]["text"].startswith("No confirmed transport")
    assert await _status(organizer, trip_id) == TripStatus.BOOKING

    grid = await _phones(organizer, trip_id)
    phones = grid["phones"]
    assert len(phones) == 6
    assert sum(phone["is_organizer"] for phone in phones) == 1
    assert sum(phone["is_demo"] for phone in phones) == 5
    assert all(phone["paid"] and phone["amount_minor"] for phone in phones)
    friends = [phone for phone in phones if phone["is_demo"]]
    assert len({phone["voted_for_title"] for phone in friends}) == 1, "the votes converged"
    assert any(phone["last_message"] and "BLIK" in phone["last_message"] for phone in friends)

    feed = (await organizer.get(f"/api/trips/{trip_id}/feed")).json()
    kinds = [event["kind"] for event in feed]
    messages = [event["message"] for event in feed if event["kind"] == EventKind.MESSAGE]
    assert "I'm in!" in messages
    assert "Prague in Nov 🍻" in messages
    assert kinds.count(EventKind.MEMBER_JOINED) == 5
    assert kinds.count(EventKind.CONTRIBUTION_PAID) == 6
    assert kinds.count(EventKind.ALL_PAID) == 1
    # The spread: more votes cast than voters (two friends changed their minds).
    assert kinds.count(EventKind.VOTE_CAST) > 5

    assert watch.checks > 10
    assert watch.violations == []


async def test_the_presenter_makes_the_last_payment(
    app: FastAPI, member_factory: MemberFactory, watch: InvariantWatch
) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _trip(organizer)
    watch.trip_id = trip_id
    await organizer.post(f"/api/trips/{trip_id}/demo/seed-members", {"count": 5})
    await organizer.post(f"/api/trips/{trip_id}/proposals/generate")
    await _drain(app)

    await _direct(organizer, trip_id, script="vote_and_pay", leave_organizer_payment=True)
    for _ in range(500):
        if (await _progress(organizer, trip_id))["phase"] == "waiting_for_organizer":
            break
        await asyncio.sleep(0.01)
    assert await _status(organizer, trip_id) == TripStatus.PAYING, "the last share is still open"

    paid = await organizer.post(f"/api/trips/{trip_id}/contributions/pay")
    assert paid.status_code == 200, paid.text
    await _drain(app)

    progress = await _progress(organizer, trip_id)
    assert progress["state"] == "done", progress["error"]
    assert await _status(organizer, trip_id) == TripStatus.BOOKING
    assert watch.violations == []


async def test_the_disruption_script_rebooks_and_the_friends_top_up(
    app: FastAPI, member_factory: MemberFactory, watch: InvariantWatch
) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _trip(organizer)
    await _direct(organizer, trip_id, script="full", with_disruption=False)
    await _drain(app)
    # The agent bought the train (as AUTO_BOOK or the presenter would on stage).
    trip_oid = to_object_id(trip_id)
    assert trip_oid is not None
    repository = BookingRepository()
    for booking in await repository.for_trip(trip_oid):
        if booking.kind is BookingKind.TRANSPORT:
            await repository.update(booking, {"status": BookingStatus.CONFIRMED})
    watch.trip_id = trip_id

    await _direct(organizer, trip_id, script="disruption")
    await _drain(app)

    progress = await _progress(organizer, trip_id)
    assert progress["state"] == "done", progress["error"]
    assert "topping_up" in [beat["phase"] for beat in progress["beats"]]
    assert all(phone["paid"] for phone in (await _phones(organizer, trip_id))["phones"])
    # The dearer replacement was topped up; the agent may buy it again.
    assert await _status(organizer, trip_id) == TripStatus.REBOOKING
    assert watch.violations == []


async def test_one_run_per_trip_and_it_can_be_stopped(
    app: FastAPI, member_factory: MemberFactory
) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _trip(organizer)
    slow = DirectorTimings((5.0, 5.0), 1.0, 10.0, 10.0, 10.0)
    app.dependency_overrides[get_director_tuning] = lambda: DirectorTuning(timings=slow)

    await _direct(organizer, trip_id, script="full")
    again = await organizer.post(f"/api/trips/{trip_id}/demo/director", {"script": "full"})
    assert again.status_code == 409

    stopped = await organizer.delete(f"/api/trips/{trip_id}/demo/director")
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["state"] == "stopped"
    assert (await _progress(organizer, trip_id))["state"] == "stopped"


async def test_only_the_organizer_directs_and_members_see_the_phones(
    app: FastAPI, member_factory: MemberFactory
) -> None:
    organizer = await member_factory("organizer@example.com")
    friend = await member_factory("friend@example.com")
    stranger = await member_factory("stranger@example.com")
    trip_id = await _trip(organizer)
    invite = (await organizer.get(f"/api/trips/{trip_id}")).json()["invite_code"]
    joined = await friend.post("/api/trips/join", {"invite_code": invite, "display_name": "Friend"})
    assert joined.status_code in (200, 201), joined.text

    refused = await friend.post(f"/api/trips/{trip_id}/demo/director", {"script": "full"})
    assert refused.status_code == 403
    assert (await friend.get(f"/api/trips/{trip_id}/demo/director")).status_code == 404
    assert (await stranger.get(f"/api/trips/{trip_id}/demo/phones")).status_code == 404

    grid = await _phones(friend, trip_id)
    assert [phone["initials"] for phone in grid["phones"]] == ["ŁO", "F"]
    assert grid["phones"][0]["amount_minor"] is None


async def test_director_routes_do_not_exist_in_production(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _trip(organizer)
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"app_env": "prod"})

    assert (await organizer.post(f"/api/trips/{trip_id}/demo/director", {})).status_code == 404
    assert (await organizer.get(f"/api/trips/{trip_id}/demo/director")).status_code == 404
    assert (await organizer.delete(f"/api/trips/{trip_id}/demo/director")).status_code == 404
    assert (await organizer.get(f"/api/trips/{trip_id}/demo/phones")).status_code == 404


def test_initials() -> None:
    assert initials_of("Ola Nowak") == "ON"
    assert initials_of("kuba") == "K"
    assert initials_of("  ") == "?"
