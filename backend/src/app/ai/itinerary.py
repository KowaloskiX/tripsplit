"""Whether a package's transport fits the trip's calendar — pure rules over segments.

The research prefers transport that gets the group there on the first day and home on the
last, without a day spent travelling and without departing earlier than the brief allows.
Segments are split into the way there and the way back at the longest gap (the stay).
"""

from collections.abc import Sequence
from datetime import date, timedelta

from app.suppliers.ports import Segment

# One direction longer than this is a lost day, not a journey (a 22 h flight via three hubs).
MAX_DIRECTION = timedelta(hours=14)
# Without a preference, no departure between midnight and 05:00 (a red-eye nobody asked for).
DEFAULT_EARLIEST_HOUR = 5


def directions(segments: Sequence[Segment]) -> tuple[list[Segment], list[Segment]]:
    ordered = sorted(segments, key=lambda segment: segment.departs_at)
    if len(ordered) < 2:
        return ordered, []
    gaps = [
        (ordered[index + 1].departs_at - ordered[index].arrives_at, index)
        for index in range(len(ordered) - 1)
    ]
    _, cut = max(gaps)
    return ordered[: cut + 1], ordered[cut + 1 :]


def travel_time(segments: Sequence[Segment]) -> timedelta:
    out, back = directions(segments)
    return sum(
        (legs[-1].arrives_at - legs[0].departs_at for legs in (out, back) if legs), timedelta(0)
    )


def leg_fits(
    segments: Sequence[Segment],
    day: date,
    earliest_departure_hour: int | None = None,
    *,
    arrive_same_day: bool,
) -> bool:
    """One direction: leaves on `day` (and arrives that day when it must — the way there
    ends at a hotel), within `MAX_DIRECTION`, not before the preferred hour
    (`DEFAULT_EARLIEST_HOUR` without one). No segments = unknown = fits."""
    if not segments:
        return True
    first, last = segments[0], segments[-1]
    hour = DEFAULT_EARLIEST_HOUR if earliest_departure_hour is None else earliest_departure_hour
    return (
        first.departs_at.date() == day
        and (not arrive_same_day or last.arrives_at.date() == day)
        and last.arrives_at - first.departs_at <= MAX_DIRECTION
        and first.departs_at.hour >= hour
    )


def fits_calendar(
    segments: Sequence[Segment],
    date_from: date,
    date_to: date,
    earliest_departure_hour: int | None = None,
) -> bool:
    """There on the first day (arriving that day), back on the last day — each direction
    `leg_fits`. No segments = unknown = fits."""
    if not segments:
        return True
    out, back = directions(segments)
    return (
        bool(out)
        and bool(back)
        and leg_fits(out, date_from, earliest_departure_hour, arrive_same_day=True)
        and leg_fits(back, date_to, earliest_departure_hour, arrive_same_day=False)
    )
