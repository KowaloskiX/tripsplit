"""Lifecycle building blocks: purchase caps, the per-purchase split of a package item, the
re-quote tolerance, the shared re-split and the PKP re-quote adapter."""

import secrets
from datetime import date, datetime
from typing import Any

import pytest
from beanie import PydanticObjectId

from app.core.domain.bookings import (
    PKP_INTERCITY,
    exceeds_tolerance,
    purchase_cap,
    refund_minor,
    split_party,
)
from app.core.domain.trips import BookingKind, ContributionStatus, EventKind, MemberRole
from app.db.client import Database
from app.db.identifiers import identifier_of
from app.models.bookings import Booking, TrainQuery
from app.models.trips import Contribution, ProposalItem, Trip, TripEvent, TripMember
from app.services.booking_plans import bookings_for_item
from app.services.resplit import resplit_shares
from app.suppliers.intercity import MAX_PASSENGERS_PER_PURCHASE
from app.suppliers.quotes import IntercityQuotes, StaticQuotes
from tests.test_intercity_client import RecordedTransport


@pytest.mark.parametrize(
    ("supplier", "cap"),
    [("PKP Intercity", 5), ("pkp intercity ", 5), ("Booking.com", None), ("GetYourGuide", None)],
)
def test_purchase_cap_per_supplier(supplier: str, cap: int | None) -> None:
    assert purchase_cap(supplier) == cap


def test_the_pkp_client_reads_the_same_cap() -> None:
    assert purchase_cap(PKP_INTERCITY) == MAX_PASSENGERS_PER_PURCHASE


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
        kind=BookingKind.TRAIN,
        title="EC 131 Warszawa -> Praha",
        supplier=PKP_INTERCITY,
        supplier_url="https://www.intercity.pl/pl/",
        price_minor=price_minor,
    )


async def test_a_capped_train_becomes_even_purchases_that_sum_exactly(
    database: Database,
) -> None:
    trip = await _trip(1, paid=[0], shares=[0])
    party = [PydanticObjectId() for _ in range(6)]
    parts = bookings_for_item(trip, _train(), 0, party, train_supplier_url="http://demo/rail")
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


async def test_uncapped_items_and_small_parties_stay_one_booking(database: Database) -> None:
    trip = await _trip(1, paid=[0], shares=[0])
    five = [PydanticObjectId() for _ in range(5)]
    (train,) = bookings_for_item(trip, _train(), 0, five)
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
    (booking,) = bookings_for_item(trip, stay, 1, seven, train_supplier_url="http://demo/rail")
    assert booking.passenger_user_ids == seven
    assert booking.supplier_url == "https://www.booking.com/"


def _pkp_booking(passengers: int, query: TrainQuery | None) -> Booking:
    return Booking(
        trip_id=PydanticObjectId(),
        kind=BookingKind.TRAIN,
        title="EC 131",
        supplier=PKP_INTERCITY,
        supplier_url="https://www.intercity.pl/pl/",
        goal="Book it.",
        amount_minor=90_000,
        passenger_user_ids=[PydanticObjectId() for _ in range(passengers)],
        train_query=query,
    )


QUERY = TrainQuery(
    from_code=5100065, to_code=5400014, departs_at=datetime(2026, 11, 20, 7, 52), train_number=131
)


async def test_static_quotes_trust_the_stored_amount(database: Database) -> None:
    assert await StaticQuotes().quote(_pkp_booking(3, QUERY)) == 90_000


async def test_intercity_quotes_ask_pkp_for_the_party(database: Database) -> None:
    transport = RecordedTransport()
    quote = await IntercityQuotes(transport).quote(_pkp_booking(3, QUERY))
    assert quote == 15_565 * 3
    assert transport.fare_requests == [3]


async def test_intercity_quotes_report_a_vanished_train(database: Database) -> None:
    gone = QUERY.model_copy(update={"train_number": 999})
    assert await IntercityQuotes(RecordedTransport()).quote(_pkp_booking(3, gone)) is None


async def test_intercity_quotes_fall_back_without_a_query(database: Database) -> None:
    transport = RecordedTransport()
    assert await IntercityQuotes(transport).quote(_pkp_booking(3, None)) == 90_000
    assert transport.fare_requests == []


class BrokenTransport(RecordedTransport):
    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        raise ConnectionResetError("Akamai said no")


async def test_intercity_quotes_keep_the_stored_amount_when_pkp_is_unreachable(
    database: Database,
) -> None:
    assert await IntercityQuotes(BrokenTransport()).quote(_pkp_booking(3, QUERY)) == 90_000
