"""Attraction voting and the day plan over HTTP: membership, the vote toggle, the plan, and the
ticket purchase it queues (with the re-split it causes)."""

from typing import Any

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.domain.trips import BookingKind, BookingStatus, EventKind, TripStatus
from app.db.identifiers import to_object_id
from app.repositories.bookings import BookingRepository
from tests.test_trips_flow import Member, MemberFactory, _create_trip, _research, _room
from tests.test_trips_flow import member_factory as member_factory  # the shared fixture

SUPPLIERS = "sim_rail,sim_stay,sim_activity,sim_tickets,sim_sights"


def _use_attraction_suppliers(app: FastAPI, settings: Settings) -> None:
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"suppliers": SUPPLIERS, "demo_supplier_url": "http://localhost:8000"}
    )


async def _trip_after_the_vote(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> tuple[Member, Member, str]:
    _use_attraction_suppliers(app, settings)
    organizer = await member_factory("organizer@example.com")
    friend = await member_factory("friend@example.com")
    trip_id = await _create_trip(organizer, group_size=2)
    invite = (await _room(organizer, trip_id))["invite_code"]
    joined = await friend.post("/api/trips/join", {"invite_code": invite, "display_name": "Ola"})
    assert joined.status_code == 200, joined.text
    await _research(app, organizer, trip_id)
    assert (await organizer.post(f"/api/trips/{trip_id}/voting/close")).status_code == 200
    return organizer, friend, trip_id


async def _attractions(member: Member, trip_id: str) -> dict[str, Any]:
    response = await member.get(f"/api/trips/{trip_id}/attractions")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_attractions_wait_for_the_package_vote(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    _use_attraction_suppliers(app, settings)
    organizer = await member_factory("organizer@example.com")
    trip_id = await _create_trip(organizer)
    response = await organizer.get(f"/api/trips/{trip_id}/attractions")
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_trip_state"


async def test_only_members_see_or_vote(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    organizer, _, trip_id = await _trip_after_the_vote(app, settings, member_factory)
    stranger = await member_factory("stranger@example.com")
    first = (await _attractions(organizer, trip_id))["attractions"][0]["attraction_id"]
    for response in (
        await stranger.get(f"/api/trips/{trip_id}/attractions"),
        await stranger.post(f"/api/trips/{trip_id}/attractions/{first}/vote"),
        await stranger.get(f"/api/trips/{trip_id}/itinerary"),
        await stranger.post(f"/api/trips/{trip_id}/itinerary/generate"),
    ):
        assert response.status_code == 404, response.text


async def test_candidates_are_ranked_snapshotted_and_never_in_the_package(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    organizer, friend, trip_id = await _trip_after_the_vote(app, settings, member_factory)
    listed = await _attractions(organizer, trip_id)
    assert listed["destination"] == "Prague"
    attractions = listed["attractions"]
    assert 8 <= len(attractions) <= 12
    assert [a["rank"] for a in attractions] == sorted(a["rank"] for a in attractions)
    museum = next(a for a in attractions if a["title"] == "National Museum")
    assert museum["kind"] == "museum" and museum["bookable"] is True
    assert museum["price_per_person_minor"] == 7_000
    assert museum["lat"] is not None and museum["opens"] == "10:00"
    bridge = next(a for a in attractions if a["title"] == "Charles Bridge")
    assert bridge["bookable"] is False and bridge["price_per_person_minor"] is None
    # The same list for everyone, every time.
    assert (await _attractions(friend, trip_id))["attractions"] == attractions
    # Package items never come from an itinerary-only attraction supplier.
    trip_oid = to_object_id(trip_id)
    assert trip_oid is not None
    bookings = await BookingRepository().for_trip(trip_oid)
    assert all(b.supplier_id not in ("sim_tickets", "sim_sights") for b in bookings)


async def test_vote_toggle_with_voters_and_a_feed_message(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    organizer, friend, trip_id = await _trip_after_the_vote(app, settings, member_factory)
    museum = next(
        a for a in (await _attractions(friend, trip_id))["attractions"] if a["kind"] == "museum"
    )
    path = f"/api/trips/{trip_id}/attractions/{museum['attraction_id']}/vote"

    voted = await friend.post(path)
    assert voted.status_code == 200, voted.text
    after = next(
        a for a in voted.json()["attractions"] if a["attraction_id"] == museum["attraction_id"]
    )
    assert after["votes"] == 1 and after["voted_by_me"] is True
    assert [v["display_name"] for v in after["voters"]] == ["Ola"]
    seen_by_organizer = next(
        a
        for a in (await _attractions(organizer, trip_id))["attractions"]
        if a["attraction_id"] == museum["attraction_id"]
    )
    assert seen_by_organizer["votes"] == 1 and seen_by_organizer["voted_by_me"] is False

    feed = (await organizer.get(f"/api/trips/{trip_id}/feed")).json()
    wants = [e for e in feed if e["kind"] == EventKind.ATTRACTION_VOTED]
    assert [e["message"] for e in wants] == [f"Ola wants {museum['title']}."]

    withdrawn = await friend.post(path)
    again = next(
        a for a in withdrawn.json()["attractions"] if a["attraction_id"] == museum["attraction_id"]
    )
    assert again["votes"] == 0 and again["voted_by_me"] is False
    unknown = await friend.post(f"/api/trips/{trip_id}/attractions/a000000000000/vote")
    assert unknown.status_code == 404 and unknown.json()["code"] == "attraction_not_found"


async def test_only_the_organizer_plans(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    _, friend, trip_id = await _trip_after_the_vote(app, settings, member_factory)
    response = await friend.post(f"/api/trips/{trip_id}/itinerary/generate")
    assert response.status_code == 403
    empty = await friend.get(f"/api/trips/{trip_id}/itinerary")
    assert empty.status_code == 200 and empty.json()["days"] == []


async def test_the_plan_queues_tickets_and_resplits(
    app: FastAPI, settings: Settings, member_factory: MemberFactory
) -> None:
    organizer, friend, trip_id = await _trip_after_the_vote(app, settings, member_factory)
    attractions = (await _attractions(organizer, trip_id))["attractions"]
    museum = next(a for a in attractions if a["title"] == "National Museum")
    bridge = next(a for a in attractions if a["title"] == "Charles Bridge")
    for member in (organizer, friend):
        for attraction in (museum, bridge):
            path = f"/api/trips/{trip_id}/attractions/{attraction['attraction_id']}/vote"
            assert (await member.post(path)).status_code == 200
    before = (await _room(organizer, trip_id))["trip"]["total_minor"]

    planned = await organizer.post(f"/api/trips/{trip_id}/itinerary/generate")
    assert planned.status_code == 200, planned.text
    plan = planned.json()
    assert [d["date"] for d in plan["days"]] == ["2026-11-20", "2026-11-21", "2026-11-22"]
    assert plan["stale"] is False
    items = [item for day in plan["days"] for item in day["items"]]
    visits = {i["attraction_id"]: i for i in items if i["kind"] == "attraction"}
    assert set(visits) == {museum["attraction_id"], bridge["attraction_id"]}
    assert visits[museum["attraction_id"]]["tickets"] == "to_buy"
    assert visits[bridge["attraction_id"]]["tickets"] is None
    assert visits[museum["attraction_id"]]["map_url"].startswith("https://www.openstreetmap.org")
    assert {"travel", "meal"} <= {i["kind"] for i in items}

    trip_oid = to_object_id(trip_id)
    assert trip_oid is not None
    tickets = [
        b
        for b in await BookingRepository().for_trip(trip_oid)
        if b.supplier_id == "sim_tickets"
    ]
    assert len(tickets) == 1
    (ticket,) = tickets
    assert ticket.kind is BookingKind.ACTIVITY and ticket.status is BookingStatus.PENDING
    assert ticket.amount_minor == 2 * 7_000
    assert ticket.supplier_url.startswith("http://localhost:8000/api/demo-supplier/tickets")
    slot = visits[museum["attraction_id"]]["start"]
    assert f"entry at {slot}" in ticket.goal and "Budget: 140.00 PLN" in ticket.goal
    room = await _room(organizer, trip_id)
    assert room["trip"]["total_minor"] == before + 14_000
    assert sum(c["amount_minor"] for c in room["contributions"]) == before + 14_000
    feed = (await organizer.get(f"/api/trips/{trip_id}/feed")).json()
    assert any(
        e["kind"] == EventKind.ITINERARY_READY and e["message"].startswith("Here is the plan for")
        for e in feed
    )

    # A changed vote makes the plan stale; planning again keeps the queued tickets once.
    extra = next(a for a in attractions if a["title"] == "Lennon Wall")
    await friend.post(f"/api/trips/{trip_id}/attractions/{extra['attraction_id']}/vote")
    assert (await organizer.get(f"/api/trips/{trip_id}/itinerary")).json()["stale"] is True
    again = await organizer.post(f"/api/trips/{trip_id}/itinerary/generate")
    assert again.status_code == 200
    tickets = [
        b
        for b in await BookingRepository().for_trip(trip_oid)
        if b.supplier_id == "sim_tickets"
    ]
    assert len(tickets) == 1
    assert (await _room(organizer, trip_id))["trip"]["total_minor"] == before + 14_000

    # Dropping the museum from the votes drops its queued tickets and the money with them.
    for member in (organizer, friend):
        await member.post(f"/api/trips/{trip_id}/attractions/{museum['attraction_id']}/vote")
    await organizer.post(f"/api/trips/{trip_id}/itinerary/generate")
    assert not [
        b
        for b in await BookingRepository().for_trip(trip_oid)
        if b.supplier_id == "sim_tickets"
    ]
    room = await _room(organizer, trip_id)
    assert room["trip"]["total_minor"] == before
    assert room["trip"]["status"] == TripStatus.PAYING
