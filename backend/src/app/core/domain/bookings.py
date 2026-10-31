"""Booking-side rules: which states may start an agent, how a disruption re-prices the trip and
how shares are re-split. Pure Python — no framework, no database."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.domain.trips import (
    AgentOutcome,
    BookingStatus,
    ContributionStatus,
    TripStatus,
    split_evenly,
)

# Run identifiers become directory names under `runs/` and URL path segments.
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# The trip must be fully paid (Rule #1) before the agent may buy anything.
TRIP_STATUSES_THAT_BUY: frozenset[TripStatus] = frozenset(
    {TripStatus.BOOKING, TripStatus.REBOOKING}
)
BOOKING_STATUSES_THAT_START: frozenset[BookingStatus] = frozenset(
    {BookingStatus.PENDING, BookingStatus.FAILED, BookingStatus.HANDOFF}
)


def is_valid_run_id(run_id: str) -> bool:
    return RUN_ID_PATTERN.fullmatch(run_id) is not None


def run_id_for(booking_id: str, attempt: int) -> str:
    return f"b{booking_id}-{attempt}"


def booking_status_after(outcome: AgentOutcome) -> BookingStatus:
    """Where a finished agent run leaves its booking."""
    if outcome is AgentOutcome.DONE:
        return BookingStatus.CONFIRMED
    if outcome is AgentOutcome.HANDOFF:
        return BookingStatus.HANDOFF
    return BookingStatus.FAILED


def all_confirmed(statuses: list[BookingStatus]) -> bool:
    """Every booking that still counts (not replaced) is bought — the trip is booked."""
    live = [status for status in statuses if status is not BookingStatus.CANCELLED]
    return bool(live) and all(status is BookingStatus.CONFIRMED for status in live)


def repriced_minor(amount_minor: int, price_change_percent: float) -> int:
    """`amount * (1 + pct/100)` rounded half-up to whole grosze, never negative."""
    factor = Decimal(1) + Decimal(str(price_change_percent)) / Decimal(100)
    value = (Decimal(amount_minor) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return max(int(value), 0)


def contribution_status(share_minor: int, paid_minor: int) -> ContributionStatus:
    if paid_minor > share_minor:
        return ContributionStatus.REFUND_DUE
    if paid_minor == share_minor:
        return ContributionStatus.PAID
    return ContributionStatus.PENDING


@dataclass(frozen=True, slots=True)
class ShareChange:
    previous_minor: int
    share_minor: int
    paid_minor: int
    status: ContributionStatus

    @property
    def delta_minor(self) -> int:
        return self.share_minor - self.previous_minor


def resplit(
    total_minor: int, previous_minor: list[int], paid_minor: list[int]
) -> list[ShareChange]:
    """New shares for a new total. They sum EXACTLY to the total (see `split_evenly`)."""
    shares = split_evenly(total_minor, len(previous_minor))
    return [
        ShareChange(
            previous_minor=previous,
            share_minor=share,
            paid_minor=paid,
            status=contribution_status(share, paid),
        )
        for previous, share, paid in zip(previous_minor, shares, paid_minor, strict=True)
    ]


def format_money(amount_minor: int, currency: str) -> str:
    """`124000, "PLN"` -> `"1 240.00 PLN"`. Signs are the caller's business."""
    whole, grosze = divmod(abs(amount_minor), 100)
    grouped = f"{whole:,}".replace(",", " ")
    sign = "-" if amount_minor < 0 else ""
    return f"{sign}{grouped}.{grosze:02d} {currency}"


def format_delta(amount_minor: int, currency: str) -> str:
    """`1200` -> `"+12.00 PLN"`, `-1200` -> `"-12.00 PLN"`."""
    return ("+" if amount_minor >= 0 else "") + format_money(amount_minor, currency)
