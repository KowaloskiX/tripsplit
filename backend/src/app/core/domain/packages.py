"""Package rules: per-person pricing, picking the winner and the agent's booking goal.

Pure Python — the services feed these with plain values, so every rule is testable without a
database.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime

# One money style for every feed message, `1 234.56 PLN` (still importable from here).
from app.core.domain.bookings import format_money as format_money
from app.core.domain.trips import BookingKind

_STOP_BEFORE_PAY = "Stop at the summary before paying."


def per_person(total_minor: int, people: int) -> int:
    """The share shown on a package card: rounded UP, so the estimate never undersells."""
    if people <= 0:
        raise ValueError("a package needs at least one traveller")
    return -(-total_minor // people)


def is_over_budget(per_person_minor: int, budget_per_person_minor: int | None) -> bool:
    """A package costs more per person than the brief allows; no budget = never over."""
    return budget_per_person_minor is not None and per_person_minor > budget_per_person_minor


# The agent may accept a supplier total this close to what the group paid (rounding of
# per-passenger splits); PRICE_TOLERANCE_PERCENT widens it, never narrows it.
MIN_SUMMARY_TOLERANCE_PERCENT = 1.0


def expected_total_clause(amount_minor: int, currency: str, tolerance_percent: float) -> str:
    """The hard price fact for the agent's summary check (parsed by `app.agent.goal`)."""
    tolerance = max(tolerance_percent, MIN_SUMMARY_TOLERANCE_PERCENT)
    return (
        f"Expected total: {format_money(amount_minor, currency)} for this purchase "
        f"(tolerance {tolerance:g}%); a different supplier total is a handoff, not a purchase."
    )


def pick_winner[T](candidates: Sequence[T], votes: Sequence[T]) -> T:
    """The candidate with the most votes; a tie goes to the earliest candidate.

    `candidates` is in presentation order. Votes for something that is not a candidate (a
    proposal replaced by a new research round) are ignored.
    """
    if not candidates:
        raise ValueError("there is nothing to vote on")
    tally = Counter(vote for vote in votes if vote in candidates)
    # `max` returns the FIRST maximal element, which is exactly the tie-break we want.
    return max(candidates, key=lambda candidate: tally[candidate])


def booking_goal(
    *,
    kind: BookingKind,
    title: str,
    details: str,
    travellers: int,
    date_from: date,
    date_to: date,
    starts_at: datetime | None = None,
    itinerary: str = "",
    return_date: date | None = None,
) -> str:
    """The natural-language instruction the booking agent receives for one package item.

    `itinerary` describes transport segments (`itinerary.describe_itinerary`); without it a
    transport is taken as a return journey over the trip's dates. `return_date` marks a
    return journey bought as ONE order: the agent's summary check then requires both legs.
    """
    extra = f" {details.strip()}" if details.strip() else ""
    match kind:
        case BookingKind.TRANSPORT:
            route = (
                itinerary.strip()
                or f"outbound on {date_from.isoformat()}, return on {date_to.isoformat()}"
            )
            body = f"Find and book {title} for {travellers} passengers: {route}."
            if return_date is not None:
                body += (
                    f" Return date: {return_date.isoformat()} — buy the outbound and the return "
                    "leg together in one order."
                )
        case BookingKind.STAY:
            body = (
                f"Find and book {title} for {travellers} guests, check-in "
                f"{date_from.isoformat()}, check-out {date_to.isoformat()}."
            )
        case BookingKind.ACTIVITY:
            day = starts_at.date() if starts_at is not None else date_from
            body = f"Find and book {title} for {travellers} people on {day.isoformat()}."
    return f"{body}{extra} {_STOP_BEFORE_PAY}"
