"""Lifecycle building blocks: the per-purchase split of a package item from the supplier's
capabilities, the re-quote tolerance, the shared re-split and the PKP adapter's re-quote."""

import secrets
from datetime import date, datetime
from typing import Any

import pytest
from beanie import PydanticObjectId

from app.core.domain.bookings import (
    exceeds_tolerance,
    refund_minor,
    resume_status,
    split_party,
)
from app.core.domain.trips import (
    BookingKind,
    BookingStatus,
    ContributionStatus,
    EventKind,
    MemberRole,
    SupplierChannel,
    TransportMode,
    TripStatus,
)
from app.db.client import Database
from app.db.identifiers import identifier_of
from app.models.trips import Contribution, ProposalItem, Trip, TripEvent, TripMember
from app.payments.fake import FakePayments
from app.services.booking_plans import bookings_for_item
from app.services.resplit import resplit_shares
from app.suppliers.intercity import MAX_PASSENGERS_PER_PURCHASE
from app.suppliers.pkp import CAPABILITIES as PKP_CAPABILITIES
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import OfferRef, SupplierUnavailableError
from app.suppliers.sim import SIM_CAPABILITIES
from tests.test_intercity_client import RecordedTransport


def test_the_pkp_adapter_declares_the_carriers_cap() -> None:
    assert PKP_CAPABILITIES.max_party_per_purchase == MAX_PASSENGERS_PER_PURCHASE == 5
    assert PKP_CAPABILITIES.channel is SupplierChannel.AGENT


@pytest.mark.parametrize(
    ("travellers", "cap", "expected"),
    [(5, 5, [5]), (6, 5, [3, 3]), (11, 5, [4, 4, 3]), (1, 5, [1]), (12, None, [12])],
)
def test_split_party(travellers: int, cap: int | None, expected: list[int]) -> None:
    assert split_party(travellers, cap) == expected


def test_split_party_rejects_an_empty_party() -> None:
    with pytest.raises(ValueError):
        split_party(0, 5)


@pytest.mark.parametrize(
    ("previous", "current", "tolerance", "expected"),
    [
        (100_000, 100_000, 0.0, False),
        (100_000, 100_001, 0.0, True),
        (100_000, 99_999, 0.0, True),
        (100_000, 105_000, 5.0, False),
        (100_000, 105_001, 5.0, True),
        (100_000, 94_999, 5.0, True),
    ],
)
def test_exceeds_tolerance(previous: int, current: int, tolerance: float, expected: bool) -> None:
    assert exceeds_tolerance(previous, current, tolerance) is expected


def test_refund_is_what_was_paid_beyond_the_share() -> None:
    assert refund_minor(85_000, 90_000) == 5_000
    assert refund_minor(92_335, 90_000) == 0


@pytest.mark.parametrize(
    ("replacements", "expected"),
    [
        ([], TripStatus.BOOKING),
        ([BookingStatus.CONFIRMED, BookingStatus.CANCELLED], TripStatus.BOOKING),
        ([BookingStatus.CONFIRMED, BookingStatus.PENDING], TripStatus.REBOOKING),
        ([BookingStatus.AWAITING_APPROVAL], TripStatus.REBOOKING),
    ],
)
def test_top_ups_resume_rebooking_while_a_replacement_is_unbought(
    replacements: list[BookingStatus], expected: TripStatus
) -> None:
    assert resume_status(replacements) is expected


async def test_fake_payments_refund_exactly_what_was_asked() -> None:
    receipt = await FakePayments().refund("trip", "user", 6_000, "PLN")
    assert receipt.refunded_minor == 6_000
    assert receipt.provider_ref.startswith("fake_refund_")


async def _trip(member_count: int, paid: list[int], shares: list[int]) -> Trip:
    trip = await Trip(
        title="Prague",
        origin="Warszawa",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
        group_size=member_count,
        organizer_id=PydanticObjectId(),
        invite_code=secrets.token_hex(6),
        total_minor=sum(shares),
    ).insert()
    for index in range(member_count):
        user_id = PydanticObjectId()
        await TripMember(
            trip_id=identifier_of(trip),
            user_id=user_id,
            display_name=f"Person{index} Nowak",
            role=MemberRole.ORGANIZER if index == 0 else MemberRole.MEMBER,
        ).insert()
        await Contribution(
            trip_id=identifier_of(trip),
            user_id=user_id,
            amount_minor=shares[index],
            paid_minor=paid[index],
            status=ContributionStatus.PAID,
        ).insert()
    return trip


async def test_resplit_shares_writes_exact_shares_statuses_and_one_event(
    database: Database,
) -> None:
    trip = await _trip(3, paid=[60_000, 60_000, 0], shares=[60_000, 60_000, 60_000])
    plan = await database.in_transaction(
        lambda session: resplit_shares(trip, 150_001, session),
    )
    assert [share.change.share_minor for share in plan.shares] == [50_001, 50_000, 50_000]
    assert [share.change.status for share in plan.shares] == [
        ContributionStatus.REFUND_DUE,
        ContributionStatus.REFUND_DUE,
        ContributionStatus.PENDING,
    ]
    assert plan.owes and plan.refunds
    assert plan.previous_total_minor == 180_000
    stored = await Contribution.find(Contribution.trip_id == identifier_of(trip)).to_list(10)
    assert sum(c.amount_minor for c in stored) == 150_001
    fresh = await Trip.get(identifier_of(trip))
    assert fresh is not None and fresh.total_minor == 150_001
    events = await TripEvent.find(TripEvent.trip_id == identifier_of(trip)).to_list(10)
    assert [event.kind for event in events] == [EventKind.RESPLIT]
    assert [m["refund_minor"] for m in events[0].payload["members"]] == [9_999, 10_000, 0]


async def test_resplit_shares_ignores_former_members_and_can_stay_silent(
    database: Database,
) -> None:
    trip = await _trip(2, paid=[50_000, 50_000], shares=[50_000, 50_000])
    former = await Contribution(
        trip_id=identifier_of(trip),
        user_id=PydanticObjectId(),
        amount_minor=0,
        paid_minor=50_000,
        status=ContributionStatus.REFUND_DUE,
    ).insert()
    plan = await database.in_transaction(
        lambda session: resplit_shares(trip, 120_000, session, announce=False)
    )
    assert [share.change.share_minor for share in plan.shares] == [60_000, 60_000]
    untouched = await Contribution.get(identifier_of(former))
    assert untouched is not None and untouched.amount_minor == 0
    assert await TripEvent.find(TripEvent.trip_id == identifier_of(trip)).count() == 0


def _train(price_minor: int = 100_001) -> ProposalItem:
    return ProposalItem(
        kind=BookingKind.TRANSPORT,
        mode=TransportMode.RAIL,
        title="EC 131 Warszawa -> Praha",
        supplier="PKP Intercity",
        supplier_url="http://demo/rail",
        price_minor=price_minor,
        supplier_id="pkp_intercity",
        offer_ref="pkp_intercity:131",
        supplier_data={"legs": [], "travel_class": 2},
    )


async def test_a_capped_train_becomes_even_purchases_that_sum_exactly(
    database: Database,
) -> None:
    trip = await _trip(1, paid=[0], shares=[0])
    party = [PydanticObjectId() for _ in range(6)]
    parts = bookings_for_item(trip, _train(), 0, party, PKP_CAPABILITIES)
    assert [len(part.passenger_user_ids) for part in parts] == [3, 3]
    assert parts[0].passenger_user_ids + parts[1].passenger_user_ids == party
    assert sum(part.amount_minor for part in parts) == 100_001
    assert [part.title for part in parts] == [
        "EC 131 Warszawa -> Praha (passengers 1-3)",
        "EC 131 Warszawa -> Praha (passengers 4-6)",
    ]
    assert all("for 3 passengers" in part.goal for part in parts)
    assert all("passenger_1..passenger_3" in part.goal for part in parts)
    assert all(part.supplier_url == "http://demo/rail" for part in parts)
    assert all(part.proposal_item_index == 0 for part in parts)
    assert all(part.supplier_id == "pkp_intercity" for part in parts)
    assert all(part.mode is TransportMode.RAIL for part in parts)


async def test_the_split_follows_capabilities_not_the_supplier_name(database: Database) -> None:
    """The same item at a cap of 9 (a coach site) is one purchase for eight."""
    trip = await _trip(1, paid=[0], shares=[0])
    eight = [PydanticObjectId() for _ in range(8)]
    _, bus = SIM_CAPABILITIES["sim_bus"]
    assert len(bookings_for_item(trip, _train(), 0, eight, bus)) == 1
    assert [
        len(p.passenger_user_ids)
        for p in bookings_for_item(trip, _train(), 0, eight, PKP_CAPABILITIES)
    ] == [4, 4]
    _, flight = SIM_CAPABILITIES["sim_flight"]
    (direct,) = bookings_for_item(trip, _train(), 0, eight, flight)
    assert direct.channel is SupplierChannel.API


async def test_uncapped_items_and_small_parties_stay_one_booking(database: Database) -> None:
    trip = await _trip(1, paid=[0], shares=[0])
    five = [PydanticObjectId() for _ in range(5)]
    (train,) = bookings_for_item(trip, _train(), 0, five, PKP_CAPABILITIES)
    assert train.passenger_user_ids == five
    assert train.title == "EC 131 Warszawa -> Praha"
    stay = ProposalItem(
        kind=BookingKind.STAY,
        title="Old Town apartment",
        supplier="Booking.com",
        supplier_url="https://www.booking.com/",
        price_minor=60_000,
    )
    seven = [PydanticObjectId() for _ in range(7)]
    (booking,) = bookings_for_item(trip, stay, 1, seven, None)
    assert booking.passenger_user_ids == seven
    assert booking.supplier_url == "https://www.booking.com/"
    assert booking.channel is SupplierChannel.AGENT  # outside the registry: bought as before


def _pkp_offer(train_number: int = 131) -> OfferRef:
    return OfferRef(
        supplier_id="pkp_intercity",
        offer_ref="pkp_intercity:131",
        supplier_data={
            "travel_class": 2,
            "refundable": False,
            "legs": [
                {
                    "from_code": 5100065,
                    "to_code": 5400014,
                    "departs_at": datetime(2026, 11, 20, 7, 52).isoformat(),
                    "train_number": train_number,
                }
            ],
        },
    )


async def test_the_pkp_adapter_requotes_the_party(database: Database) -> None:
    transport = RecordedTransport()
    quote = await PkpIntercitySupplier(transport).quote(_pkp_offer(), 3)
    assert quote is not None and quote.price_minor == 15_565 * 3
    assert transport.fare_requests == [3]


async def test_the_pkp_adapter_reports_a_vanished_train(database: Database) -> None:
    assert await PkpIntercitySupplier(RecordedTransport()).quote(_pkp_offer(999), 3) is None


async def test_the_pkp_adapter_cannot_quote_without_legs(database: Database) -> None:
    transport = RecordedTransport()
    empty = OfferRef(supplier_id="pkp_intercity", offer_ref="x", supplier_data={})
    assert await PkpIntercitySupplier(transport).quote(empty, 3) is None
    assert transport.fare_requests == []


class BrokenTransport(RecordedTransport):
    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        raise ConnectionResetError("Akamai said no")


async def test_an_unreachable_pkp_is_unavailable_not_sold_out(database: Database) -> None:
    with pytest.raises(SupplierUnavailableError):
        await PkpIntercitySupplier(BrokenTransport()).quote(_pkp_offer(), 3)
