"""Schedule sanity of a journey, as plain checks over its segments.

A journey is the segments of one package's transport (a return offer, or a one-way out plus a
one-way back). It is split into outbound and return at the longest gap — the stay. Places are
compared at city level: an airport code and a station name of the same city match (`WMI` and
`Warszawa Centralna` are both Warszawa), via the airport table of `app.suppliers.airports`.
"""

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.suppliers.airports import AIRPORTS
from app.suppliers.ports import Segment

MIN_FLIGHT_CONNECTION = timedelta(minutes=40)
MIN_RAIL_CONNECTION = timedelta(minutes=5)
MAX_CONNECTION = timedelta(hours=8)
MAX_DIRECTION = timedelta(hours=14)
# Leaving home (or the hotel) between midnight and this hour is a red-eye nobody asked for.
NIGHT_ENDS_HOUR = 5
_IATA = re.compile(r"^[A-Z]{3}$")
# Polish names of foreign cities that the airport table does not carry.
_EXONYMS: dict[str, str] = {
    "praga": "PRG",
    "wiedeń": "VIE",
    "wieden": "VIE",
    "budapeszt": "BUD",
    "rzym": "ROM",
    "lizbona": "LIS",
}
_COVERED: dict[str, str] = {
    airport: code for code, airports in AIRPORTS.values() for airport in airports
}


def place_key(place: str) -> str:
    """The city a place belongs to, as its airport search code; else the folded name."""
    raw = place.strip()
    if _IATA.fullmatch(raw):
        return _COVERED.get(raw, raw)
    # "Praga Gł./Praha hl.n." — PKP names foreign stations in Polish and the local language.
    for word in (word for word in re.split(r"[^\w]+", raw.casefold()) if word):
        code = AIRPORTS[word][0] if word in AIRPORTS else _EXONYMS.get(word)
        if code is not None:
            return code
    return raw.casefold()


def split_directions(segments: Sequence[Segment]) -> tuple[list[Segment], list[Segment]]:
    ordered = sorted(segments, key=lambda segment: segment.departs_at)
    if len(ordered) < 2:
        return ordered, []
    gaps = [
        (ordered[index + 1].departs_at - ordered[index].arrives_at, index)
        for index in range(len(ordered) - 1)
    ]
    _, cut = max(gaps)
    return ordered[: cut + 1], ordered[cut + 1 :]


def _connections_ok(direction: Sequence[Segment]) -> bool:
    for before, after in itertools.pairwise(direction):
        if place_key(before.destination) != place_key(after.origin):
            return False
        wait = after.departs_at - before.arrives_at
        minimum = (
            MIN_FLIGHT_CONNECTION if _IATA.fullmatch(after.origin.strip()) else MIN_RAIL_CONNECTION
        )
        if not minimum <= wait <= MAX_CONNECTION:
            return False
    return True


def _duration(direction: Sequence[Segment]) -> timedelta:
    return direction[-1].arrives_at - direction[0].departs_at if direction else timedelta(0)


@dataclass(frozen=True, slots=True)
class Journey:
    """What a check needs to know about the trip."""

    origin: str
    destination: str
    date_from: date
    date_to: date
    earliest_departure_hour: int | None = None


def schedule_checks(segments: Sequence[Segment], trip: Journey) -> dict[str, bool]:
    """Named pass/fail checks; every check is listed even when it fails trivially."""
    out, back = split_directions(segments)
    home, away = place_key(trip.origin), place_key(trip.destination)
    checks = {
        "both_directions": bool(out) and bool(back),
        "outbound_departs_on_day_one": bool(out) and out[0].departs_at.date() == trip.date_from,
        "arrives_before_check_in_day_ends": bool(out)
        and out[-1].arrives_at.date() == trip.date_from,
        "return_departs_on_checkout_day": bool(back) and back[0].departs_at.date() == trip.date_to,
        "connections_ok": _connections_ok(out) and _connections_ok(back),
        "places_consistent": bool(out)
        and bool(back)
        and place_key(out[0].origin) == home
        and place_key(out[-1].destination) == away
        and place_key(back[0].origin) == away
        and place_key(back[-1].destination) == home,
        "travel_time_reasonable": bool(out)
        and _duration(out) <= MAX_DIRECTION
        and _duration(back) <= MAX_DIRECTION,
    }
    checks["no_night_departure"] = all(
        direction[0].departs_at.hour >= NIGHT_ENDS_HOUR for direction in (out, back) if direction
    )
    if trip.earliest_departure_hour is not None:
        hour = trip.earliest_departure_hour
        checks["no_departure_before_preferred_hour"] = all(
            direction[0].departs_at.hour >= hour for direction in (out, back) if direction
        )
    return checks


def travel_hours(segments: Sequence[Segment]) -> float:
    out, back = split_directions(segments)
    return round((_duration(out) + _duration(back)).total_seconds() / 3600, 1)


def schedule_ok(segments: Sequence[Segment], trip: Journey) -> bool:
    return all(schedule_checks(segments, trip).values())
