"""Invariants checked against the database after EVERY step.

Each invariant is a named function from an `InvariantContext` (the snapshot before and after
the step, plus what the step was) to a list of human-readable violations. An invariant whose
feature has not landed yet carries a `known_issue` — its violations are reported as known, not
failed, until the feature exists.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any

from beanie import PydanticObjectId

from app.core.domain.bookings import contribution_status
from app.core.domain.escrow import CardStatus, EscrowTotals, PurchasePayment
from app.core.domain.suppliers import (
    SupplierCapabilities,
    hold_is_live,
    missing_traveller_fields,
    price_is_guaranteed,
)
from app.core.domain.trips import (
    BookingStatus,
    ContributionStatus,
    EventKind,
    SupplierChannel,
    TripStatus,
)
from app.core.domain.wallet import WalletTransactionKind, WalletTransactionStatus, held_minor
from app.harness.features import Feature, feature
from app.models.bookings import AgentRun, Booking
from app.models.travellers import TravellerProfile
from app.models.trips import Contribution, Trip, TripEvent, TripMember
from app.models.wallet import Wallet, WalletTransaction
from app.payments.fake_partner import card_view, movement_of
from app.payments.fake_partner_models import (
    PartnerCardRecord,
    PartnerLedgerRecord,
    PartnerWalletRecord,
)
from app.payments.partner import LedgerKind
from app.repositories.bookings import BookingRepository
from app.repositories.travellers import TravellerProfileRepository
from app.repositories.trips import ContributionRepository, MemberRepository, TripRepository
from app.services.escrow import escrow_totals
from app.services.travellers import details_of
from app.suppliers.registry import SupplierRegistry

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
        (S.PAYING, S.EXPIRED),  # the funding deadline passed: the escrow refunded everyone
    }
)
# A booking in one of these has started buying — Rule #1 must have held when it got there.
# Feed events that mark a purchase starting (see `_paid_before_buying`).
_STARTS = frozenset({EventKind.BOOKING_STARTED})
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
    profiles: dict[PydanticObjectId, TravellerProfile] = field(default_factory=dict)
    # The wallets of everyone with a share (members and former members) and their ledgers.
    wallets: dict[PydanticObjectId, int] = field(default_factory=dict)
    ledger: list[WalletTransaction] = field(default_factory=list)
    # The payment partner's side: each member's partner wallet balance (by our user id), the
    # trip escrow's totals and release state, its cards and its release movements.
    partner_balances: dict[PydanticObjectId, int] = field(default_factory=dict)
    escrow: EscrowTotals | None = None
    escrow_funded_minor: int = 0
    escrow_target_minor: int = 0
    cards: list[PartnerCardRecord] = field(default_factory=list)
    releases: list[PartnerLedgerRecord] = field(default_factory=list)

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
    members = await MemberRepository().for_trip(trip_id)
    contributions = await ContributionRepository().for_trip(trip_id)
    people = list({*(m.user_id for m in members), *(c.user_id for c in contributions)})
    wallets = await Wallet.find({"user_id": {"$in": people}}).to_list(len(people) + 1)
    ledger = await WalletTransaction.find({"user_id": {"$in": people}}).to_list(5_000)
    partner = await _partner_side(trip, wallets)
    return Snapshot(
        trip=trip,
        members=members,
        contributions=contributions,
        bookings=await BookingRepository().for_trip(trip_id),
        runs=runs,
        events=events,
        profiles=await TravellerProfileRepository().for_users([m.user_id for m in members]),
        wallets={w.user_id: w.balance_minor for w in wallets},
        ledger=ledger,
        **partner,
    )


async def _partner_side(trip: Trip, wallets: list[Wallet]) -> dict[str, Any]:
    """Read straight from the partner's collections — the harness audits the partner too."""
    linked = {w.user_id: w.partner_wallet_id for w in wallets if w.partner_wallet_id}
    records = await PartnerWalletRecord.find(
        {"wallet_id": {"$in": [*linked.values(), trip.escrow_wallet_id or ""]}}
    ).to_list(len(linked) + 2)
    by_id = {record.wallet_id: record for record in records}
    found: dict[str, Any] = {
        "partner_balances": {
            user: by_id[wallet].balance_minor for user, wallet in linked.items() if wallet in by_id
        }
    }
    escrow_id = trip.escrow_wallet_id
    if escrow_id is None or escrow_id not in by_id:
        return found
    entries = (
        await PartnerLedgerRecord.find(
            {"$or": [{"debit_wallet_id": escrow_id}, {"credit_wallet_id": escrow_id}]}
        )
        .sort("created_at", "_id")
        .to_list()
    )
    cards = await PartnerCardRecord.find(PartnerCardRecord.funding_wallet_id == escrow_id).to_list()
    totals = escrow_totals(
        [movement_of(entry) for entry in entries], [card_view(card) for card in cards], escrow_id
    )
    record = by_id[escrow_id]
    found.update(
        escrow=EscrowTotals(
            collected_minor=totals.collected_minor,
            paid_to_suppliers_minor=totals.paid_to_suppliers_minor,
            refunded_minor=totals.refunded_minor,
            reserved_minor=totals.reserved_minor,
            balance_minor=record.balance_minor,
        ),
        escrow_funded_minor=record.funded_minor,
        escrow_target_minor=record.release_target_minor,
        cards=cards,
        releases=[
            e
            for e in entries
            if e.debit_wallet_id == escrow_id
            and e.kind in (LedgerKind.PAYOUT, LedgerKind.CARD_FUNDING)
        ],
    )
    return found


@dataclass(frozen=True, slots=True)
class InvariantContext:
    before: Snapshot | None
    after: Snapshot
    # Trip statuses observed during the step, in order (includes before/after).
    status_trail: Sequence[TripStatus]
    # Event kinds the step was supposed to produce (only when the step succeeded).
    expected_events: Sequence[str] = field(default_factory=tuple)
    # The scenario's supplier plugins and the clock's "now" right after the step.
    suppliers: SupplierRegistry = field(default_factory=SupplierRegistry)
    now: datetime | None = None
    # HOLDS=on for the scenario: only then must a holding supplier's purchase run on a hold.
    holds: bool = True

    def capabilities(self, booking: Booking) -> SupplierCapabilities | None:
        adapter = self.suppliers.get(booking.supplier_id) if booking.supplier_id else None
        return adapter.capabilities if adapter is not None else None

    def started_buying(self) -> list[tuple[Booking, BookingStatus]]:
        """(booking, previous status) for every booking that moved INTO a buying state."""
        if self.before is None:
            return []
        moved = []
        for booking in self.after.bookings:
            previous = self.before.booking(booking.id)
            old = previous.status if previous is not None else BookingStatus.PENDING
            if booking.status in BUYING and booking.status is not old:
                moved.append((booking, old))
        return moved

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


def _paid_before_buying(ctx: InvariantContext) -> bool:
    """In this step every share was covered (ALL_PAID) before any purchase started — the
    AUTO_BOOK path, where the last payment and "book everything" share one step."""
    kinds = [event.kind for event in ctx.new_events]
    if EventKind.ALL_PAID not in kinds:
        return False
    paid_at = kinds.index(EventKind.ALL_PAID)
    return all(index > paid_at for index, kind in enumerate(kinds) if kind in _STARTS)


def _rule_one(ctx: InvariantContext) -> list[str]:
    """No booking may enter a buying state while any share is unpaid."""
    before = ctx.before
    if before is None:
        return []
    paid_first = _paid_before_buying(ctx)
    problems = []
    for booking in ctx.after.bookings:
        previous = before.booking(booking.id)
        old = previous.status if previous is not None else BookingStatus.PENDING
        moved_forward = booking.status in BUYING and booking.status is not old
        if not moved_forward:
            continue
        owed = (
            ctx.after.outstanding_minor
            if paid_first
            else max(before.outstanding_minor, ctx.after.outstanding_minor)
        )
        if owed > 0:
            problems.append(
                f"{booking.kind} booking '{booking.title}' moved {old} -> {booking.status} while "
                f"{owed} grosze of shares were unpaid"
            )
    return problems


def _passengers(booking: Booking, travellers: int) -> int:
    split: object = getattr(booking, "passenger_user_ids", None)
    return len(split) if isinstance(split, list) else travellers


def _purchase_cap(ctx: InvariantContext) -> list[str]:
    """Read off the supplier's capabilities — whoever the supplier is."""
    snap = ctx.after
    travellers = len(snap.members)
    problems = []
    for booking in snap.live_bookings:
        capabilities = ctx.capabilities(booking)
        cap = capabilities.max_party_per_purchase if capabilities else None
        carried = _passengers(booking, travellers)
        if cap is not None and carried > cap:
            problems.append(
                f"{booking.supplier_id} booking '{booking.title}' covers {carried} passengers "
                f"(the supplier sells at most {cap} per purchase)"
            )
    return problems


def _purchase_cap_known() -> str | None:
    info = feature(Feature.PASSENGER_SPLIT)
    return None if info.present else f"pending: {info.missing}"


def _traveller_details_before_purchase(ctx: InvariantContext) -> list[str]:
    """No purchase starts before its passengers have every field the supplier requires.
    Reports names and field names only — never a value."""
    snap = ctx.after
    members = {member.user_id: member for member in snap.members}
    problems = []
    for booking, old in ctx.started_buying():
        capabilities = ctx.capabilities(booking)
        # Checked where a purchase STARTS; later steps of the same purchase follow from it.
        if capabilities is None or old in BUYING:
            continue
        passengers = [members[uid] for uid in booking.passenger_user_ids if uid in members]
        provided = {
            member.display_name: details_of(
                member, snap.profiles.get(member.user_id)
            ).provided_fields()
            for member in passengers
        }
        missing = missing_traveller_fields(capabilities.required_traveller_fields, provided)
        for name, fields in missing.items():
            problems.append(
                f"'{booking.title}' moved {old} -> {booking.status} although {name} lacks "
                f"{', '.join(sorted(field.value for field in fields))}"
            )
    return problems


def _hold_live_at_purchase(ctx: InvariantContext) -> list[str]:
    """With holds on, a supplier that holds prices never sees a purchase step on a lapsed
    hold. With holds off nothing is held, and a supplier that refused to hold this offer
    holds nothing either: there `price_fresh_at_purchase` guards the re-quote."""
    if ctx.now is None or not ctx.holds:
        return []
    problems = []
    for booking, old in ctx.started_buying():
        capabilities = ctx.capabilities(booking)
        if capabilities is None or not capabilities.supports_hold:
            continue
        if booking.hold_ref is None and booking.hold_expires_at is None:
            continue  # never held (refused): bought on a fresh quote instead
        if not hold_is_live(booking.hold_expires_at, ctx.now):
            problems.append(
                f"'{booking.title}' moved {old} -> {booking.status} on a hold that expired at "
                f"{booking.hold_expires_at}"
            )
    return problems


def _price_fresh_at_purchase(ctx: InvariantContext) -> list[str]:
    """A purchase never uses a price older than the supplier's quote TTL (or a lapsed hold):
    checked when the agent starts and whenever an API purchase moves forward."""
    if ctx.now is None:
        return []
    problems = []
    for booking, old in ctx.started_buying():
        capabilities = ctx.capabilities(booking)
        if capabilities is None:
            continue
        direct = booking.channel is SupplierChannel.API
        if not direct and booking.status is not BookingStatus.RUNNING:
            continue
        if not price_is_guaranteed(
            capabilities,
            hold_expires_at=booking.hold_expires_at,
            quoted_at=booking.quoted_at,
            now=ctx.now,
        ):
            problems.append(
                f"'{booking.title}' moved {old} -> {booking.status} on a price quoted at "
                f"{booking.quoted_at} (TTL {capabilities.quote_ttl})"
            )
    return problems


def _no_document_numbers_in_feed(ctx: InvariantContext) -> list[str]:
    """A passport number never lands in the feed — not in a message, not in a payload."""
    numbers = [p.document_number for p in ctx.after.profiles.values() if p.document_number]
    if not numbers:
        return []
    problems = []
    for event in ctx.new_events:
        text = event.message + json.dumps(event.payload, default=str)
        if any(number in text for number in numbers):
            problems.append(f"a '{event.kind}' event contains a traveller's document number")
    return problems


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


def _wallets_match_ledgers(ctx: InvariantContext) -> list[str]:
    """Every balance is the sum of its completed ledger entries, and never negative."""
    snap = ctx.after
    problems = []
    for user_id in {*snap.wallets, *(e.user_id for e in snap.ledger)}:
        balance = snap.wallets.get(user_id, 0)
        booked = sum(
            e.amount_minor
            for e in snap.ledger
            if e.user_id == user_id and e.status is WalletTransactionStatus.COMPLETED
        )
        if balance != booked or balance < 0:
            problems.append(f"wallet of {user_id} holds {balance}, its ledger sums to {booked}")
    return problems


def _pot_never_negative(ctx: InvariantContext) -> list[str]:
    """The trip never spends or refunds money it did not collect from the wallets."""
    snap = ctx.after
    trip_entries = [
        e
        for e in snap.ledger
        if e.trip_id == snap.trip.id and e.status is WalletTransactionStatus.COMPLETED
    ]
    collected = -sum(
        e.amount_minor for e in trip_entries if e.kind is WalletTransactionKind.SHARE_PAYMENT
    )
    refunded = sum(e.amount_minor for e in trip_entries if e.kind is WalletTransactionKind.REFUND)
    spent = sum(b.amount_minor for b in snap.bookings if b.status is BookingStatus.CONFIRMED)
    held = held_minor(collected, spent, refunded)
    if held < 0:
        return [f"the pot is {held}: collected {collected}, spent {spent}, refunded {refunded}"]
    return []


def _escrow_balances(ctx: InvariantContext) -> list[str]:
    """Escrow = share transfers - payouts - card spends - refunds - live card reserves, >= 0."""
    escrow = ctx.after.escrow
    if escrow is None:
        return []
    problems = []
    if escrow.balance_minor < 0:
        problems.append(f"the escrow balance is negative: {escrow.balance_minor}")
    if escrow.held_minor != escrow.expected_held_minor:
        problems.append(
            f"the escrow holds {escrow.held_minor} (balance {escrow.balance_minor} + reserved "
            f"{escrow.reserved_minor}) but collected {escrow.collected_minor} - paid to "
            f"suppliers {escrow.paid_to_suppliers_minor} - refunded {escrow.refunded_minor} = "
            f"{escrow.expected_held_minor}"
        )
    return problems


def _card_limits(ctx: InvariantContext) -> list[str]:
    """No virtual card's limit exceeds its purchase amount, no card spends above its limit,
    and a card is charged at most once."""
    snap = ctx.after
    by_card = {
        b.payment_ref: b
        for b in snap.bookings
        if b.payment_kind is PurchasePayment.VIRTUAL_CARD and b.payment_ref
    }
    problems = []
    for card in snap.cards:
        booking = by_card.get(card.card_id)
        if booking is not None and card.limit_minor > booking.amount_minor:
            problems.append(
                f"card {card.card_id} limit {card.limit_minor} > purchase {booking.amount_minor}"
            )
        if card.spent_minor > card.limit_minor:
            problems.append(f"card {card.card_id} spent {card.spent_minor} > {card.limit_minor}")
        if card.status is not CardStatus.USED and card.spent_minor:
            problems.append(f"card {card.card_id} spent money but is {card.status}")
    return problems


def _no_release_before_funded(ctx: InvariantContext) -> list[str]:
    """Rule #1 at the partner: a payout or card funding only from a 100% funded escrow."""
    before = {e.entry_id for e in ctx.before.releases} if ctx.before else set()
    fresh = [e for e in ctx.after.releases if e.entry_id not in before]
    if not fresh:
        return []
    snap = ctx.after
    problems = []
    if snap.escrow_funded_minor < snap.escrow_target_minor or snap.escrow_target_minor <= 0:
        problems.append(
            f"{len(fresh)} release(s) while the escrow is funded {snap.escrow_funded_minor} of "
            f"{snap.escrow_target_minor}"
        )
    if snap.outstanding_minor > 0:
        problems.append(f"{len(fresh)} release(s) while {snap.outstanding_minor} is still owed")
    return problems


def _mirror_matches_partner(ctx: InvariantContext) -> list[str]:
    """Our wallet mirror equals the member's e-money wallet at the partner."""
    snap = ctx.after
    return [
        f"wallet of {user} mirrors {snap.wallets.get(user, 0)}, the partner holds {balance}"
        for user, balance in snap.partner_balances.items()
        if snap.wallets.get(user, 0) != balance
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
        "no booking carries more passengers than its supplier's max_party_per_purchase",
        _purchase_cap,
        _purchase_cap_known,
    ),
    Invariant(
        "traveller_details_before_purchase",
        "no purchase starts before its passengers have the fields the supplier requires",
        _traveller_details_before_purchase,
    ),
    Invariant(
        "hold_live_at_purchase",
        "no purchase step on a booking whose supplier hold has expired",
        _hold_live_at_purchase,
    ),
    Invariant(
        "price_fresh_at_purchase",
        "a purchase never uses a price older than the supplier's quote TTL",
        _price_fresh_at_purchase,
    ),
    Invariant(
        "no_document_numbers_in_feed",
        "traveller document numbers never appear in feed messages or payloads",
        _no_document_numbers_in_feed,
    ),
    Invariant("state_machine", "every observed trip transition is an allowed one", _state_machine),
    Invariant(
        "money_steps_leave_events",
        "every money-moving step produced its feed event",
        _money_steps_leave_events,
    ),
    Invariant(
        "wallets_match_ledgers",
        "every wallet balance equals its completed ledger entries and is never negative",
        _wallets_match_ledgers,
    ),
    Invariant(
        "pot_never_negative",
        "the trip never spends or refunds more than it collected from the wallets",
        _pot_never_negative,
    ),
    Invariant(
        "escrow_balances",
        "escrow = share transfers - payouts - card spends - refunds (- live card reserves), "
        "never negative",
        _escrow_balances,
    ),
    Invariant(
        "card_within_purchase",
        "no virtual card limit above its purchase amount; each card charged once, within it",
        _card_limits,
    ),
    Invariant(
        "no_release_before_funded",
        "no payout or card funding before the escrow is 100% funded (Rule #1 at the partner)",
        _no_release_before_funded,
    ),
    Invariant(
        "member_wallet_matches_partner",
        "every member's mirrored wallet equals their wallet at the payment partner",
        _mirror_matches_partner,
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
    """Every invariant against one step; a violation named in `known` is reported, not failed."""
    violations: list[Violation] = []
    for invariant in INVARIANTS:
        reason = known.get(invariant.name) or invariant.known_issue()
        violations.extend(
            Violation(invariant.name, message, reason) for message in invariant.check(ctx)
        )
    return violations
