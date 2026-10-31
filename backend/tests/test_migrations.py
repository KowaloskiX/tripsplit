"""The data migrations in `backend/migrations/` — run forward and backward against real Mongo.

Every migration ships with a `Backward` class (docs/conventions/04); this proves both
directions on documents written in the OLD shape, and that the new models read them before and
after the backfill (the expand step).
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from beanie import PydanticObjectId

from app.core.domain.trips import BookingKind, SupplierChannel, TransportMode
from app.db.client import Database
from app.models.bookings import Booking
from app.models.trips import Proposal, Trip

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUPPLIER_PLUGINS = _load("20261031_120000_supplier_plugins")
TRIP_PREFERENCES = _load("20261031_150000_trip_preferences")
DEPARTS = datetime(2026, 11, 20, 7, 52, tzinfo=UTC)


def _old_booking(trip_id: PydanticObjectId, kind: str, supplier: str) -> dict[str, Any]:
    """A booking exactly as the code before supplier plugins stored it."""
    return {
        "trip_id": trip_id,
        "kind": kind,
        "title": "EC 131 Batory",
        "supplier": supplier,
        "supplier_url": "https://www.intercity.pl/pl/",
        "goal": "Book it.",
        "amount_minor": 90_000,
        "status": "pending",
        "passenger_user_ids": [],
        "current_run_id": None,
        "confirmation_ref": None,
        "replaces_booking_id": None,
        "proposal_item_index": None,
        "created_at": DEPARTS,
        "updated_at": DEPARTS,
        "train_query": {
            "from_code": 5100065,
            "to_code": 5400014,
            "departs_at": DEPARTS,
            "train_number": 131,
            "travel_class": 2,
            "refundable": False,
        }
        if kind == "train"
        else None,
    }


async def _raw(model: Any, oid: Any) -> dict[str, Any]:
    found = await model.get_pymongo_collection().find_one({"_id": oid})
    assert found is not None
    return dict(found)


async def test_supplier_plugins_forward_and_backward(database: Database) -> None:
    trip_id = PydanticObjectId()
    # Stored by the OLD code: the current validator (which requires the new fields) did not
    # exist yet, hence the bypass.
    bookings = Booking.get_pymongo_collection()
    train = (
        await bookings.insert_one(
            _old_booking(trip_id, "train", "PKP Intercity"), bypass_document_validation=True
        )
    ).inserted_id
    stay = (
        await bookings.insert_one(
            _old_booking(trip_id, "stay", "Booking.com"), bypass_document_validation=True
        )
    ).inserted_id
    old_trip = (
        await Trip.get_pymongo_collection().insert_one(
            {
                "title": "Prague",
                "origin": "Warszawa",
                "brief": "",
                "date_from": datetime(2026, 11, 20, tzinfo=UTC),
                "date_to": datetime(2026, 11, 22, tzinfo=UTC),
                "group_size": 2,
                "budget_per_person_minor": None,
                "currency": "PLN",
                "status": "paying",
                "organizer_id": PydanticObjectId(),
                "invite_code": "migration-trip",
                "chosen_proposal_id": None,
                "total_minor": 0,
                # Added by the LATER trip_preferences migration; present here because the
                # validator in place (when another test applied it) is today's.
                "earliest_departure_hour": None,
                "max_transfers": None,
                "created_at": DEPARTS,
                "updated_at": DEPARTS,
            },
            bypass_document_validation=True,
        )
    ).inserted_id
    proposal = (
        await Proposal.get_pymongo_collection().insert_one(
            {
                "trip_id": trip_id,
                "title": "Budget",
                "summary": "",
                "total_minor": 100,
                "per_person_minor": 50,
                "over_budget": False,
                "image_url": None,
                "items": [
                    {
                        "kind": "train",
                        "title": "EC",
                        "supplier": "PKP Intercity",
                        "supplier_url": "https://x",
                        "price_minor": 60,
                    },
                    {
                        "kind": "stay",
                        "title": "Hostel",
                        "supplier": "Booking.com",
                        "supplier_url": "https://y",
                        "price_minor": 40,
                    },
                ],
                "created_at": DEPARTS,
                "updated_at": DEPARTS,
            },
            bypass_document_validation=True,
        )
    ).inserted_id

    # Expand: the new model reads an old document before any backfill.
    before = await Booking.get(train)
    assert before is not None
    assert (before.kind, before.mode) == (BookingKind.TRANSPORT, TransportMode.RAIL)

    await SUPPLIER_PLUGINS.Forward.transport_with_modes.run(session=None)

    # Every added field is present now, so the validator accepts updates of old documents.
    trip = await Trip.get(old_trip)
    assert trip is not None and (trip.destination, trip.transport_mode) == ("", None)
    await trip.set({"status": "booking"})
    assert set(SUPPLIER_PLUGINS.BOOKING_DEFAULTS) <= set(await _raw(Booking, stay))
    upgraded = await _raw(Booking, train)
    assert (upgraded["kind"], upgraded["mode"], upgraded["channel"]) == (
        "transport",
        "rail",
        "agent",
    )
    assert upgraded["supplier_id"] == "pkp_intercity"
    (leg,) = upgraded["supplier_data"]["legs"]
    assert (leg["from_code"], leg["train_number"]) == (5100065, 131)
    assert datetime.fromisoformat(leg["departs_at"]) == DEPARTS
    assert "train_query" in upgraded  # contract comes in a later deploy
    assert (await _raw(Booking, stay))["kind"] == "stay"
    items = (await _raw(Proposal, proposal))["items"]
    assert [(item["kind"], item.get("mode")) for item in items] == [
        ("transport", "rail"),
        ("stay", None),
    ]
    model = await Booking.get(train)
    assert model is not None and model.channel is SupplierChannel.AGENT
    await model.set({"status": "running"})  # passes the validator
    upgraded = await _raw(Booking, train)

    # Idempotent: a second run changes nothing.
    await SUPPLIER_PLUGINS.Forward.transport_with_modes.run(session=None)
    assert await _raw(Booking, train) == upgraded

    await SUPPLIER_PLUGINS.Backward.trains_again.run(session=None)

    restored = await _raw(Booking, train)
    assert restored["kind"] == "train"
    assert restored["train_query"]["train_number"] == 131
    assert [item["kind"] for item in (await _raw(Proposal, proposal))["items"]] == [
        "train",
        "stay",
    ]
    # ... and the new code still reads what Backward wrote.
    again = await Booking.get(train)
    assert again is not None and again.kind is BookingKind.TRANSPORT


async def test_trip_preferences_forward_and_backward(database: Database) -> None:
    trips = Trip.get_pymongo_collection()
    old = {
        "title": "Prague",
        "origin": "Warszawa",
        "brief": "",
        "date_from": datetime(2026, 11, 20, tzinfo=UTC),
        "date_to": datetime(2026, 11, 22, tzinfo=UTC),
        "group_size": 2,
        "budget_per_person_minor": None,
        "currency": "PLN",
        "destination": "Praha",
        "transport_mode": None,
        "status": "paying",
        "organizer_id": PydanticObjectId(),
        "invite_code": "preferences-trip",
        "chosen_proposal_id": None,
        "total_minor": 0,
        "created_at": DEPARTS,
        "updated_at": DEPARTS,
    }
    trip_id = (await trips.insert_one(old, bypass_document_validation=True)).inserted_id
    before = await Trip.get(trip_id)  # expand: read before the backfill
    assert before is not None and before.earliest_departure_hour is None

    await TRIP_PREFERENCES.Forward.trip_preferences.run(session=None)
    raw = await _raw(Trip, trip_id)
    assert (raw["earliest_departure_hour"], raw["max_transfers"]) == (None, None)
    after = await Trip.get(trip_id)
    assert after is not None
    await after.set({"status": "booking"})  # passes the validator
    await TRIP_PREFERENCES.Forward.trip_preferences.run(session=None)  # idempotent

    await TRIP_PREFERENCES.Backward.no_trip_preferences.run(session=None)
    assert "max_transfers" not in await _raw(Trip, trip_id)


def test_pure_mappings_leave_current_documents_alone() -> None:
    assert SUPPLIER_PLUGINS.booking_forward({"kind": "transport"}) is None
    assert SUPPLIER_PLUGINS.booking_backward({"kind": "stay"}) is None
    assert SUPPLIER_PLUGINS.items_forward([{"kind": "stay"}]) is None
    assert SUPPLIER_PLUGINS.items_backward([{"kind": "activity"}]) is None
    # A non-PKP train keeps no supplier id: it is bought as before, at its stored price.
    changes = SUPPLIER_PLUGINS.booking_forward({"kind": "train", "supplier": "Demo rail"})
    assert changes == {"kind": "transport", "mode": "rail"}
