"""Invariants checked against the database after EVERY step.

Each invariant is a named function from an `InvariantContext` (the snapshot before and after
the step, plus what the step was) to a list of human-readable violations. An invariant whose
feature has not landed yet carries a `known_issue` — its violations are reported as known, not
failed, until the feature exists.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from beanie import PydanticObjectId

from app.core.domain.bookings import contribution_status
from app.core.domain.trips import BookingKind, BookingStatus, ContributionStatus, TripStatus
from app.harness.features import Feature, feature
from app.models.bookings import AgentRun, Booking
from app.models.trips import Contribution, Trip, TripEvent, TripMember
from app.repositories.bookings import BookingRepository
from app.repositories.trips import ContributionRepository, MemberRepository, TripRepository
from app.suppliers.intercity import MAX_PASSENGERS_PER_PURCHASE

S = TripStatus

# From docs/PLAN.md and `TripStatus`. Steps are observed from outside, so a transaction that
# passes through DISRUPTED and ends in REBOOKING/PAYING is seen as one hop — listed explicitly.
ALLOWED_TRANSITIONS: frozenset[tuple[TripStatus, TripStatus]] = frozenset(
    {
        (S.COLLECTING, S.PROPOSING),
        (S.PROPOSING, S.VOTING),
        (S.PROPOSING, S.COLLECTING),  # research failed
        (S.VOTING, S.PROPOSING),  # re-research during voting
        (S.VOTING, S.PAYING),
        (S.PAYING, S.BOOKING),
        (S.BOOKING, S.BOOKED),
        (S.BOOKING, S.PAYING),  # a price change / drop-out / dearer disruption needs top-ups
        (S.BOOKING, S.REBOOKING),  # a cheaper disruption before everything was bought
        (S.BOOKED, S.DISRUPTED),
        (S.BOOKED, S.REBOOKING),  # via DISRUPTED, inside one transaction
        (S.BOOKED, S.PAYING),  # via DISRUPTED, a dearer replacement
        (S.DISRUPTED, S.REBOOKING),
        (S.DISRUPTED, S.PAYING),
        (S.REBOOKING, S.BOOKED),
        (S.REBOOKING, S.PAYING),
        (S.PAYING, S.REBOOKING),  # top-ups after a disruption are complete
        (S.BOOKED, S.DONE),
    }
)
# A booking in one of these has started buying — Rule #1 must have held when it got there.
BUYING = frozenset(
    {
        BookingStatus.RUNNING,
        BookingStatus.AWAITING_APPROVAL,
        BookingStatus.APPROVED,
        BookingStatus.CONFIRMED,
    }
)
PRE_SPLIT = frozenset({S.COLLECTING, S.PROPOSING, S.VOTING})


@dataclass(frozen=True, slots=True)
class Snapshot:
    trip: Trip
    members: list[TripMember]
    contributions: list[Contribution]
    bookings: list[Booking]
    runs: list[AgentRun]
    events: list[TripEvent]

    @property
    def live_bookings(self) -> list[Booking]:
        return [b for b in self.bookings if b.status is not BookingStatus.CANCELLED]

    @property
    def outstanding_minor(self) -> int:
        return sum(max(c.amount_minor - c.paid_minor, 0) for c in self.contributions)

    def booking(self, booking_id: PydanticObjectId | None) -> Booking | None:
        return next((b for b in self.bookings if b.id == booking_id), None)


async def load_snapshot(trip_id: PydanticObjectId) -> Snapshot:
    trip = await TripRepository().get(trip_id)
    if trip is None:
        raise LookupError(f"trip {trip_id} vanished")
    # Raw finds on indexed fields only (the test database runs with `notablescan`).
    runs = await AgentRun.find(AgentRun.trip_id == trip_id).sort("_id").to_list()
    events = await TripEvent.find(TripEvent.trip_id == trip_id).sort("_id").to_list()
    return Snapshot(
        trip=trip,
        members=await MemberRepository().for_trip(trip_id),
        contributions=await ContributionRepository().for_trip(trip_id),
        bookings=await BookingRepository().for_trip(trip_id),
        runs=runs,
        events=events,
    )


@dataclass(frozen=True, slots=True)
class InvariantContext:
    before: Snapshot | None
    after: Snapshot
    # Trip statuses observed during the step, in order (includes before/after).
    status_trail: Sequence[TripStatus]
    # Event kinds the step was supposed to produce (only when the step succeeded).
    expected_events: Sequence[str] = field(default_factory=tuple)

    @property
    def new_events(self) -> list[TripEvent]:
        seen = {e.id for e in self.before.events} if self.before else set()
        return [e for e in self.after.events if e.id not in seen]


type Check = Callable[[InvariantContext], list[str]]


@dataclass(frozen=True, slots=True)
class Invariant:
    name: str
    description: str
    check: Check
    known_issue: Callable[[], str | None] = lambda: None


def _shares_sum_to_total(ctx: InvariantContext) -> list[str]:
    snap = ctx.after
    if not snap.contributions:
        return []
    total = sum(c.amount_minor for c in snap.contributions)
    if total != snap.trip.total_minor:
        return [f"shares sum to {total}, trip total is {snap.trip.total_minor}"]
    return []


def _total_matches_bookings(ctx: InvariantContext) -> list[str]:
    snap = ctx.after
    if not snap.bookings:
        return []
    live = sum(b.amount_minor for b in snap.live_bookings)
    if live != snap.trip.total_minor:
        return [f"live bookings cost {live}, trip total is {snap.trip.total_minor}"]
    return []


def _amounts_non_negative(ctx: InvariantContext) -> list[str]:
    return [
        f"contribution of {c.user_id}: amount {c.amount_minor}, paid {c.paid_minor}"
        for c in ctx.after.contributions
        if c.amount_minor < 0 or c.paid_minor < 0
    ]


def _overpaid_only_as_refund(ctx: InvariantContext) -> list[str]:
    problems = []
    for c in ctx.after.contributions:
        if c.paid_minor > c.amount_minor and c.status is not ContributionStatus.REFUND_DUE:
            problems.append(
                f"{c.user_id} paid {c.paid_minor} > share {c.amount_minor} but is {c.status}"
            )
        expected = contribution_status(c.amount_minor, c.paid_minor)
        if c.status is not expected:
            problems.append(
                f"{c.user_id} is {c.status} with share {c.amount_minor} / paid "
                f"{c.paid_minor} (expected {expected})"
            )
    return problems


def _every_member_has_a_share(ctx: InvariantContext) -> list[str]:
    snap = ctx.after
    if snap.trip.status in PRE_SPLIT:
        return []
    owners = {c.user_id for c in snap.contributions}
    return [
        f"{m.display_name} is a member without a contribution"
        for m in snap.members
        if m.user_id not in owners
    ]


def _refunds_settled_when_booked(ctx: InvariantContext) -> list[str]:
    """A trip that is fully bought holds exactly its total: overpayments went back."""
    snap = ctx.after
    if snap.trip.status not in (S.BOOKED, S.DONE):
        return []
    owed = [c for c in snap.contributions if c.paid_minor > c.amount_minor]
    if not owed:
        return []
    back = sum(c.paid_minor - c.amount_minor for c in owed)
    return [f"trip is {snap.trip.status} but {len(owed)} member(s) still await {back} grosze back"]


def _rule_one(ctx: InvariantContext) -> list[str]:
    """No booking may enter a buying state while any share is unpaid."""
    before = ctx.before
    if before is None:
        return []
    problems = []
    for booking in ctx.after.bookings:
        previous = before.booking(booking.id)
        old = previous.status if previous is not None else BookingStatus.PENDING
        moved_forward = booking.status in BUYING and booking.status is not old
        if not moved_forward:
            continue
        owed = max(before.outstanding_minor, ctx.after.outstanding_minor)
        if owed > 0:
            problems.append(
                f"{booking.kind} booking moved {old} -> {booking.status} while "
                f"{owed} grosze of shares were unpaid"
            )
    return problems


def _passengers(booking: Booking, travellers: int) -> int:
    split: object = getattr(booking, "passenger_user_ids", None)
    return len(split) if isinstance(split, list) else travellers


def _purchase_cap(ctx: InvariantContext) -> list[str]:
    snap = ctx.after
    travellers = len(snap.members)
    return [
        f"train booking '{b.title}' covers {_passengers(b, travellers)} passengers "
        f"(PKP Intercity sells at most {MAX_PASSENGERS_PER_PURCHASE} per purchase)"
        for b in snap.live_bookings
        if b.kind is BookingKind.TRAIN
        and b.supplier == "PKP Intercity"
        and _passengers(b, travellers) > MAX_PASSENGERS_PER_PURCHASE
    ]


def _purchase_cap_known() -> str | None:
    info = feature(Feature.PASSENGER_SPLIT)
    return None if info.present else f"pending: {info.missing}"


def _state_machine(ctx: InvariantContext) -> list[str]:
    trail = list(ctx.status_trail)
    return [
        f"{old} -> {new} is not an allowed trip transition"
        for old, new in pairwise(trail)
        if old is not new and (old, new) not in ALLOWED_TRANSITIONS
    ]


def _money_steps_leave_events(ctx: InvariantContext) -> list[str]:
    kinds = {e.kind.value for e in ctx.new_events}
    return [f"no '{kind}' event in the feed" for kind in ctx.expected_events if kind not in kinds]


def _feed_is_chronological(ctx: InvariantContext) -> list[str]:
    events = ctx.after.events
    return [
        f"event '{later.kind}' ({later.created_at:%H:%M:%S.%f}) was written after "
        f"'{earlier.kind}' ({earlier.created_at:%H:%M:%S.%f}) but is dated before it"
        for earlier, later in pairwise(events)
        if later.created_at < earlier.created_at
    ]


INVARIANTS: tuple[Invariant, ...] = (
    Invariant(
        "shares_sum_to_total",
        "the contributions sum exactly to trip.total_minor",
        _shares_sum_to_total,
    ),
    Invariant(
        "total_matches_bookings",
        "trip.total_minor equals the price of the live (not cancelled) bookings",
        _total_matches_bookings,
    ),
    Invariant("amounts_non_negative", "no negative share or payment", _amounts_non_negative),
    Invariant(
        "overpaid_only_as_refund",
        "paid > share only with status refund_due; status always matches share/paid",
        _overpaid_only_as_refund,
    ),
    Invariant(
        "every_member_has_a_share",
        "after voting closed, every current member has a contribution",
        _every_member_has_a_share,
    ),
    Invariant(
        "refunds_settled_when_booked",
        "once the trip is booked, nobody's overpayment is still waiting to be refunded",
        _refunds_settled_when_booked,
    ),
    Invariant(
        "rule_1_paid_before_buying",
        "no booking left PENDING (started buying) while any share was unpaid",
        _rule_one,
    ),
    Invariant(
        "purchase_cap",
        f"no intercity train booking covers more than {MAX_PASSENGERS_PER_PURCHASE} passengers",
        _purchase_cap,
        _purchase_cap_known,
    ),
    Invariant("state_machine", "every observed trip transition is an allowed one", _state_machine),
    Invariant(
        "money_steps_leave_events",
        "every money-moving step produced its feed event",
        _money_steps_leave_events,
    ),
    Invariant(
        "feed_is_chronological",
        "feed events are dated in the order they were written",
        _feed_is_chronological,
    ),
)


@dataclass(frozen=True, slots=True)
class Violation:
    invariant: str
    message: str
    known: str | None  # why it is expected, or None for a real failure


def check_all(ctx: InvariantContext, known: dict[str, str]) -> list[Violation]:
    violations: list[Violation] = []
    for invariant in INVARIANTS:
        reason = known.get(invariant.name) or invariant.known_issue()
        violations.extend(
            Violation(invariant.name, message, reason) for message in invariant.check(ctx)
        )
    return violations
