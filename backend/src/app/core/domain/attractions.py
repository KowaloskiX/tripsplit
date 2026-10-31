"""Attractions the group can vote on at the destination — pure rules, no framework.

Any activity supplier can propose attractions (a ticket shop, an open-data catalogue of sights).
Their offers carry adapter-owned `supplier_data` whose keys differ per supplier, so everything
here reads loosely typed values defensively and falls back to sensible defaults: a kind guessed
from the title, opening hours of 10:00-18:00, a visit length by kind.
"""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from typing import Any


class AttractionKind(StrEnum):
    MUSEUM = "museum"
    LANDMARK = "landmark"
    VIEWPOINT = "viewpoint"
    FOOD = "food"
    EXPERIENCE = "experience"


# How long a visit takes, by kind (minutes) — the itinerary's default when a supplier is silent.
VISIT_MINUTES: dict[AttractionKind, int] = {
    AttractionKind.MUSEUM: 150,
    AttractionKind.LANDMARK: 90,
    AttractionKind.VIEWPOINT: 60,
    AttractionKind.FOOD: 90,
    AttractionKind.EXPERIENCE: 120,
}
MIN_VISIT_MINUTES = 30
MAX_VISIT_MINUTES = 240

_KIND_WORDS: tuple[tuple[AttractionKind, str], ...] = (
    (AttractionKind.MUSEUM, r"museum|muzeum|museo|gallery|galerie|galeria|exhibit|collection"),
    (AttractionKind.VIEWPOINT, r"view|lookout|tower|hill|panorama|observation|park güell|bunkers"),
    (AttractionKind.FOOD, r"market|food|tapas|tasting|beer|wine|brewery|café|cafe|bar\b|halle"),
    (
        AttractionKind.EXPERIENCE,
        r"tour|cruise|bath|spa|show|concert|workshop|class|crawl|escape|night|experience",
    ),
)


@dataclass(frozen=True, slots=True)
class OpeningHours:
    opens: time
    closes: time

    def __post_init__(self) -> None:
        if self.closes <= self.opens:
            raise ValueError("an attraction must close after it opens")


DEFAULT_HOURS = OpeningHours(time(10), time(18))
_HOURS = re.compile(r"([0-2]?\d)[:.]([0-5]\d)\s*[-\u2013]\s*([0-2]?\d)[:.]([0-5]\d)")


def parse_hours(raw: object) -> OpeningHours | None:
    """ "09:00-17:30", {"open": "09:00", "close": "17:30"} or {"opens": ..., "closes": ...};
    None when unknown or unreadable (24/7, per-weekday prose, nonsense)."""
    if isinstance(raw, Mapping):
        opens = raw.get("open") or raw.get("opens")
        closes = raw.get("close") or raw.get("closes")
        if isinstance(opens, str) and isinstance(closes, str):
            return parse_hours(f"{opens}-{closes}")
        return None
    if not isinstance(raw, str) or (m := _HOURS.search(raw)) is None:
        return None
    hour_a, minute_a, hour_b, minute_b = (int(part) for part in m.groups())
    if hour_a > 23 or hour_b > 23:
        return None
    try:
        return OpeningHours(time(hour_a, minute_a), time(hour_b, minute_b))
    except ValueError:
        return None


def kind_of(raw: object, title: str) -> AttractionKind:
    """The supplier's kind when it is one of ours, else guessed from the title."""
    if isinstance(raw, str):
        try:
            return AttractionKind(raw.strip().lower())
        except ValueError:
            pass
    for kind, pattern in _KIND_WORDS:
        if re.search(pattern, title, re.IGNORECASE):
            return kind
    return AttractionKind.LANDMARK


def visit_minutes(raw: object, kind: AttractionKind) -> int:
    value = whole(raw)
    if value is None:
        return VISIT_MINUTES[kind]
    return min(max(value, MIN_VISIT_MINUTES), MAX_VISIT_MINUTES)


def whole(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and math.isfinite(raw):
        return round(raw)
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def coordinate(raw: object, limit: float) -> float | None:
    """A latitude (limit 90) or longitude (limit 180), or None."""
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw) if isinstance(raw, int | float | str) else None
    except ValueError:
        return None
    if value is None or not math.isfinite(value) or abs(value) > limit:
        return None
    return value


def first_of(data: Mapping[str, Any], *keys: str) -> object:
    """The first present, non-empty value among `keys` (suppliers name things differently)."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def text_of(data: Mapping[str, Any], *keys: str, limit: int = 2000) -> str:
    value = first_of(data, *keys)
    return value.strip()[:limit] if isinstance(value, str) else ""


def http_url(raw: str) -> str:
    """Only absolute http(s) links reach the UI."""
    return raw if raw.startswith(("https://", "http://")) else ""


@dataclass(frozen=True, slots=True)
class Tally:
    """An attraction with its votes, as `select_for_plan` ranks them."""

    attraction_id: str
    votes: int
    rank: int  # supplier order: lower = better


def select_for_plan(tallies: Sequence[Tally], members: int, capacity: int) -> list[str]:
    """Which attractions go into the plan, best first.

    Everything at least half of the group wants is in; when that leaves room (`capacity` =
    days x max per day), the next most-voted ones with at least one vote fill it. Nothing
    nobody voted for is planned — an empty vote gives a plan of travel, meals and free time.
    """
    if members <= 0 or capacity <= 0:
        return []
    ordered = sorted(
        (tally for tally in tallies if tally.votes > 0),
        key=lambda tally: (-tally.votes, tally.rank, tally.attraction_id),
    )
    majority = [tally for tally in ordered if tally.votes * 2 >= members]
    rest = [tally for tally in ordered if tally.votes * 2 < members]
    return [tally.attraction_id for tally in (majority + rest)[:capacity]]


class TicketStatus(StrEnum):
    """Where the group's tickets for a planned visit stand, for the itinerary."""

    TO_BUY = "to_buy"  # queued: bought with everything else once every share is paid
    BUYING = "buying"  # the agent is on the ticket shop / the summary awaits approval
    BOOKED = "booked"  # confirmed by the ticket shop
    NEEDS_HELP = "needs_help"  # the agent handed over (or failed): a human finishes


def ticket_goal(
    *, title: str, day: str, slot: str, tickets: int, budget: str, part: str = ""
) -> str:
    """The booking agent's instruction for one ticket purchase. `day` is ISO, `slot` HH:MM;
    `budget` is the expected total ("420.00 PLN") the summary is checked against."""
    extra = f" {part.strip()}" if part.strip() else ""
    return (
        f"Buy {tickets} timed-entry tickets for {title} on {day}, entry at {slot}, "
        f"for {tickets} visitors.{extra} Budget: {budget}. Stop at the summary before paying."
    )
