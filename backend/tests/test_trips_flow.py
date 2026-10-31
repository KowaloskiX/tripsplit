"""The trip money path over HTTP: create -> join -> research -> vote -> close -> pay -> booking."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.background import BackgroundRunner
from app.core.config import Settings, get_settings
from app.core.domain.trips import BookingStatus, EventKind, TripStatus
from app.core.http_security import CSRF_HEADER_NAME
from app.db.identifiers import to_object_id
from app.repositories.bookings import BookingRepository

PASSWORD = "correct-horse-battery-staple"

TRIP = {
    "title": "Weekend in Prague",
    "origin": "Warszawa",
    "brief": "weekend in Prague for 6 from Warsaw, cheap, good food",
    "date_from": "2026-11-20",
    "date_to": "2026-11-22",
    "group_size": 6,
    "display_name": "Łukasz",
}


class Member:
    """One signed-in browser: its own cookie jar and CSRF token."""

    def __init__(self, client: AsyncClient, settings: Settings) -> None:
        self.client = client
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        token = self.client.cookies.get(self._settings.effective_csrf_cookie_name)
        assert token is not None, "the CSRF cookie is missing"
        return {CSRF_HEADER_NAME: token}

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return await self.client.post(path, json=body or {}, headers=self._headers())

    async def get(self, path: str) -> Any:
        return await self.client.get(path)


type MemberFactory = Callable[[str], Awaitable[Member]]


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


def _runner(app: FastAPI) -> BackgroundRunner:
    runner: BackgroundRunner = app.state.background
    return runner


async def _create_trip(organizer: Member, **overrides: Any) -> str:
    response = await organizer.post("/api/trips", {**TRIP, **overrides})
    assert response.status_code == 201, response.text
    trip_id: str = response.json()["trip_id"]
    return trip_id


async def _room(member: Member, trip_id: str) -> dict[str, Any]:
    response = await member.get(f"/api/trips/{trip_id}")
    assert response.status_code == 200, response.text
    room: dict[str, Any] = response.json()
    return room


async def _research(app: FastAPI, organizer: Member, trip_id: str) -> list[dict[str, Any]]:
    response = await organizer.post(f"/api/trips/{trip_id}/proposals/generate")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == TripStatus.PROPOSING
    await _runner(app).drain()
    room = await _room(organizer, trip_id)
    assert room["trip"]["status"] == TripStatus.VOTING
    proposals: list[dict[str, Any]] = room["proposals"]
    return proposals


async def test_full_flow_from_brief_to_booking(app: FastAPI, member_factory: MemberFactory) -> None:
    organizer = await member_factory("organizer@example.com")
    friend = await member_factory("friend@example.com")
    trip_id = await _create_trip(organizer)

    invite_code = (await _room(organizer, trip_id))["invite_code"]
    joined = await friend.post(
        "/api/trips/join", {"invite_code": invite_code, "display_name": "Ola"}
    )
    assert joined.status_code == 200, joined.text
    again = await friend.post(
        "/api/trips/join", {"invite_code": invite_code, "display_name": "Ola"}
    )
    assert again.status_code == 200, "joining twice must be idempotent"

    seeded = await organizer.post(f"/api/trips/{trip_id}/demo/seed-members", {"count": 4})
    assert seeded.json() == {"affected": 4}
    assert len((await _room(organizer, trip_id))["members"]) == 6

    proposals = await _research(app, organizer, trip_id)
    assert len(proposals) == 3
    assert all(p["per_person_minor"] * 6 >= p["total_minor"] for p in proposals)

    comfort = proposals[1]["id"]
    assert (
        await friend.post(f"/api/trips/{trip_id}/votes", {"proposal_id": comfort})
    ).status_code == 200
    voted = await organizer.post(f"/api/trips/{trip_id}/demo/vote-all", {"proposal_id": comfort})
    assert voted.json() == {"affected": 4}
    room = await _room(friend, trip_id)
    assert room["my_vote_proposal_id"] == comfort
    assert [p["votes"] for p in room["proposals"]] == [0, 5, 0]

    closed = await organizer.post(f"/api/trips/{trip_id}/voting/close")
    assert closed.status_code == 200, closed.text
    room = await _room(organizer, trip_id)
    assert room["trip"]["status"] == TripStatus.PAYING
    assert room["trip"]["chosen_proposal_id"] == comfort
    shares = [c["amount_minor"] for c in room["contributions"]]
    assert len(shares) == 6
    assert sum(shares) == room["trip"]["total_minor"]

    trip_oid = to_object_id(trip_id)
    assert trip_oid is not None
    bookings = await BookingRepository().for_trip(trip_oid)
    assert len(bookings) == len(proposals[1]["items"])
    assert all(b.status is BookingStatus.PENDING for b in bookings)
    assert all("6" in b.goal and "Stop at the summary before paying." in b.goal for b in bookings)

    # Everyone but the organizer pays — the trip must NOT move to booking yet (rule #1).
    assert (await friend.post(f"/api/trips/{trip_id}/contributions/pay")).status_code == 200
    paid_by_demo = await organizer.post(f"/api/trips/{trip_id}/demo/pay-all")
    assert paid_by_demo.json() == {"affected": 4}, "the friend already paid; four fake members left"
    room = await _room(organizer, trip_id)
    assert room["trip"]["status"] == TripStatus.PAYING
    assert room["paid_count"] == 5

    last = await organizer.post(f"/api/trips/{trip_id}/contributions/pay")
    assert last.status_code == 200, last.text
    assert last.json()["all_paid"] is True
    assert (await _room(organizer, trip_id))["trip"]["status"] == TripStatus.BOOKING

    twice = await organizer.post(f"/api/trips/{trip_id}/contributions/pay")
    assert twice.status_code == 409

    feed = (await organizer.get(f"/api/trips/{trip_id}/feed")).json()
    kinds = [event["kind"] for event in feed]
    assert kinds.count(EventKind.ALL_PAID) == 1
    for expected in (
        EventKind.TRIP_CREATED,
        EventKind.MEMBER_JOINED,
        EventKind.PROPOSALS_READY,
        EventKind.VOTE_CAST,
        EventKind.PROPOSAL_CHOSEN,
        EventKind.CONTRIBUTION_PAID,
    ):
        assert expected in kinds


async def test_non_member_sees_404_everywhere(app: FastAPI, member_factory: MemberFactory) -> None:
    organizer = await member_factory("organizer@example.com")
    stranger = await member_factory("stranger@example.com")
    trip_id = await _create_trip(organizer)

    for response in (
        await stranger.get(f"/api/trips/{trip_id}"),
        await stranger.get(f"/api/trips/{trip_id}/feed"),
        await stranger.post(f"/api/trips/{trip_id}/messages", {"text": "hi"}),
        await stranger.post(f"/api/trips/{trip_id}/proposals/generate"),
        await stranger.post(f"/api/trips/{trip_id}/contributions/pay"),
        await stranger.get("/api/trips/not-an-id"),
    ):
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "trip_not_found"
    assert (await stranger.get("/api/trips")).json() == []


async def test_only_the_organizer_runs_the_trip(
    app: FastAPI, member_factory: MemberFactory
) -> None:
    organizer = await member_factory("organizer@example.com")
    friend = await member_factory("friend@example.com")
    trip_id = await _create_trip(organizer)
    code = (await _room(organizer, trip_id))["invite_code"]
    await friend.post("/api/trips/join", {"invite_code": code, "display_name": "Kuba"})

    assert (await friend.post(f"/api/trips/{trip_id}/proposals/generate")).status_code == 403
    await _research(app, organizer, trip_id)
    assert (await friend.post(f"/api/trips/{trip_id}/voting/close")).status_code == 403


async def test_odd_split_sums_to_the_total(app: FastAPI, member_factory: MemberFactory) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _create_trip(organizer, group_size=7)
    await organizer.post(f"/api/trips/{trip_id}/demo/seed-members", {"count": 6})
    await _research(app, organizer, trip_id)
    # No votes at all: the earliest package wins.
    assert (await organizer.post(f"/api/trips/{trip_id}/voting/close")).status_code == 200

    room = await _room(organizer, trip_id)
    shares = [c["amount_minor"] for c in room["contributions"]]
    assert room["trip"]["chosen_proposal_id"] == room["proposals"][0]["id"]
    assert len(shares) == 7
    assert sum(shares) == room["trip"]["total_minor"]
    assert max(shares) - min(shares) <= 1


async def test_feed_messages_and_after_filter(app: FastAPI, member_factory: MemberFactory) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _create_trip(organizer)
    posted = await organizer.post(f"/api/trips/{trip_id}/messages", {"text": "  Who's in?  "})
    assert posted.status_code == 201, posted.text
    event = posted.json()
    assert event["message"] == "Who's in?"
    assert event["actor"] == "member"
    assert event["actor_name"] == "Łukasz"

    feed = (await organizer.get(f"/api/trips/{trip_id}/feed")).json()
    assert [e["kind"] for e in feed] == [EventKind.TRIP_CREATED, EventKind.MESSAGE]
    newer = await organizer.client.get(
        f"/api/trips/{trip_id}/feed", params={"after": feed[0]["created_at"]}
    )
    assert [e["id"] for e in newer.json()] == [event["id"]]


async def test_voting_is_closed_outside_the_voting_stage(
    app: FastAPI, member_factory: MemberFactory
) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _create_trip(organizer)
    response = await organizer.post(f"/api/trips/{trip_id}/voting/close")
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_trip_state"


async def test_trip_dates_must_be_in_order(member_factory: MemberFactory) -> None:
    organizer = await member_factory("organizer@example.com")
    response = await organizer.post(
        "/api/trips", {**TRIP, "date_from": "2026-11-22", "date_to": "2026-11-20"}
    )
    assert response.status_code == 422


async def test_demo_routes_do_not_exist_in_production(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    organizer = await member_factory("organizer@example.com")
    trip_id = await _create_trip(organizer)

    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"app_env": "prod"})
    for path, body in (
        ("seed-members", {"count": 2}),
        ("vote-all", {"proposal_id": "0" * 24}),
        ("pay-all", None),
    ):
        response = await organizer.post(f"/api/trips/{trip_id}/demo/{path}", body)
        assert response.status_code == 404, f"{path}: {response.text}"
