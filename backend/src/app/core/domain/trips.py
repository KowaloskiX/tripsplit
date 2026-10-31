"""The trip domain: states, kinds and the money rule. Pure Python — no framework, no database.

This module is the contract shared by the "group & money" side (trips, proposals, votes,
contributions, events) and the "agent & booking" side (bookings, agent runs).
"""

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


class MemberRole(StrEnum):
    ORGANIZER = "organizer"
    MEMBER = "member"


class BookingKind(StrEnum):
    TRAIN = "train"
    STAY = "stay"
    ACTIVITY = "activity"


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
