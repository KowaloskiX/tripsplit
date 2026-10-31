"""Package rules: per-person pricing, picking the winner and the agent's booking goal.

Pure Python — the services feed these with plain values, so every rule is testable without a
database.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime

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


def format_money(amount_minor: int, currency: str) -> str:
    """`123456, "PLN"` -> `"1234.56 PLN"` — for agent messages in the feed."""
    return f"{amount_minor // 100}.{amount_minor % 100:02d} {currency}"


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
) -> str:
    """The natural-language instruction the booking agent receives for one package item.

    `itinerary` describes transport segments ("LO 401 WAW -> BCN 2026-11-20 07:05"); without
    it a transport is taken as a return journey over the trip's dates.
    """
    extra = f" {details.strip()}" if details.strip() else ""
    match kind:
        case BookingKind.TRANSPORT:
            route = (
                itinerary.strip()
                or f"outbound on {date_from.isoformat()}, return on {date_to.isoformat()}"
            )
            body = f"Find and book {title} for {travellers} passengers: {route}."
        case BookingKind.STAY:
            body = (
                f"Find and book {title} for {travellers} guests, check-in "
                f"{date_from.isoformat()}, check-out {date_to.isoformat()}."
            )
        case BookingKind.ACTIVITY:
            day = starts_at.date() if starts_at is not None else date_from
            body = f"Find and book {title} for {travellers} people on {day.isoformat()}."
    return f"{body}{extra} {_STOP_BEFORE_PAY}"
