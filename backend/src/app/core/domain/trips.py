"""The trip domain: states, kinds and the money rule. Pure Python — no framework, no database.

This module is the contract shared by the "group & money" side (trips, proposals, votes,
contributions, events) and the "agent & booking" side (bookings, agent runs).
"""

from dataclasses import dataclass
from enum import StrEnum


class TripStatus(StrEnum):
    """collecting -> proposing -> voting -> paying -> booking -> booked -> done,
    with booked -> disrupted -> rebooking -> booked for post-purchase care."""

    COLLECTING = "collecting"  # members join, organizer sets the brief
    PROPOSING = "proposing"  # the AI is researching packages
    VOTING = "voting"  # three packages on the table
    PAYING = "paying"  # a package won; each member pays their share
    BOOKING = "booking"  # everyone paid; the agent is buying
    BOOKED = "booked"  # every booking confirmed
    DISRUPTED = "disrupted"  # a delay / cancellation / drop-out was reported
    REBOOKING = "rebooking"  # the agent is buying the replacement
    DONE = "done"
    # Not 100% funded by `pay_by`: the escrow refunded every paid share. Terminal.
    EXPIRED = "expired"


class MemberRole(StrEnum):
    ORGANIZER = "organizer"
    MEMBER = "member"


class BookingKind(StrEnum):
    """What a purchase is, independent of who sells it. How a transport moves is its
    `TransportMode`; the supplier behind it is a plugin (see `app.suppliers.ports`)."""

    TRANSPORT = "transport"
    STAY = "stay"
    ACTIVITY = "activity"


class TransportMode(StrEnum):
    RAIL = "rail"
    FLIGHT = "flight"
    BUS = "bus"
    FERRY = "ferry"


MAX_TRANSFERS_LIMIT = 3


@dataclass(frozen=True, slots=True)
class TravelPreferences:
    """The organizer's simple transport preferences; None = no preference.

    `earliest_departure_hour` (0-23, local time at the departure station/airport) applies to
    every leg; `max_transfers` counts changes within one direction (0 = direct only).
    """

    earliest_departure_hour: int | None = None
    max_transfers: int | None = None

    def accepts(self, departure_hour: int, transfers: int) -> bool:
        if (
            self.earliest_departure_hour is not None
            and departure_hour < self.earliest_departure_hour
        ):
            return False
        return self.max_transfers is None or transfers <= self.max_transfers


NO_PREFERENCES = TravelPreferences()


class SupplierChannel(StrEnum):
    """How a purchase at a supplier is made."""

    API = "api"  # the supplier's own booking API, called by the backend after the approval
    AGENT = "agent"  # the browser agent drives the supplier's site up to the pay click
    MANUAL = "manual"  # a human books it by hand and enters the reference


# Before suppliers became plugins, rail was a kind of its own. Stored documents may still say so.
LEGACY_TRAIN_KIND = "train"


def upgrade_legacy_kind(raw: dict[str, object]) -> dict[str, object]:
    """Reads a stored item or booking written before `transport` existed: kind `train` becomes
    kind `transport` with mode `rail`. Anything else is returned unchanged (expand-contract:
    the readers accept both shapes until the backfill migration has run everywhere)."""
    if raw.get("kind") != LEGACY_TRAIN_KIND:
        return raw
    return {**raw, "kind": BookingKind.TRANSPORT.value, "mode": raw.get("mode") or "rail"}


class BookingStatus(StrEnum):
    PENDING = "pending"  # created, agent not started
    RUNNING = "running"  # the agent is driving the supplier site
    AWAITING_APPROVAL = "awaiting_approval"  # summary reached; a human must approve the pay click
    APPROVED = "approved"  # approved; the agent performs the final click
    CONFIRMED = "confirmed"  # supplier confirmation captured
    HANDOFF = "handoff"  # CAPTCHA / OTP / login wall — a human must finish
    FAILED = "failed"  # stuck, step cap or error
    CANCELLED = "cancelled"  # replaced by a rebooking


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"


class AgentOutcome(StrEnum):
    """Mirrors `RunResult.outcome` in `app.agent.runner`."""

    DONE = "done"
    HANDOFF = "handoff"
    STUCK = "stuck"
    MAX_STEPS = "max_steps"
    ERROR = "error"
    UNKNOWN = "unknown"


class RunStepStatus(StrEnum):
    """One step of an agent run, as `status.json` reports it."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    HEALED = "healed"  # a replayed step that missed and was re-planned


class RunStepSource(StrEnum):
    """Where a step's decision came from."""

    FLOW = "flow"  # a recorded flow, replayed
    RULE = "rule"  # a deterministic rule
    LLM = "llm"  # the planner model (including the follow-ups of one macro plan)
    HUMAN = "human"  # the approval


class ContributionStatus(StrEnum):
    PENDING = "pending"  # owes `amount_minor - paid_minor`
    PAID = "paid"  # paid in full
    REFUND_DUE = "refund_due"  # paid more than the current share (after a cheaper rebooking)


class EventActor(StrEnum):
    AGENT = "agent"
    MEMBER = "member"
    SYSTEM = "system"


class EventKind(StrEnum):
    TRIP_CREATED = "trip_created"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    MESSAGE = "message"  # free text from a member or the agent
    PROPOSALS_READY = "proposals_ready"
    VOTE_CAST = "vote_cast"
    PROPOSAL_CHOSEN = "proposal_chosen"
    CONTRIBUTION_PAID = "contribution_paid"
    ALL_PAID = "all_paid"
    BOOKING_STARTED = "booking_started"
    BOOKING_AWAITING_APPROVAL = "booking_awaiting_approval"
    BOOKING_CONFIRMED = "booking_confirmed"
    BOOKING_FAILED = "booking_failed"
    DISRUPTION = "disruption"
    RESPLIT = "resplit"
    PRICE_CHANGED = "price_changed"  # the supplier re-quoted a booking before the purchase
    REFUND_ISSUED = "refund_issued"  # an overpayment went back to the member
    HOLD_PLACED = "hold_placed"  # the supplier holds the price while the group pays
    HOLD_EXPIRED = "hold_expired"  # the hold lapsed before the purchase — re-held / re-quoted
    TRAVELLER_DETAILS_MISSING = "traveller_details_missing"  # names who still has to fill in
    ESCROW_OPENED = "escrow_opened"  # the partner opened the trip escrow; the pay-by deadline
    SUPPLIER_PAID = "supplier_paid"  # the escrow paid a supplier (payout or virtual card)
    FUNDING_EXPIRED = "funding_expired"  # pay-by missed: every paid share went back
    ATTRACTION_VOTED = "attraction_voted"  # a member wants to see an attraction
    ITINERARY_READY = "itinerary_ready"  # the day-by-day plan was (re)generated


def split_evenly(total_minor: int, members: int) -> list[int]:
    """Split an amount in minor units into `members` shares that sum EXACTLY to the total.

    The remainder (at most `members - 1` grosze) goes to the first shares, so nobody pays more
    than one grosz above anyone else and no money appears or disappears.
    """
    if members <= 0:
        raise ValueError("a split needs at least one member")
    if total_minor < 0:
        raise ValueError("a split needs a non-negative total")
    base, remainder = divmod(total_minor, members)
    return [base + 1 if index < remainder else base for index in range(members)]


def is_fully_paid(shares_minor: list[int], paid_minor: list[int]) -> bool:
    """Rule #1 of the product: booking may start only when every share is covered."""
    return len(shares_minor) == len(paid_minor) and all(
        paid >= share for share, paid in zip(shares_minor, paid_minor, strict=True)
    )
