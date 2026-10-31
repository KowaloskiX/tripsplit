"""The day-by-day plan and the attraction tickets it needs. No HTTP here.

`generate` (the organizer's "Plan the days" button, again whenever the votes change) takes the
attractions the group voted for (`select_for_plan`), the transport of the chosen package
(arrival on day one, departure on the last day) and the hotel's location when the stay
supplier knows it, and schedules everything with the deterministic rules of
`app.core.domain.day_plan`. No LLM.

A planned visit to a BOOKABLE attraction becomes a ticket purchase: a PENDING `Booking` for the
planned day and entry slot, bought by its supplier's channel (the agent on the demo ticket shop)
with everything else once every share is paid. Adding (or dropping) one changes what the group
pays, so the shares are re-split in the same transaction — exactly like a re-quote — and a trip
that was already fully paid goes back to PAYING for the top-up. Rule #1 never bends: tickets
are bought only after that. Tickets already being bought (or bought) are never moved: their
slot is fixed in every later plan.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.ai.itinerary import directions
from app.core.domain.attractions import (
    AttractionKind,
    OpeningHours,
    Tally,
    TicketStatus,
    coordinate,
    select_for_plan,
    ticket_goal,
)
from app.core.domain.bookings import format_money
from app.core.domain.day_plan import (
    ItemKind,
    PlanDay,
    PlannedAttraction,
    Point,
    TransportLeg,
    TripFrame,
    build_plan,
    capacity,
)
from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import SupplierCapabilities, as_utc, purchase_sizes
from app.core.domain.trips import (
    BookingKind,
    BookingStatus,
    EventActor,
    EventKind,
    SupplierChannel,
    TripStatus,
)
from app.db.client import Database
from app.db.identifiers import identifier_of, to_text
from app.models.bookings import Booking
from app.models.itinerary import (
    AttractionCandidate,
    ItineraryDay,
    ItineraryEntry,
    TripAttractions,
)
from app.models.trips import Proposal, Trip, TripMember
from app.repositories.bookings import BookingRepository
from app.repositories.itinerary import ItineraryRepository
from app.repositories.trips import (
    EventRepository,
    MemberRepository,
    ProposalRepository,
    TripRepository,
)
from app.services.attractions import AFTER_THE_VOTE, VOTING_OPEN, AttractionService
from app.services.resplit import resplit_shares, status_once_paid
from app.services.trip_access import TripAccess, load_access, require_organizer
from app.suppliers.ports import Segment
from app.suppliers.registry import SupplierRegistry

# Destination wall clocks. The demo's cities are all on Central European Time.
DEFAULT_ZONE = "Europe/Warsaw"
ZONES: dict[str, str] = {"lisbon": "Europe/Lisbon", "lisboa": "Europe/Lisbon"}
ATTRACTION_KEY = "attraction_id"
SLOT_KEY = "slot_start"
# A trip whose tickets may still be added or dropped (the money can still move).
MONEY_OPEN = frozenset({TripStatus.PAYING, TripStatus.BOOKING, TripStatus.BOOKED})
_IN_FLIGHT = frozenset(
    {BookingStatus.RUNNING, BookingStatus.AWAITING_APPROVAL, BookingStatus.APPROVED}
)
_REPLACEABLE = frozenset({BookingStatus.PENDING, BookingStatus.FAILED})
_TICKET_STATUS: dict[BookingStatus, TicketStatus] = {
    BookingStatus.PENDING: TicketStatus.TO_BUY,
    BookingStatus.FAILED: TicketStatus.NEEDS_HELP,
    BookingStatus.HANDOFF: TicketStatus.NEEDS_HELP,
    BookingStatus.RUNNING: TicketStatus.BUYING,
    BookingStatus.AWAITING_APPROVAL: TicketStatus.BUYING,
    BookingStatus.APPROVED: TicketStatus.BUYING,
    BookingStatus.CONFIRMED: TicketStatus.BOOKED,
}


@dataclass(frozen=True, slots=True)
class ItemView:
    start: str  # "HH:MM", local at the destination
    end: str
    kind: ItemKind
    title: str
    place: str
    lat: float | None
    lon: float | None
    link: str
    map_url: str
    note: str
    attraction_id: str | None
    tickets: TicketStatus | None
    booking_id: str | None


@dataclass(frozen=True, slots=True)
class DayView:
    date: date
    label: str  # "Saturday"
    items: list[ItemView]


@dataclass(frozen=True, slots=True)
class ItineraryView:
    trip_id: str
    generated_at: datetime | None
    # The votes changed since the plan was made: the organizer may plan again.
    stale: bool
    days: list[DayView]


def zone_for(destination: str) -> ZoneInfo:
    folded = destination.casefold()
    return ZoneInfo(next((z for key, z in ZONES.items() if key in folded), DEFAULT_ZONE))


def map_url(lat: float | None, lon: float | None) -> str:
    if lat is not None and lon is not None:
        return f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=17"
    return ""


def votes_signature(
    candidates: Sequence[AttractionCandidate], members: set[PydanticObjectId]
) -> str:
    return ",".join(
        f"{c.attraction_id}:{sum(1 for v in c.voter_ids if v in members)}"
        for c in sorted(candidates, key=lambda c: c.attraction_id)
    )


def _local(moment: datetime, zone: ZoneInfo) -> datetime:
    return as_utc(moment).astimezone(zone).replace(tzinfo=None)


def transport_legs(
    proposal: Proposal | None, zone: ZoneInfo
) -> tuple[TransportLeg | None, TransportLeg | None]:
    """The way there and the way back of the chosen package, in destination wall-clock time."""
    if proposal is None:
        return None, None
    segments = [
        Segment(s.carrier, s.number, s.origin, s.destination, s.departs_at, s.arrives_at)
        for item in proposal.items
        if item.kind is BookingKind.TRANSPORT
        for s in item.segments
    ]
    out, back = directions(segments)

    def leg(legs: list[Segment]) -> TransportLeg | None:
        if not legs:
            return None
        return TransportLeg(
            title=" + ".join(s.number for s in legs),
            departs_at=_local(legs[0].departs_at, zone),
            arrives_at=_local(legs[-1].arrives_at, zone),
            origin=legs[0].origin,
            destination=legs[-1].destination,
        )

    return leg(out), leg(back)


def base_of(
    proposal: Proposal | None, candidates: Sequence[AttractionCandidate]
) -> tuple[Point | None, str]:
    """The hotel when its supplier gave coordinates, else the middle of the candidates."""
    stay = (
        next((item for item in proposal.items if item.kind is BookingKind.STAY), None)
        if proposal
        else None
    )
    if stay is not None:
        lat = coordinate(stay.supplier_data.get("lat") or stay.supplier_data.get("latitude"), 90)
        lon = coordinate(stay.supplier_data.get("lon") or stay.supplier_data.get("longitude"), 180)
        name = stay.title if len(stay.title) <= 40 else "the hotel"
        if lat is not None and lon is not None:
            return Point(lat, lon), name
    points = [Point(c.lat, c.lon) for c in candidates if c.lat is not None and c.lon is not None]
    centre = (
        Point(sum(p.lat for p in points) / len(points), sum(p.lon for p in points) / len(points))
        if points
        else None
    )
    return centre, "the hotel" if stay is not None else "the centre"


def _hours(candidate: AttractionCandidate) -> OpeningHours | None:
    if candidate.opens is None or candidate.closes is None:
        return None
    try:
        return OpeningHours(
            time.fromisoformat(candidate.opens), time.fromisoformat(candidate.closes)
        )
    except ValueError:
        return None


def planned(candidate: AttractionCandidate, fixed_at: datetime | None) -> PlannedAttraction:
    point = (
        Point(candidate.lat, candidate.lon)
        if candidate.lat is not None and candidate.lon is not None
        else None
    )
    return PlannedAttraction(
        id=candidate.attraction_id,
        title=candidate.title,
        point=point,
        minutes=candidate.duration_minutes,
        hours=_hours(candidate),
        ticketed=candidate.bookable,
        link=candidate.website,
        fixed_at=fixed_at,
        is_meal=candidate.kind is AttractionKind.FOOD,
    )


def slot_of(booking: Booking) -> datetime | None:
    raw = booking.supplier_data.get(SLOT_KEY)
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def ticket_bookings_of(bookings: Sequence[Booking]) -> dict[str, list[Booking]]:
    """Live ticket purchases by attraction (a party above the shop's cap is several)."""
    grouped: dict[str, list[Booking]] = {}
    for booking in bookings:
        aid = booking.supplier_data.get(ATTRACTION_KEY)
        if isinstance(aid, str) and booking.status is not BookingStatus.CANCELLED:
            grouped.setdefault(aid, []).append(booking)
    return grouped


def ticket_purchases(
    trip: Trip,
    candidate: AttractionCandidate,
    start: datetime,
    passengers: list[PydanticObjectId],
    capabilities: SupplierCapabilities | None,
) -> list[Booking]:
    """The PENDING booking(s) buying the group's tickets for one planned slot."""
    per_person = candidate.price_per_person_minor or 0
    sizes = purchase_sizes(len(passengers), capabilities) if capabilities else [len(passengers)]
    channel = capabilities.channel if capabilities else SupplierChannel.AGENT
    bookings: list[Booking] = []
    first = 0
    for number, size in enumerate(sizes, start=1):
        part = (
            f"This is purchase {number} of {len(sizes)}: visitors {first + 1}-{first + size}."
            if len(sizes) > 1
            else ""
        )
        amount = per_person * size
        bookings.append(
            Booking(
                trip_id=identifier_of(trip),
                kind=BookingKind.ACTIVITY,
                title=f"{size} tickets: {candidate.title} ({start:%a %H:%M})"[:200],
                supplier=candidate.supplier_name or candidate.provenance or "Ticket shop",
                supplier_url=candidate.purchase_url,
                goal=ticket_goal(
                    title=candidate.title,
                    day=start.date().isoformat(),
                    slot=f"{start:%H:%M}",
                    tickets=size,
                    budget=format_money(amount, candidate.currency),
                    part=part,
                ),
                amount_minor=amount,
                passenger_user_ids=passengers[first : first + size],
                supplier_id=candidate.supplier_id,
                offer_ref=candidate.offer_ref,
                channel=channel,
                supplier_data={
                    **candidate.supplier_data,
                    ATTRACTION_KEY: candidate.attraction_id,
                    SLOT_KEY: start.isoformat(),
                },
            )
        )
        first += size
    return bookings


def _entry(item_start: datetime, item_end: datetime, **fields: object) -> ItineraryEntry:
    return ItineraryEntry.model_validate({"start": item_start, "end": item_end, **fields})


def stored_days(plan: list[PlanDay]) -> list[ItineraryDay]:
    return [
        ItineraryDay(
            day=day.day,
            items=[
                _entry(
                    item.start,
                    item.end,
                    kind=item.kind,
                    title=item.title[:200],
                    place=item.place[:200],
                    lat=item.point.lat if item.point else None,
                    lon=item.point.lon if item.point else None,
                    link=item.link,
                    note=item.note,
                    attraction_id=item.attraction_id,
                )
                for item in day.items
            ],
        )
        for day in plan
    ]


def _short(item: ItineraryEntry) -> str:
    return item.title if item.kind is ItemKind.ATTRACTION else item.title.lower()


def plan_message(days: Sequence[ItineraryDay]) -> str:
    """ "Here is the plan for Saturday: 10:00 Prague Castle, 13:00 lunch, ..." — the busiest day."""
    if not days:
        return "Here is the plan."
    busiest = max(days, key=lambda d: sum(1 for i in d.items if i.kind is ItemKind.ATTRACTION))
    steps = [
        f"{item.start:%H:%M} {_short(item)}"
        for item in busiest.items
        if item.kind in (ItemKind.ATTRACTION, ItemKind.MEAL)
    ]
    visits = sum(1 for d in days for i in d.items if i.kind is ItemKind.ATTRACTION)
    body = ", ".join(steps) if steps else "free time"
    return (
        f"Here is the plan for {busiest.day:%A}: {body}. {len(days)} day(s), {visits} "
        "attraction(s) in total — open the plan for every day."
    )


class ItineraryService:
    def __init__(self, db: Database, *, suppliers: SupplierRegistry | None = None) -> None:
        self.db = db
        self.suppliers = suppliers if suppliers is not None else SupplierRegistry()
        self.attractions = AttractionService(db, suppliers=self.suppliers)
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.proposals = ProposalRepository()
        self.events = EventRepository()
        self.bookings = BookingRepository()
        self.itineraries = ItineraryRepository()

    async def _access(self, trip_id: str, user_id: str) -> Result[TripAccess, TripError]:
        return await load_access(trip_id, user_id, trips=self.trips, members=self.members)

    # ---- reads ----------------------------------------------------------------------------

    async def get(self, trip_id: str, user_id: str) -> Result[ItineraryView, TripError]:
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip = access.value.trip
        if trip.status not in AFTER_THE_VOTE:
            return Err(TripError.INVALID_STATE)
        return Ok(await self._view(trip))

    async def _view(self, trip: Trip) -> ItineraryView:
        trip_oid = identifier_of(trip)
        stored = await self.itineraries.get(trip_oid)
        candidates = await self.attractions.attractions.get(trip_oid)
        members = {m.user_id for m in await self.members.for_trip(trip_oid)}
        tickets = ticket_bookings_of(await self.bookings.for_trip(trip_oid))
        if stored is None:
            return ItineraryView(to_text(trip_oid), None, False, [])
        signature = votes_signature(candidates.candidates, members) if candidates else ""
        return ItineraryView(
            trip_id=to_text(trip_oid),
            generated_at=stored.generated_at,
            stale=signature != stored.votes_signature,
            days=[_day_view(day, tickets) for day in stored.days],
        )

    # ---- the plan -------------------------------------------------------------------------

    async def generate(self, trip_id: str, user_id: str) -> Result[ItineraryView, TripError]:
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        if (error := require_organizer(access.value)) is not None:
            return Err(error)
        trip = access.value.trip
        if trip.status not in VOTING_OPEN:
            return Err(TripError.INVALID_STATE)
        trip_oid = identifier_of(trip)
        stored = await self.attractions.snapshot(trip)
        members = await self.members.for_trip(trip_oid)
        bookings = await self.bookings.for_trip(trip_oid)
        money_open = trip.status in MONEY_OPEN and not any(b.status in _IN_FLIGHT for b in bookings)
        chosen = (
            await self.proposals.get(trip.chosen_proposal_id)
            if trip.chosen_proposal_id is not None
            else None
        )
        plan = self._plan(trip, stored, members, bookings, chosen, money_open=money_open)
        days = stored_days(plan)
        signature = votes_signature(stored.candidates, {m.user_id for m in members})

        async def write(session: AsyncClientSession) -> None:
            await self.itineraries.replace(trip_oid, days, signature, session)
            await self.events.add(
                trip_oid,
                EventKind.ITINERARY_READY,
                EventActor.AGENT,
                plan_message(days),
                payload={"days": len(days)},
                session=session,
            )
            if money_open:
                await self._sync_tickets(trip, stored, members, plan, session)

        await self.db.in_transaction(write)
        fresh = await self.trips.get(trip_oid) or trip
        return Ok(await self._view(fresh))

    def _plan(
        self,
        trip: Trip,
        stored: TripAttractions,
        members: list[TripMember],
        bookings: list[Booking],
        chosen: Proposal | None,
        *,
        money_open: bool,
    ) -> list[PlanDay]:
        zone = zone_for(stored.destination)
        there, back = transport_legs(chosen, zone)
        base, base_name = base_of(chosen, stored.candidates)
        frame = TripFrame(
            first_day=trip.date_from,
            last_day=trip.date_to,
            there=there,
            back=back,
            base=base,
            base_name=base_name,
        )
        by_id = {c.attraction_id: c for c in stored.candidates}
        current = {m.user_id for m in members}
        # Tickets already being bought (or bought) keep their slot; while the money cannot
        # move, so do the queued ones.
        fixed: dict[str, datetime] = {}
        for aid, parts in ticket_bookings_of(bookings).items():
            slot = slot_of(parts[0])
            settled = any(p.status not in _REPLACEABLE for p in parts)
            if aid in by_id and slot is not None and (settled or not money_open):
                fixed[aid] = slot
        tallies = [
            Tally(c.attraction_id, sum(1 for v in c.voter_ids if v in current), c.rank)
            for c in stored.candidates
            if c.attraction_id not in fixed
        ]
        chosen_ids = select_for_plan(tallies, len(members), capacity(frame) - len(fixed))
        attractions = [planned(by_id[aid], fixed_at) for aid, fixed_at in fixed.items()] + [
            planned(by_id[aid], None) for aid in chosen_ids
        ]
        return build_plan(frame, attractions)

    async def _sync_tickets(
        self,
        trip: Trip,
        stored: TripAttractions,
        members: list[TripMember],
        plan: list[PlanDay],
        session: AsyncClientSession,
    ) -> None:
        """Queues tickets for every planned bookable visit, drops queued tickets the plan no
        longer has (or moves them to the new slot) and re-splits when the total moved."""
        trip_oid = identifier_of(trip)
        by_id = {c.attraction_id: c for c in stored.candidates}
        wanted = {
            item.attraction_id: item.start
            for day in plan
            for item in day.items
            if item.attraction_id in by_id and by_id[item.attraction_id].bookable
        }
        existing = ticket_bookings_of(await self.bookings.for_trip(trip_oid, session))
        passengers = [m.user_id for m in members]
        added: list[tuple[AttractionCandidate, datetime, int]] = []
        dropped = False
        for aid, parts in existing.items():
            if any(p.status not in _REPLACEABLE for p in parts):
                continue  # being bought or bought: never touched
            start = wanted.get(aid)
            if start is None:
                await self.bookings.delete_many(parts, session)
                dropped = True
            elif slot_of(parts[0]) != start:
                await self.bookings.delete_many(parts, session)
                for booking in self._purchases(trip, by_id[aid], start, passengers):
                    await self.bookings.add(booking, session)
        for aid, start in wanted.items():
            if aid in existing:
                continue
            purchases = self._purchases(trip, by_id[aid], start, passengers)
            for booking in purchases:
                await self.bookings.add(booking, session)
            added.append((by_id[aid], start, sum(b.amount_minor for b in purchases)))
        if not added and not dropped:
            return
        for candidate, start, amount in added:
            await self.events.add(
                trip_oid,
                EventKind.MESSAGE,
                EventActor.AGENT,
                f"I added {len(passengers)} tickets for {candidate.title} ({start:%a %H:%M}, "
                f"{format_money(amount, trip.currency)}) to the trip. I buy them with "
                "everything else once every share is covered.",
                payload={"attraction_id": candidate.attraction_id, "amount_minor": amount},
                session=session,
            )
        await self._resplit(trip, session)

    def _purchases(
        self,
        trip: Trip,
        candidate: AttractionCandidate,
        start: datetime,
        passengers: list[PydanticObjectId],
    ) -> list[Booking]:
        adapter = self.suppliers.get(candidate.supplier_id)
        capabilities = adapter.capabilities if adapter is not None else None
        return ticket_purchases(trip, candidate, start, passengers, capabilities)

    async def _resplit(self, trip: Trip, session: AsyncClientSession) -> None:
        """The trip costs what its live bookings cost; somebody owing sends a paid trip back
        to PAYING, nobody owing lets a paying one go on to buying."""
        trip_oid = identifier_of(trip)
        live = [
            b
            for b in await self.bookings.for_trip(trip_oid, session)
            if b.status is not BookingStatus.CANCELLED
        ]
        fresh = await self.trips.get(trip_oid, session) or trip
        split = await resplit_shares(fresh, sum(b.amount_minor for b in live), session)
        if split.owes and fresh.status in (TripStatus.BOOKING, TripStatus.BOOKED):
            await self.trips.set_status(fresh, TripStatus.PAYING, session)
        elif not split.owes and fresh.status is TripStatus.PAYING and split.shares:
            await self.trips.set_status(fresh, await status_once_paid(trip_oid, session), session)
            await self.events.add(
                trip_oid,
                EventKind.ALL_PAID,
                EventActor.AGENT,
                "Everyone paid — the agent can book now.",
                payload={"total_minor": split.total_minor},
                session=session,
            )


def _day_view(day: ItineraryDay, tickets: dict[str, list[Booking]]) -> DayView:
    items = []
    for entry in day.items:
        parts = tickets.get(entry.attraction_id or "", [])
        matching = [p for p in parts if slot_of(p) == entry.start]
        status = _ticket_status(matching or parts) if parts else None
        items.append(
            ItemView(
                start=f"{entry.start:%H:%M}",
                end=f"{entry.end:%H:%M}",
                kind=entry.kind,
                title=entry.title,
                place=entry.place,
                lat=entry.lat,
                lon=entry.lon,
                link=entry.link,
                map_url=map_url(entry.lat, entry.lon),
                note=entry.note,
                attraction_id=entry.attraction_id,
                tickets=status,
                booking_id=to_text(identifier_of((matching or parts)[0])) if parts else None,
            )
        )
    return DayView(date=day.day, label=f"{day.day:%A}", items=items)


def _ticket_status(parts: list[Booking]) -> TicketStatus:
    """The least advanced part decides: two purchases are booked only when both are."""
    order = list(TicketStatus)
    statuses = [_TICKET_STATUS.get(p.status, TicketStatus.TO_BUY) for p in parts]
    if TicketStatus.NEEDS_HELP in statuses:
        return TicketStatus.NEEDS_HELP
    return min(statuses, key=order.index)
