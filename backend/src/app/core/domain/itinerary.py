"""How a transport leg reads in text: one helper, one clock.

Suppliers build offer details from timezone-aware local datetimes, while a stored segment comes
back from Mongo in UTC. Formatting each with `%H:%M` as it stands gave the agent two different
times for the same train ("05:20" and "06:20-14:05"). Every leg description therefore goes
through `describe_leg`, which shows wall-clock time in `DISPLAY_ZONE` — the zone every trip
starts from — whatever zone the datetime arrived in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

DISPLAY_ZONE = ZoneInfo("Europe/Warsaw")


def local_time(moment: datetime) -> datetime:
    """An aware datetime as wall-clock time in `DISPLAY_ZONE`; a naive one is already local."""
    return moment.astimezone(DISPLAY_ZONE) if moment.tzinfo is not None else moment


def describe_leg(
    number: str, origin: str, destination: str, departs_at: datetime, arrives_at: datetime
) -> str:
    """`"EC 111 Warszawa → Praha 2026-11-30 06:20-14:05"` (local departure and arrival)."""
    departs, arrives = local_time(departs_at), local_time(arrives_at)
    return f"{number} {origin} → {destination} {departs:%Y-%m-%d %H:%M}-{arrives:%H:%M}"


@dataclass(frozen=True, slots=True)
class Leg:
    number: str
    origin: str
    destination: str
    departs_at: datetime
    arrives_at: datetime


def return_date_of(legs: Sequence[Leg]) -> date | None:
    """The local date the journey comes back, when the legs go out and back; else None."""
    if len(legs) < 2 or legs[-1].destination != legs[0].origin:
        return None
    back = local_time(legs[-1].departs_at).date()
    return back if back != local_time(legs[0].departs_at).date() else None


def describe_itinerary(legs: Sequence[Leg]) -> str:
    """Every leg, "; "-separated; a return journey labels its legs "outbound" / "return"."""
    back = return_date_of(legs)
    parts = []
    for leg in legs:
        text = describe_leg(leg.number, leg.origin, leg.destination, leg.departs_at, leg.arrives_at)
        if back is not None:
            is_back = local_time(leg.departs_at).date() >= back
            text = f"{'return' if is_back else 'outbound'} {text}"
        parts.append(text)
    return "; ".join(parts)
