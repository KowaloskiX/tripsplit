"""The chat flow: the research's options (`GET /trips/{id}/options`) and the organizer's own
package from one pick of each (`POST /trips/{id}/selection`) — chosen and the vote closed in
one go, with shares and bookings exactly as when a vote closes."""

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.ai.research import PackageItemPlan, PackagePlan, ResearchCandidates
from app.core.domain.trips import BookingKind, EventKind, TransportMode, TripStatus
from app.db.identifiers import to_object_id
from app.models.bookings import Booking
from app.models.trips import Proposal, TripEvent
from app.schemas.trips import TripSelectionRequest
from app.services.trip_options import (
    as_plans,
    candidate_options,
    custom_package,
    from_plans,
    stored_options,
)
from tests.test_pay_all import launcher, wallet_app, wallet_settings  # noqa: F401 — fixtures
from tests.test_wallet import TRIP, Browser, _drain, browsers  # noqa: F401 — fixtures too

# ---- pure -----------------------------------------------------------------------------------


def _item(kind: BookingKind, title: str, price: int, **extra: object) -> PackageItemPlan:
    return PackageItemPlan(
        kind=kind,
        title=title,
        supplier="Sim",
        supplier_url="https://example.com",
        price_minor=price,
        supplier_id="sim",
        offer_ref=title,
        mode=TransportMode.RAIL if kind is BookingKind.TRANSPORT else None,
        supplier_data=dict(extra),
    )


TRAIN = _item(BookingKind.TRANSPORT, "IC 1", 40_000)
BUS = _item(BookingKind.TRANSPORT, "Bus 2", 20_000)
HOSTEL = _item(BookingKind.STAY, "Hostel", 30_000, rating=8.5)
HOTEL = _item(BookingKind.STAY, "Hotel", 60_000)
TOUR = _item(BookingKind.ACTIVITY, "Tour", 10_000)
IDEA = _item(BookingKind.ACTIVITY, "Old Town walk", 0)


def test_options_fall_back_to_the_packages_items_deduplicated_without_free_ideas() -> None:
    plans = [
        PackagePlan("Budget", "", (BUS, HOSTEL)),
        PackagePlan("Comfort", "", (TRAIN, HOSTEL, TOUR, IDEA)),
        PackagePlan("Splurge", "", (TRAIN, HOTEL, TOUR)),
    ]
    options = candidate_options(plans, ResearchCandidates())
    assert [t[0].title for t in options.transports] == ["Bus 2", "IC 1"]
    assert [s.title for s in options.stays] == ["Hostel", "Hotel"]
    assert [a.title for a in options.activities] == ["Tour"]


def test_the_researchers_own_candidates_win_and_survive_the_link_check_round_trip() -> None:
    found = ResearchCandidates(transports=[(TRAIN,), (BUS, BUS)], stays=[HOTEL], activities=[])
    options = candidate_options([PackagePlan("x", "", (TRAIN,))], found)
    assert len(options.transports) == 2
    back = from_plans(options, as_plans(options))
    assert back.transports == options.transports and back.stays == [HOTEL]
    transport, stays, activities = stored_options(back)
    assert [o.option_id for o in transport] == ["t0", "t1"]
    assert len(transport[1].items) == 2
    assert [o.option_id for o in stays] == ["s0"] and activities == []


def test_a_custom_package_is_priced_per_person_and_budget_flagged() -> None:
    transport, stays, activities = stored_options(
        ResearchCandidates(transports=[(TRAIN,)], stays=[HOSTEL], activities=[TOUR])
    )
    package = custom_package(
        [transport[0], stays[0], activities[0]],
        travellers=2,
        budget_per_person_minor=35_000,
        currency="PLN",
    )
    assert package.total_minor == 80_000
    assert package.per_person_minor == 40_000
    assert package.over_budget is True
    assert package.title.startswith("Your pick: Sim train + Hostel")


def test_the_selection_request_takes_scalar_ids_only() -> None:
    ok = TripSelectionRequest(transport_option_id="t1", activity_option_ids="a0,a2")
    assert ok.activities == ["a0", "a2"] and ok.stay_option_id is None
    for bad in (
        {"transport_option_id": "x"},
        {"transport_option_id": "t0", "activity_option_ids": "a0;drop"},
    ):
        with pytest.raises(ValidationError):
            TripSelectionRequest.model_validate(bad)


# ---- HTTP -----------------------------------------------------------------------------------


async def _researched_trip(app: FastAPI, anna: Browser, kuba: Browser) -> str:
    trip_id: str = (await anna.post("/api/trips", TRIP)).json()["trip_id"]
    code = (await anna.get(f"/api/trips/{trip_id}")).json()["invite_code"]
    await kuba.post("/api/trips/join", {"invite_code": code, "display_name": "Kuba"})
    early = await anna.get(f"/api/trips/{trip_id}/options")
    assert early.status_code == 409  # nothing researched yet
    await anna.post(f"/api/trips/{trip_id}/proposals/generate")
    await _drain(app)
    return trip_id


async def test_options_list_every_candidate_with_trust_fields(
    wallet_app: FastAPI,  # noqa: F811
    browsers: list[Browser],  # noqa: F811
) -> None:
    anna, kuba = browsers
    trip_id = await _researched_trip(wallet_app, anna, kuba)
    response = await kuba.get(f"/api/trips/{trip_id}/options")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["travellers"] == 2
    assert body["transport"] and body["stays"] and body["activities"]
    first = body["transport"][0]
    assert first["option_id"] == "t0" and first["kind"] == "transport"
    assert first["per_person_minor"] * 2 >= first["total_minor"]
    assert first["items"][0]["provenance"]["source"] == "example"
    prices = [option["total_minor"] for option in body["stays"]]
    assert prices == sorted(prices)


async def test_selection_builds_one_package_and_closes_the_vote(
    wallet_app: FastAPI,  # noqa: F811
    browsers: list[Browser],  # noqa: F811
) -> None:
    anna, kuba = browsers
    trip_id = await _researched_trip(wallet_app, anna, kuba)
    options = (await anna.get(f"/api/trips/{trip_id}/options")).json()
    transport, stay = options["transport"][-1], options["stays"][0]
    activity = options["activities"][0]
    picks = {
        "transport_option_id": transport["option_id"],
        "stay_option_id": stay["option_id"],
        "activity_option_ids": activity["option_id"],
    }

    assert (await kuba.post(f"/api/trips/{trip_id}/selection", picks)).status_code == 403
    unknown = await anna.post(f"/api/trips/{trip_id}/selection", {**picks, "stay_option_id": "s99"})
    assert unknown.status_code == 404 and unknown.json()["code"] == "option_not_found"

    chosen = await anna.post(f"/api/trips/{trip_id}/selection", picks)
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["status"] == TripStatus.PAYING

    room = (await anna.get(f"/api/trips/{trip_id}")).json()
    total = transport["total_minor"] + stay["total_minor"] + activity["total_minor"]
    assert room["trip"]["total_minor"] == total
    picked = next(p for p in room["proposals"] if p["chosen"])
    assert picked["id"] == room["trip"]["chosen_proposal_id"]
    assert picked["title"].startswith("Your pick:")
    assert len(picked["items"]) == len(transport["items"]) + 2
    assert sum(c["amount_minor"] for c in room["contributions"]) == total
    assert len(room["contributions"]) == 2

    trip_oid = to_object_id(trip_id)
    bookings = await Booking.find(Booking.trip_id == trip_oid).to_list()
    assert sum(b.amount_minor for b in bookings) == total
    assert await Proposal.find(Proposal.trip_id == trip_oid).count() == 4
    events = await TripEvent.find(
        TripEvent.trip_id == trip_oid, TripEvent.kind == EventKind.PROPOSAL_CHOSEN
    ).to_list()
    assert [e.message.startswith("Picked step by step") for e in events] == [True]

    again = await anna.post(f"/api/trips/{trip_id}/selection", picks)
    assert again.status_code == 409  # the vote is closed: no second package
