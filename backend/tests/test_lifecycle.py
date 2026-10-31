"""The trip lifecycle beyond the happy path, over HTTP: re-quotes before buying, purchases
capped per supplier, members leaving, and finishing a handed-off booking by hand.

No browser and no LLM: the launcher records what it was asked to run and refuses to start (the
booking then fails, as with a broken browser), and quotes are scripted per booking.
"""

import secrets
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import date
from typing import Any

import pytest
from beanie import PydanticObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.launcher import LaunchSpec
from app.core.config import Settings, get_settings
from app.core.deps import SettingsDep
from app.core.domain.errors import BookingError, TripError
from app.core.domain.result import Err, Result
from app.core.domain.suppliers import SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
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
from app.core.http_security import CSRF_HEADER_NAME
from app.db.client import Database
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_object_id
from app.models.bookings import AgentRun, Booking
from app.models.trips import Contribution, Trip, TripEvent, TripMember, Vote
from app.routes.dependencies import get_booking_service, get_supplier_registry
from app.services.bookings import BookingService
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
)
from app.suppliers.registry import SupplierRegistry

PASSWORD = "correct-horse-battery-staple"
TRAIN_MINOR = 120_000
STAY_MINOR = 60_000

TRIP = {
    "title": "Weekend in Prague",
    "origin": "Warszawa",
    "brief": "weekend in Prague, cheap, good food",
    "date_from": "2026-11-20",
    "date_to": "2026-11-22",
    "group_size": 6,
    "display_name": "Anna Organizer",
}


class RecordingLauncher:
    """Records every launch, then refuses it — the booking ends FAILED, no monitor runs."""

    def __init__(self) -> None:
        self.started: list[LaunchSpec] = []

    async def start(self, spec: LaunchSpec) -> Any:
        self.started.append(spec)
        raise RuntimeError("no browser in tests")


class ScriptedQuotes:
    """A rail supplier plugin whose current price is scripted per offer (`offer_ref`); an
    unscripted offer answers the price the seeded booking was created with."""

    id = "scripted_rail"
    display_name = "Scripted rail"
    capabilities = SupplierCapabilities(
        kind=BookingKind.TRANSPORT,
        mode=TransportMode.RAIL,
        channel=SupplierChannel.AGENT,
        max_party_per_purchase=5,
        required_traveller_fields=frozenset(),
    )

    def __init__(self) -> None:
        self.prices: dict[str, int | None] = {}

    async def search(self, request: SearchRequest) -> list[Offer]:
        return []

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        price = self.prices.get(offer.offer_ref, int(offer.supplier_data["listed_minor"]))
        return Quote(price, "PLN", utc_now()) if price is not None else None

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        return None

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        return Err("bought by the agent")

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return None


@pytest.fixture
def launcher() -> RecordingLauncher:
    return RecordingLauncher()


@pytest.fixture
def quotes() -> ScriptedQuotes:
    return ScriptedQuotes()


@pytest.fixture
def tolerance() -> list[float]:
    return [0.0]


@pytest.fixture
def lifecycle_app(
    app: FastAPI,
    database: Database,
    tmp_path: Any,
    launcher: RecordingLauncher,
    quotes: ScriptedQuotes,
    tolerance: list[float],
) -> Iterator[FastAPI]:
    def service(current: SettingsDep) -> BookingService:
        return BookingService(
            database,
            launcher,
            tmp_path / "runs",
            suppliers=SupplierRegistry([quotes, *get_supplier_registry(current)]),
            price_tolerance_percent=tolerance[0],
        )

    app.dependency_overrides[get_booking_service] = service
    yield app


class Person:
    def __init__(self, client: AsyncClient, user_id: str) -> None:
        self.client = client
        self.id = user_id

    def _headers(self) -> dict[str, str]:
        token = self.client.cookies.get("csrf_token")
        assert token is not None
        return {CSRF_HEADER_NAME: token}

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return await self.client.post(path, json=body or {}, headers=self._headers())

    async def get(self, path: str) -> Any:
        return await self.client.get(path)


@pytest.fixture
async def people(lifecycle_app: FastAPI) -> AsyncIterator[list[Person]]:
    """Two signed-in browsers: [organizer, friend]."""
    created: list[Person] = []
    for email in ("anna@example.com", "friend@example.com"):
        client = AsyncClient(transport=ASGITransport(app=lifecycle_app), base_url="http://test")
        await client.get("/api/auth/session")
        token = client.cookies.get("csrf_token")
        assert token is not None
        response = await client.post(
            "/api/auth/register",
            json={"email": email, "password": PASSWORD, "organization_name": "Friends"},
            headers={CSRF_HEADER_NAME: token},
        )
        assert response.status_code == 201, response.text
        created.append(Person(client, response.json()["id"]))
    yield created
    for person in created:
        await person.client.aclose()


async def _seed_trip(
    organizer: Person,
    others: list[Person],
    status: TripStatus,
    booking_status: BookingStatus = BookingStatus.PENDING,
    paid: bool = True,
) -> tuple[Trip, Booking, Booking]:
    """A trip with a PKP train and a stay, every member owing (or having paid) an even share."""
    owners = [to_object_id(organizer.id), *(to_object_id(person.id) for person in others)]
    user_ids = [oid for oid in owners if oid is not None]
    total = TRAIN_MINOR + STAY_MINOR
    trip = await Trip(
        title="Prague weekend",
        origin="Warszawa",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
        group_size=len(user_ids),
        organizer_id=user_ids[0],
        invite_code=secrets.token_hex(6),
        status=status,
        total_minor=total,
    ).insert()
    share = total // len(user_ids)
    for index, user_id in enumerate(user_ids):
        await TripMember(
            trip_id=identifier_of(trip),
            user_id=user_id,
            display_name=f"Person{index} Nowak",
            role=MemberRole.ORGANIZER if index == 0 else MemberRole.MEMBER,
        ).insert()
        await Contribution(
            trip_id=identifier_of(trip),
            user_id=user_id,
            amount_minor=share,
            paid_minor=share if paid else 0,
            status=ContributionStatus.PAID if paid else ContributionStatus.PENDING,
        ).insert()

    def booking(kind: BookingKind, title: str, supplier: str, amount: int) -> Booking:
        transport = kind is BookingKind.TRANSPORT
        return Booking(
            trip_id=identifier_of(trip),
            kind=kind,
            mode=TransportMode.RAIL if transport else None,
            supplier_id=ScriptedQuotes.id if transport else "",
            offer_ref=f"offer:{title}" if transport else "",
            supplier_data={"listed_minor": amount} if transport else {},
            title=title,
            supplier=supplier,
            supplier_url="http://localhost:8400/api/demo-supplier/rail",
            goal=f"Book {title}.",
            amount_minor=amount,
            status=booking_status,
            passenger_user_ids=user_ids,
        )

    train = await booking(BookingKind.TRANSPORT, "EC 131", "PKP Intercity", TRAIN_MINOR).insert()
    stay = await booking(BookingKind.STAY, "Old Town apartment", "Booking.com", STAY_MINOR).insert()
    return trip, train, stay


async def _contributions(trip: Trip) -> list[Contribution]:
    return await Contribution.find(Contribution.trip_id == identifier_of(trip)).to_list(20)


async def _events(trip: Trip, kind: EventKind) -> list[TripEvent]:
    return await TripEvent.find(
        TripEvent.trip_id == identifier_of(trip), TripEvent.kind == kind
    ).to_list(20)


async def _trip_status(trip: Trip) -> TripStatus:
    fresh = await Trip.get(identifier_of(trip))
    assert fresh is not None
    return fresh.status


# ---- re-quote before buying ---------------------------------------------------------------


async def test_a_price_rise_resplits_exactly_and_sends_the_trip_back_to_paying(
    people: list[Person], quotes: ScriptedQuotes, launcher: RecordingLauncher
) -> None:
    organizer, friend = people
    trip, train, _ = await _seed_trip(organizer, [friend], TripStatus.BOOKING)
    quotes.prices[train.offer_ref] = 124_670  # +46.70 PLN for the party

    response = await organizer.post(f"/api/trips/{trip.id}/bookings/{train.id}/start")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == BookingError.PRICE_CHANGED
    assert launcher.started == []

    stored = await Booking.get(identifier_of(train))
    assert stored is not None
    assert stored.amount_minor == 124_670
    assert stored.status is BookingStatus.PENDING
    assert await _trip_status(trip) is TripStatus.PAYING
    contributions = await _contributions(trip)
    assert [c.amount_minor for c in contributions] == [92_335, 92_335]
    assert {c.status for c in contributions} == {ContributionStatus.PENDING}
    fresh = await Trip.get(identifier_of(trip))
    assert fresh is not None and fresh.total_minor == 124_670 + STAY_MINOR

    (event,) = await _events(trip, EventKind.PRICE_CHANGED)
    assert event.message == (
        "PKP Intercity raised the price of EC 131 from 1 200.00 to 1 246.70 PLN — "
        "23.35 PLN more each. Top up and I will buy it."
    )
    assert event.payload["previous_amount_minor"] == TRAIN_MINOR
    assert event.payload["amount_minor"] == 124_670
    assert [m["delta_minor"] for m in event.payload["members"]] == [2_335, 2_335]

    # Both top up; the trip is fully paid again and the purchase goes ahead at the new price.
    for person in (friend, organizer):
        paid = await person.post(f"/api/trips/{trip.id}/contributions/pay")
        assert paid.status_code == 200, paid.text
    assert await _trip_status(trip) is TripStatus.BOOKING
    again = await organizer.post(f"/api/trips/{trip.id}/bookings/{train.id}/start")
    assert again.status_code == 202, again.text
    assert len(launcher.started) == 1


async def test_a_price_drop_marks_refunds_and_the_booking_proceeds(
    people: list[Person], quotes: ScriptedQuotes, launcher: RecordingLauncher
) -> None:
    organizer, friend = people
    trip, train, _ = await _seed_trip(organizer, [friend], TripStatus.BOOKING)
    quotes.prices[train.offer_ref] = 110_000

    response = await organizer.post(f"/api/trips/{trip.id}/bookings/{train.id}/start")
    assert response.status_code == 202, response.text
    assert len(launcher.started) == 1
    assert await _trip_status(trip) is TripStatus.BOOKING
    contributions = await _contributions(trip)
    assert [c.amount_minor for c in contributions] == [85_000, 85_000]
    assert {c.status for c in contributions} == {ContributionStatus.REFUND_DUE}

    room = (await friend.get(f"/api/trips/{trip.id}")).json()
    assert room["my_contribution"]["refund_minor"] == 5_000
    assert room["my_contribution"]["status"] == ContributionStatus.REFUND_DUE
    (event,) = await _events(trip, EventKind.PRICE_CHANGED)
    assert "lowered the price" in event.message
    assert "50.00 PLN less each" in event.message


async def test_a_sold_out_booking_fails_before_launching(
    people: list[Person], quotes: ScriptedQuotes, launcher: RecordingLauncher
) -> None:
    organizer, _ = people
    trip, train, _ = await _seed_trip(organizer, [], TripStatus.BOOKING)
    quotes.prices[train.offer_ref] = None

    response = await organizer.post(f"/api/trips/{trip.id}/bookings/{train.id}/start")
    assert response.status_code == 409
    assert response.json()["code"] == BookingError.SOLD_OUT
    assert launcher.started == []
    stored = await Booking.get(identifier_of(train))
    assert stored is not None and stored.status is BookingStatus.FAILED
    assert await _events(trip, EventKind.BOOKING_FAILED)


async def test_a_change_within_the_tolerance_is_ignored(
    people: list[Person],
    quotes: ScriptedQuotes,
    launcher: RecordingLauncher,
    tolerance: list[float],
) -> None:
    tolerance[0] = 5.0
    organizer, _ = people
    trip, train, _ = await _seed_trip(organizer, [], TripStatus.BOOKING)
    quotes.prices[train.offer_ref] = 123_000  # +2.5 %

    response = await organizer.post(f"/api/trips/{trip.id}/bookings/{train.id}/start")
    assert response.status_code == 202, response.text
    stored = await Booking.get(identifier_of(train))
    assert stored is not None and stored.amount_minor == TRAIN_MINOR
    assert not await _events(trip, EventKind.PRICE_CHANGED)


async def _split_quoted_train(organizer: Person, friend: Person) -> tuple[Trip, Booking, Booking]:
    """The seeded train as TWO purchases of the same package item (one passenger each)."""
    trip, train, _ = await _seed_trip(organizer, [friend], TripStatus.BOOKING)
    half = TRAIN_MINOR // 2
    first_passenger, second_passenger = train.passenger_user_ids
    await train.set(
        {
            "proposal_item_index": 0,
            "amount_minor": half,
            "passenger_user_ids": [first_passenger],
            "supplier_data": {"listed_minor": half},
        }
    )
    second = await Booking(
        **{
            **train.model_dump(exclude={"id", "revision_id"}),
            "offer_ref": "offer:EC 131 part 2",
            "passenger_user_ids": [second_passenger],
        }
    ).insert()
    return trip, train, second


async def test_a_split_train_with_one_part_gone_starts_none_of_its_parts(
    people: list[Person], quotes: ScriptedQuotes, launcher: RecordingLauncher
) -> None:
    organizer, friend = people
    trip, first, second = await _split_quoted_train(organizer, friend)
    quotes.prices[second.offer_ref] = None  # the second half's seats are gone

    response = await organizer.post(f"/api/trips/{trip.id}/bookings/{first.id}/start")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == BookingError.SOLD_OUT
    assert launcher.started == []
    for part in (first, second):
        stored = await Booking.get(identifier_of(part))
        assert stored is not None and stored.status is BookingStatus.FAILED
    (event,) = await _events(trip, EventKind.BOOKING_FAILED)
    assert event.payload["sold_out"] is True
    assert len(event.payload["booking_ids"]) == 2  # both purchases
    assert "bought none" in event.message


async def test_a_split_train_requotes_every_part_before_the_first_starts(
    people: list[Person], quotes: ScriptedQuotes, launcher: RecordingLauncher
) -> None:
    organizer, friend = people
    trip, first, second = await _split_quoted_train(organizer, friend)

    response = await organizer.post(f"/api/trips/{trip.id}/bookings/{first.id}/start")
    assert response.status_code == 202, response.text
    assert len(launcher.started) == 1
    waiting = await Booking.get(identifier_of(second))
    assert waiting is not None
    assert waiting.status is BookingStatus.PENDING
    assert waiting.quoted_at is not None  # checked with the first, not started


# ---- purchases capped per supplier ---------------------------------------------------------


async def _six_person_trip(
    organizer: Person, friend: Person, seeded: int, demo_settings: bool = False
) -> str:
    response = await organizer.post("/api/trips", TRIP)
    assert response.status_code == 201, response.text
    trip_id: str = response.json()["trip_id"]
    code = (await organizer.get(f"/api/trips/{trip_id}")).json()["invite_code"]
    joined = await friend.post("/api/trips/join", {"invite_code": code, "display_name": "Ola B"})
    assert joined.status_code == 200, joined.text
    if seeded:
        await organizer.post(f"/api/trips/{trip_id}/demo/seed-members", {"count": seeded})
    return trip_id


async def _research_and_close(app: FastAPI, organizer: Person, trip_id: str) -> None:
    assert (await organizer.post(f"/api/trips/{trip_id}/proposals/generate")).status_code == 202
    await app.state.background.drain()
    closed = await organizer.post(f"/api/trips/{trip_id}/voting/close")
    assert closed.status_code == 200, closed.text


async def _bookings(trip_id: str) -> list[Booking]:
    trip_oid = to_object_id(trip_id)
    return await Booking.find(Booking.trip_id == trip_oid).sort("_id").to_list(20)


async def _pay_everyone(organizer: Person, friend: Person, trip_id: str) -> None:
    await friend.post(f"/api/trips/{trip_id}/contributions/pay")
    await organizer.post(f"/api/trips/{trip_id}/demo/pay-all")
    last = await organizer.post(f"/api/trips/{trip_id}/contributions/pay")
    assert last.json()["all_paid"] is True, last.text


async def test_six_travellers_become_two_train_purchases_with_their_own_vaults(
    lifecycle_app: FastAPI,
    settings: Settings,
    people: list[Person],
    launcher: RecordingLauncher,
) -> None:
    lifecycle_app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={
            "demo_supplier_url": "http://localhost:8400",
            "suppliers": "demo_rail,sim_stay_site,sim_activity",
        }
    )
    organizer, friend = people
    trip_id = await _six_person_trip(organizer, friend, seeded=4)
    await _research_and_close(lifecycle_app, organizer, trip_id)

    bookings = await _bookings(trip_id)
    trains = [b for b in bookings if b.mode is TransportMode.RAIL]
    assert [len(t.passenger_user_ids) for t in trains] == [3, 3]
    room = (await organizer.get(f"/api/trips/{trip_id}")).json()
    chosen = next(p for p in room["proposals"] if p["chosen"])
    train_item = next(i for i in chosen["items"] if i.get("mode") == TransportMode.RAIL)
    assert sum(t.amount_minor for t in trains) == train_item["price_minor"]
    assert [t.title.endswith(s) for t, s in zip(trains, ("1-3)", "4-6)"), strict=True)] == [
        True,
        True,
    ]
    assert all(t.supplier_url == "http://localhost:8400/api/demo-supplier/rail" for t in trains)
    assert all(len(b.passenger_user_ids) == 6 for b in bookings if b.mode is not TransportMode.RAIL)

    await _pay_everyone(organizer, friend, trip_id)
    names = {m["user_id"]: m["display_name"] for m in room["members"]}
    for train in trains:
        started = await organizer.post(f"/api/trips/{trip_id}/bookings/{train.id}/start")
        assert started.status_code == 202, started.text
    assert len(launcher.started) == 2
    for spec, train in zip(launcher.started, trains, strict=True):
        vault = spec.vault
        assert vault["passengers"] == "3"
        assert "passenger_4_first_name" not in vault
        expected = [names[str(uid)].split(" ")[0] for uid in train.passenger_user_ids]
        assert [vault[f"passenger_{n}_first_name"] for n in (1, 2, 3)] == expected
        assert vault["email"] == "anna@example.com"
        assert "Passengers on this purchase: 3." in spec.goal


async def test_five_travellers_are_one_train_purchase(
    lifecycle_app: FastAPI, people: list[Person]
) -> None:
    organizer, friend = people
    trip_id = await _six_person_trip(organizer, friend, seeded=3)
    await _research_and_close(lifecycle_app, organizer, trip_id)
    trains = [b for b in await _bookings(trip_id) if b.mode is TransportMode.RAIL]
    assert len(trains) == 1
    assert len(trains[0].passenger_user_ids) == 5
    assert "(passengers" not in trains[0].title


# ---- leaving a trip ---------------------------------------------------------------------


async def test_leaving_while_voting_drops_the_member_and_their_vote(
    lifecycle_app: FastAPI, people: list[Person]
) -> None:
    organizer, friend = people
    trip_id = await _six_person_trip(organizer, friend, seeded=0)
    assert (await organizer.post(f"/api/trips/{trip_id}/proposals/generate")).status_code == 202
    await lifecycle_app.state.background.drain()
    room = (await friend.get(f"/api/trips/{trip_id}")).json()
    await friend.post(f"/api/trips/{trip_id}/votes", {"proposal_id": room["proposals"][0]["id"]})

    left = await friend.post(f"/api/trips/{trip_id}/leave")
    assert left.status_code == 200, left.text
    assert left.json()["status"] == TripStatus.VOTING
    assert (await friend.get(f"/api/trips/{trip_id}")).status_code == 404
    room = (await organizer.get(f"/api/trips/{trip_id}")).json()
    assert len(room["members"]) == 1
    assert await Vote.find(Vote.trip_id == to_object_id(trip_id)).count() == 0
    kinds = [e["kind"] for e in (await organizer.get(f"/api/trips/{trip_id}/feed")).json()]
    assert EventKind.MEMBER_LEFT in kinds
    assert EventKind.RESPLIT not in kinds


async def test_leaving_before_paying_resplits_and_rebuilds_the_bookings(
    lifecycle_app: FastAPI, people: list[Person]
) -> None:
    organizer, friend = people
    trip_id = await _six_person_trip(organizer, friend, seeded=0)
    await _research_and_close(lifecycle_app, organizer, trip_id)
    before = await _bookings(trip_id)

    left = await friend.post(f"/api/trips/{trip_id}/leave")
    assert left.status_code == 200, left.text
    room = (await organizer.get(f"/api/trips/{trip_id}")).json()
    assert [c["user_id"] for c in room["contributions"]] == [organizer.id]
    assert room["contributions"][0]["amount_minor"] == room["trip"]["total_minor"]
    after = await _bookings(trip_id)
    assert sum(b.amount_minor for b in after) == sum(b.amount_minor for b in before)
    assert all(b.passenger_user_ids == [to_object_id(organizer.id)] for b in after)


async def test_leaving_after_paying_refunds_the_leaver_and_the_rest_top_up(
    lifecycle_app: FastAPI, people: list[Person]
) -> None:
    organizer, friend = people
    trip_id = await _six_person_trip(organizer, friend, seeded=4)
    await _research_and_close(lifecycle_app, organizer, trip_id)
    total = (await organizer.get(f"/api/trips/{trip_id}")).json()["trip"]["total_minor"]
    await friend.post(f"/api/trips/{trip_id}/contributions/pay")
    await organizer.post(f"/api/trips/{trip_id}/demo/pay-all")
    paid_by_friend = next(
        c["paid_minor"]
        for c in (await friend.get(f"/api/trips/{trip_id}")).json()["contributions"]
        if c["user_id"] == friend.id
    )

    left = await friend.post(f"/api/trips/{trip_id}/leave")
    assert left.status_code == 200, left.text
    assert left.json()["status"] == TripStatus.PAYING

    room = (await organizer.get(f"/api/trips/{trip_id}")).json()
    by_user = {c["user_id"]: c for c in room["contributions"]}
    leaver = by_user.pop(friend.id)
    assert leaver["amount_minor"] == 0
    assert leaver["status"] == ContributionStatus.REFUND_DUE
    assert leaver["refund_minor"] == paid_by_friend
    assert sum(c["amount_minor"] for c in by_user.values()) == total
    assert len(by_user) == 5
    assert {c["status"] for c in by_user.values()} == {ContributionStatus.PENDING}
    assert room["paid_count"] == 0
    assert room["trip"]["total_minor"] == total

    kinds = [e["kind"] for e in (await organizer.get(f"/api/trips/{trip_id}/feed")).json()]
    assert EventKind.MEMBER_LEFT in kinds and EventKind.RESPLIT in kinds
    # Five travellers fit one PKP purchase again: the two train parts merge into one.
    trains = [b for b in await _bookings(trip_id) if b.mode is TransportMode.RAIL]
    assert len(trains) == 1
    assert len(trains[0].passenger_user_ids) == 5
    assert to_object_id(friend.id) not in trains[0].passenger_user_ids


async def test_leaving_is_refused_once_a_booking_started(people: list[Person]) -> None:
    organizer, friend = people
    # A disruption sent the trip back to PAYING after the train was already bought.
    trip, train, _ = await _seed_trip(organizer, [friend], TripStatus.PAYING)
    await train.set({"status": BookingStatus.CONFIRMED})
    response = await friend.post(f"/api/trips/{trip.id}/leave")
    assert response.status_code == 409
    assert response.json()["code"] == TripError.BOOKING_STARTED
    assert await TripMember.find(TripMember.trip_id == identifier_of(trip)).count() == 2


async def test_leaving_while_booking_before_anything_is_bought_goes_back_to_paying(
    people: list[Person],
) -> None:
    """Everyone had paid (BOOKING) but no agent started: the leaver is refunded later and the
    one who stays owes the leaver's half, so the trip waits for the top-up again."""
    organizer, friend = people
    trip, _, _ = await _seed_trip(organizer, [friend], TripStatus.BOOKING)
    response = await friend.post(f"/api/trips/{trip.id}/leave")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == TripStatus.PAYING
    assert await _trip_status(trip) is TripStatus.PAYING
    by_user = {str(c.user_id): c for c in await _contributions(trip)}
    assert by_user[friend.id].status is ContributionStatus.REFUND_DUE
    assert by_user[organizer.id].amount_minor == TRAIN_MINOR + STAY_MINOR
    assert by_user[organizer.id].status is ContributionStatus.PENDING


async def test_leaving_while_booking_is_refused_once_an_agent_runs(
    people: list[Person],
) -> None:
    organizer, friend = people
    trip, train, _ = await _seed_trip(organizer, [friend], TripStatus.BOOKING)
    await train.set({"status": BookingStatus.RUNNING})
    response = await friend.post(f"/api/trips/{trip.id}/leave")
    assert response.status_code == 409
    assert response.json()["code"] == TripError.BOOKING_STARTED
    assert await _trip_status(trip) is TripStatus.BOOKING


async def test_the_organizer_cannot_leave(people: list[Person]) -> None:
    organizer, friend = people
    trip, _, _ = await _seed_trip(organizer, [friend], TripStatus.PAYING, paid=False)
    response = await organizer.post(f"/api/trips/{trip.id}/leave")
    assert response.status_code == 409
    assert response.json()["code"] == TripError.ORGANIZER_CANNOT_LEAVE


async def test_the_organizer_makes_only_a_seeded_member_leave(
    lifecycle_app: FastAPI, people: list[Person]
) -> None:
    organizer, friend = people
    trip_id = await _six_person_trip(organizer, friend, seeded=2)
    room = (await organizer.get(f"/api/trips/{trip_id}")).json()
    seeded = next(m for m in room["members"] if m["display_name"] == "Ola Nowak")

    refused = await organizer.post(f"/api/trips/{trip_id}/demo/leave", {"user_id": friend.id})
    assert refused.status_code == 404
    by_friend = await friend.post(
        f"/api/trips/{trip_id}/demo/leave", {"user_id": seeded["user_id"]}
    )
    assert by_friend.status_code == 403
    left = await organizer.post(f"/api/trips/{trip_id}/demo/leave", {"user_id": seeded["user_id"]})
    assert left.status_code == 200, left.text
    members = (await organizer.get(f"/api/trips/{trip_id}")).json()["members"]
    assert seeded["user_id"] not in {m["user_id"] for m in members}
    assert len(members) == 3


# ---- manual completion --------------------------------------------------------------------


async def test_a_handoff_completed_by_hand_confirms_and_books_the_trip(
    people: list[Person],
) -> None:
    organizer, _ = people
    trip, train, stay = await _seed_trip(organizer, [], TripStatus.BOOKING)
    await train.set({"status": BookingStatus.HANDOFF})
    await stay.set({"status": BookingStatus.CONFIRMED})

    response = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/complete", {"confirmation_ref": "PKP-XYZ"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == BookingStatus.CONFIRMED
    assert response.json()["confirmation_ref"] == "PKP-XYZ"
    assert await _trip_status(trip) is TripStatus.BOOKED
    (event,) = await _events(trip, EventKind.BOOKING_CONFIRMED)
    assert event.message == "Person0 Nowak finished EC 131 by hand: ref PKP-XYZ."

    twice = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/complete", {"confirmation_ref": "PKP-XYZ"}
    )
    assert twice.status_code == 409
    assert twice.json()["code"] == BookingError.NOT_COMPLETABLE


async def test_only_the_organizer_completes_and_only_a_handoff_or_failure(
    people: list[Person],
) -> None:
    organizer, friend = people
    trip, train, stay = await _seed_trip(organizer, [friend], TripStatus.BOOKING)
    await train.set({"status": BookingStatus.FAILED})

    by_friend = await friend.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/complete", {"confirmation_ref": "X1"}
    )
    assert by_friend.status_code == 403
    assert by_friend.json()["code"] == BookingError.NOT_ORGANIZER
    pending = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{stay.id}/complete", {"confirmation_ref": "X1"}
    )
    assert pending.status_code == 409
    assert pending.json()["code"] == BookingError.NOT_COMPLETABLE
    blank = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{train.id}/complete", {"confirmation_ref": "   "}
    )
    assert blank.status_code == 422
    unknown = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{PydanticObjectId()}/complete",
        {"confirmation_ref": "X1"},
    )
    assert unknown.status_code == 404


# ---- disruptions of a split train, top-ups, refunds and approvals -------------------------


async def _split_train(train: Booking, organizer: Person, friend: Person) -> list[Booking]:
    """The seeded train as two purchases of one package item (like a party above the cap)."""
    first, second = to_object_id(organizer.id), to_object_id(friend.id)
    assert first is not None and second is not None
    await train.set(
        {"passenger_user_ids": [first], "amount_minor": 60_001, "proposal_item_index": 0}
    )
    other = await Booking(
        trip_id=train.trip_id,
        kind=BookingKind.TRANSPORT,
        mode=TransportMode.RAIL,
        title="EC 131 (passengers 2-2)",
        supplier="PKP Intercity",
        supplier_url=train.supplier_url,
        goal="Book EC 131.",
        amount_minor=59_999,
        status=train.status,
        passenger_user_ids=[second],
        proposal_item_index=0,
    ).insert()
    return [train, other]


async def _disrupt(person: Person, trip: Trip, percent: float) -> dict[str, Any]:
    response = await person.post(
        f"/api/trips/{trip.id}/demo/disruption",
        {"delay_minutes": 140, "price_change_percent": percent},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_disruption_replaces_every_purchase_of_the_train_and_resplits_once(
    people: list[Person],
) -> None:
    organizer, friend = people
    trip, train, _ = await _seed_trip(
        organizer, [friend], TripStatus.BOOKED, BookingStatus.CONFIRMED
    )
    parts = await _split_train(train, organizer, friend)

    body = await _disrupt(organizer, trip, -10)

    assert body["cancelled_booking_ids"] == [str(part.id) for part in parts]
    replacements = body["replacements"]
    # Each part repriced on its own, to whole grosze: 60 001 * 0.9 and 59 999 * 0.9.
    assert [r["amount_minor"] for r in replacements] == [54_001, 53_999]
    assert body["total_minor"] == 108_000 + STAY_MINOR
    assert body["trip_status"] == TripStatus.REBOOKING
    for part, replacement in zip(parts, replacements, strict=True):
        stored = await Booking.get(replacement["id"])
        assert stored is not None
        assert stored.replaces_booking_id == identifier_of(part)
        assert stored.passenger_user_ids == part.passenger_user_ids
        assert stored.status is BookingStatus.PENDING
        old = await Booking.get(identifier_of(part))
        assert old is not None and old.status is BookingStatus.CANCELLED
    assert len(await _events(trip, EventKind.RESPLIT)) == 1
    (disruption,) = await _events(trip, EventKind.DISRUPTION)
    assert len(disruption.payload["booking_ids"]) == 2


async def test_refunds_are_paid_out_when_the_trip_is_booked_again(
    people: list[Person],
) -> None:
    organizer, friend = people
    trip, _, _ = await _seed_trip(organizer, [friend], TripStatus.BOOKED, BookingStatus.CONFIRMED)
    body = await _disrupt(organizer, trip, -10)
    assert {c.status for c in await _contributions(trip)} == {ContributionStatus.REFUND_DUE}
    assert not await _events(trip, EventKind.REFUND_ISSUED)

    for replacement in body["replacements"]:
        stored = await Booking.get(replacement["id"])
        assert stored is not None
        await stored.set({"status": BookingStatus.HANDOFF})
        done = await organizer.post(
            f"/api/trips/{trip.id}/bookings/{stored.id}/complete", {"confirmation_ref": "PKP-1"}
        )
        assert done.status_code == 200, done.text

    assert await _trip_status(trip) is TripStatus.BOOKED
    contributions = await _contributions(trip)
    assert [c.amount_minor for c in contributions] == [84_000, 84_000]
    assert [c.paid_minor for c in contributions] == [84_000, 84_000]
    assert {c.status for c in contributions} == {ContributionStatus.PAID}
    refunds = await _events(trip, EventKind.REFUND_ISSUED)
    assert [event.payload["amount_minor"] for event in refunds] == [6_000, 6_000]
    assert refunds[0].message == "Refunded 60.00 PLN to Person0 Nowak."
    assert refunds[0].payload["provider_ref"].startswith("fake_refund_")


async def test_top_ups_after_a_dearer_disruption_resume_rebooking(people: list[Person]) -> None:
    organizer, friend = people
    trip, _, _ = await _seed_trip(organizer, [friend], TripStatus.BOOKED, BookingStatus.CONFIRMED)
    body = await _disrupt(organizer, trip, 20)
    assert body["trip_status"] == TripStatus.PAYING

    await friend.post(f"/api/trips/{trip.id}/contributions/pay")
    last = await organizer.post(f"/api/trips/{trip.id}/contributions/pay")
    assert last.status_code == 200, last.text
    assert last.json()["all_paid"] is True
    assert last.json()["status"] == TripStatus.REBOOKING
    assert await _trip_status(trip) is TripStatus.REBOOKING


async def _awaiting_approval(trip: Trip, booking: Booking) -> str:
    run_id = f"b{booking.id}-1"
    await AgentRun(
        run_id=run_id, booking_id=identifier_of(booking), trip_id=identifier_of(trip)
    ).insert()
    await booking.set({"status": BookingStatus.AWAITING_APPROVAL, "current_run_id": run_id})
    return run_id


@pytest.mark.parametrize(
    ("trip_status", "paid"),
    [(TripStatus.PAYING, False), (TripStatus.BOOKING, False), (TripStatus.PAYING, True)],
)
async def test_approval_is_refused_unless_the_trip_is_buying_and_fully_paid(
    people: list[Person], tmp_path: Any, trip_status: TripStatus, paid: bool
) -> None:
    organizer, friend = people
    trip, _, stay = await _seed_trip(organizer, [friend], trip_status, paid=paid)
    run_id = await _awaiting_approval(trip, stay)

    response = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{stay.id}/approve", {"approved": True}
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == BookingError.TRIP_NOT_READY
    stored = await Booking.get(identifier_of(stay))
    assert stored is not None and stored.status is BookingStatus.AWAITING_APPROVAL
    assert not (tmp_path / "runs" / run_id / "approval.json").exists()


async def test_a_summary_can_be_rejected_while_paying(people: list[Person]) -> None:
    organizer, friend = people
    trip, _, stay = await _seed_trip(organizer, [friend], TripStatus.PAYING, paid=False)
    await _awaiting_approval(trip, stay)
    response = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{stay.id}/approve", {"approved": False}
    )
    assert response.status_code == 200, response.text
    stored = await Booking.get(identifier_of(stay))
    assert stored is not None and stored.status is BookingStatus.HANDOFF


async def test_approval_goes_through_once_buying_and_fully_paid(
    people: list[Person], tmp_path: Any
) -> None:
    organizer, friend = people
    trip, _, stay = await _seed_trip(organizer, [friend], TripStatus.REBOOKING)
    run_id = await _awaiting_approval(trip, stay)
    response = await organizer.post(
        f"/api/trips/{trip.id}/bookings/{stay.id}/approve", {"approved": True}
    )
    assert response.status_code == 200, response.text
    stored = await Booking.get(identifier_of(stay))
    assert stored is not None and stored.status is BookingStatus.APPROVED
    assert (tmp_path / "runs" / run_id / "approval.json").is_file()
