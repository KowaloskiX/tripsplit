"""The day-by-day plan: voted attractions scheduled around the transport — deterministic, no LLM.

Rules, in order of precedence:

- **Transport bounds the trip.** Day one starts after the arrival (plus getting to the hotel);
  the last day ends before the departure (minus getting to the station or airport). A day
  without room for anything gets travel and free time only.
- **Fixed events stay where they are**: a slot somebody already holds tickets for is never
  moved; everything else is planned around it.
- **Opening hours** when the supplier knows them, else 10:00-18:00. A visit must fit inside.
- **A visit lasts** what the supplier says, else 1-2.5 h by kind (see `attractions`).
- **Getting around** from straight-line distance: walking at 5 km/h under 2 km, otherwise
  transit at 25 km/h plus 10 minutes of waiting and walking.
- **Lunch and dinner** get a slot each when the day covers them.
- **At most `max_per_day` attractions a day**, picked greedily by nearest neighbour from the
  hotel (or the city centre), so nearby sights cluster into the same day.
- Starts are rounded up to a quarter of an hour; a ticketed visit to the half hour (ticket
  shops sell half-hourly entry slots).

Times are local wall-clock times at the destination (naive datetimes).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from app.core.domain.attractions import DEFAULT_HOURS, OpeningHours

WALKING_KMH = 5.0
TRANSIT_KMH = 25.0
TRANSIT_OVERHEAD = timedelta(minutes=10)
WALKING_LIMIT_KM = 2.0
UNKNOWN_TRAVEL = timedelta(minutes=15)
MIN_TRAVEL_ITEM = timedelta(minutes=5)
DAY_START = time(9, 30)
DAY_END = time(22, 0)
AFTER_ARRIVAL = timedelta(minutes=45)  # to the hotel, bags dropped
BEFORE_DEPARTURE = timedelta(minutes=90)  # to the station / airport, with a margin
LUNCH = (time(12, 0), time(14, 0), timedelta(minutes=60))  # earliest, latest start, length
DINNER = (time(19, 0), time(20, 30), timedelta(minutes=90))
FREE_TIME_MIN = timedelta(minutes=90)
MAX_PER_DAY = 4
QUARTER = 15
TICKET_SLOT = 30


class ItemKind(StrEnum):
    TRAVEL = "travel"
    ATTRACTION = "attraction"
    MEAL = "meal"
    FREE = "free"


@dataclass(frozen=True, slots=True)
class Point:
    lat: float
    lon: float


def distance_km(a: Point, b: Point) -> float:
    """Great-circle distance (haversine)."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def travel_time(a: Point | None, b: Point | None) -> timedelta:
    if a is None or b is None:
        return UNKNOWN_TRAVEL
    km = distance_km(a, b)
    if km < WALKING_LIMIT_KM:
        return timedelta(minutes=math.ceil(km / WALKING_KMH * 60))
    return timedelta(minutes=math.ceil(km / TRANSIT_KMH * 60)) + TRANSIT_OVERHEAD


def travel_label(a: Point | None, b: Point | None) -> str:
    if a is None or b is None:
        return "Getting there"
    return "Walk" if distance_km(a, b) < WALKING_LIMIT_KM else "Public transport"


@dataclass(frozen=True, slots=True)
class PlannedAttraction:
    """An attraction to schedule. `fixed_at` = tickets are held for that moment: keep it."""

    id: str
    title: str
    point: Point | None
    minutes: int
    hours: OpeningHours | None = None
    ticketed: bool = False
    link: str = ""
    place: str = ""
    fixed_at: datetime | None = None
    # A food market or a beer garden: a visit over lunch or dinner time IS the meal.
    is_meal: bool = False


@dataclass(frozen=True, slots=True)
class TransportLeg:
    """One direction of the transport: there (arrives on day one) or back (on the last day)."""

    title: str
    departs_at: datetime
    arrives_at: datetime
    origin: str = ""
    destination: str = ""


@dataclass(frozen=True, slots=True)
class TripFrame:
    first_day: date
    last_day: date
    there: TransportLeg | None = None
    back: TransportLeg | None = None
    base: Point | None = None  # the hotel, else the centre
    base_name: str = "the hotel"
    max_per_day: int = MAX_PER_DAY

    @property
    def days(self) -> list[date]:
        count = (self.last_day - self.first_day).days + 1
        return [self.first_day + timedelta(days=offset) for offset in range(max(count, 1))]


@dataclass(frozen=True, slots=True)
class PlanItem:
    start: datetime
    end: datetime
    kind: ItemKind
    title: str
    place: str = ""
    point: Point | None = None
    link: str = ""
    note: str = ""
    attraction_id: str | None = None


@dataclass(slots=True)
class PlanDay:
    day: date
    items: list[PlanItem] = field(default_factory=list)


def round_up(moment: datetime, minutes: int) -> datetime:
    excess = (moment.minute % minutes) * 60 + moment.second
    if excess == 0 and moment.microsecond == 0:
        return moment
    return moment.replace(second=0, microsecond=0) + timedelta(minutes=minutes - excess // 60)


def _at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock)


@dataclass(slots=True)
class _Cursor:
    """Where the group is and when, while one day is being filled."""

    now: datetime
    end: datetime
    at: Point | None
    place: str
    items: list[PlanItem]
    lunch_done: bool
    dinner_done: bool
    visits: int = 0


def _window(frame: TripFrame, day: date) -> tuple[datetime, datetime]:
    start, end = _at(day, DAY_START), _at(day, DAY_END)
    if frame.there is not None and frame.there.arrives_at.date() == day:
        start = max(start, frame.there.arrives_at + AFTER_ARRIVAL)
    if frame.back is not None and frame.back.departs_at.date() == day:
        end = min(end, frame.back.departs_at - BEFORE_DEPARTURE)
    return start, end


def _covers(start: datetime, end: datetime, meal: tuple[time, time, timedelta]) -> bool:
    """The day's window leaves room for this meal at all."""
    earliest = max(start, _at(start.date(), meal[0]))
    return earliest <= _at(start.date(), meal[1]) and earliest + meal[2] <= end


def _meal_deadline(cursor: _Cursor, meal: tuple[time, time, timedelta]) -> datetime:
    """The latest moment a visit may end and still leave the meal its slot."""
    return min(_at(cursor.now.date(), meal[1]), cursor.end - meal[2])


def _visit_start(cursor: _Cursor, attraction: PlannedAttraction) -> tuple[datetime, timedelta]:
    hop = travel_time(cursor.at, attraction.point)
    hours = attraction.hours or DEFAULT_HOURS
    start = max(cursor.now + hop, _at(cursor.now.date(), hours.opens))
    return round_up(start, TICKET_SLOT if attraction.ticketed else QUARTER), hop


def _fits(
    cursor: _Cursor,
    attraction: PlannedAttraction,
    deadline: datetime,
) -> tuple[datetime, timedelta] | None:
    start, hop = _visit_start(cursor, attraction)
    end = start + timedelta(minutes=attraction.minutes)
    hours = attraction.hours or DEFAULT_HOURS
    if end > _at(cursor.now.date(), hours.closes) or end > deadline:
        return None
    # A visit that only starts after a long wait is not "next" — something else should be.
    if start - (cursor.now + hop) > timedelta(hours=2):
        return None
    return start, hop


def _add_travel(cursor: _Cursor, to: Point | None, place: str, arrive_by: datetime) -> None:
    hop = travel_time(cursor.at, to)
    if hop >= MIN_TRAVEL_ITEM and cursor.at is not None and to is not None:
        cursor.items.append(
            PlanItem(
                start=arrive_by - hop,
                end=arrive_by,
                kind=ItemKind.TRAVEL,
                title=f"{travel_label(cursor.at, to)} to {place}",
                place=place,
                point=to,
                note=f"{distance_km(cursor.at, to):.1f} km",
            )
        )


def _add_free(cursor: _Cursor, until: datetime) -> None:
    if until - cursor.now >= FREE_TIME_MIN:
        cursor.items.append(
            PlanItem(
                start=cursor.now,
                end=until,
                kind=ItemKind.FREE,
                title="Free time",
                place=cursor.place,
                point=cursor.at,
                note="Wander, rest, shop — nothing planned.",
            )
        )


def _visit(cursor: _Cursor, attraction: PlannedAttraction, start: datetime) -> None:
    _add_free(cursor, start - travel_time(cursor.at, attraction.point))
    _add_travel(cursor, attraction.point, attraction.title, start)
    end = start + timedelta(minutes=attraction.minutes)
    hours = attraction.hours or DEFAULT_HOURS
    cursor.items.append(
        PlanItem(
            start=start,
            end=end,
            kind=ItemKind.ATTRACTION,
            title=attraction.title,
            place=attraction.place or attraction.title,
            point=attraction.point,
            link=attraction.link,
            note=f"Open {hours.opens:%H:%M}-{hours.closes:%H:%M}",
            attraction_id=attraction.id,
        )
    )
    # A held slot is never moved, even when it overlaps: time only moves forward.
    cursor.now, cursor.at, cursor.place = max(cursor.now, end), attraction.point, attraction.title
    cursor.visits += 1
    if attraction.is_meal:
        day = start.date()
        if start < _at(day, LUNCH[1]) + LUNCH[2] and end > _at(day, LUNCH[0]):
            cursor.lunch_done = True
        elif start < _at(day, DINNER[1]) + DINNER[2] and end > _at(day, DINNER[0]):
            cursor.dinner_done = True


def _meal(cursor: _Cursor, meal: tuple[time, time, timedelta], title: str) -> bool:
    start = round_up(max(cursor.now, _at(cursor.now.date(), meal[0])), QUARTER)
    if start > _at(cursor.now.date(), meal[1]) or start + meal[2] > cursor.end:
        return False
    _add_free(cursor, start)
    where = f"near {cursor.place}" if cursor.place else ""
    cursor.items.append(
        PlanItem(
            start=start,
            end=start + meal[2],
            kind=ItemKind.MEAL,
            title=title,
            place=where,
            point=cursor.at,
            note="Somewhere close by — no booking needed.",
        )
    )
    cursor.now = start + meal[2]
    return True


def _deadline(cursor: _Cursor, fixed: list[PlannedAttraction]) -> datetime:
    """The latest a flexible visit may end: before the next meal, the next fixed slot (with
    the way there) and the end of the day."""
    limits = [cursor.end]
    if not cursor.lunch_done:
        limits.append(_meal_deadline(cursor, LUNCH))
    if not cursor.dinner_done:
        limits.append(_meal_deadline(cursor, DINNER))
    if fixed and fixed[0].fixed_at is not None:
        limits.append(fixed[0].fixed_at - travel_time(cursor.at, fixed[0].point))
    return min(limits)


def _fixed_due(cursor: _Cursor, fixed: list[PlannedAttraction], before: timedelta) -> bool:
    """Spending `before` now would make the group late for the next held slot."""
    if not fixed or fixed[0].fixed_at is None:
        return False
    return cursor.now + before > fixed[0].fixed_at - travel_time(cursor.at, fixed[0].point)


def _visit_fixed(cursor: _Cursor, fixed: list[PlannedAttraction]) -> None:
    pinned = fixed.pop(0)
    _visit(cursor, pinned, pinned.fixed_at or cursor.now)


def _fill_day(
    frame: TripFrame,
    day: date,
    pool: list[PlannedAttraction],
    fixed: list[PlannedAttraction],
) -> PlanDay:
    plan = PlanDay(day)
    start, end = _window(frame, day)
    if frame.there is not None and frame.there.arrives_at.date() == day:
        leg = frame.there
        plan.items.append(_leg_item(leg, f"Arrive in {leg.destination}".strip()))
        plan.items.append(
            PlanItem(
                start=leg.arrives_at,
                end=leg.arrives_at + AFTER_ARRIVAL,
                kind=ItemKind.TRAVEL,
                title=f"To {frame.base_name}, drop the bags",
                place=frame.base_name,
                point=frame.base,
            )
        )
    cursor = _Cursor(
        now=start,
        end=end,
        at=frame.base,
        place=frame.base_name,
        items=plan.items,
        lunch_done=not _covers(start, end, LUNCH),
        dinner_done=not _covers(start, end, DINNER),
    )
    fixed = sorted(fixed, key=lambda a: a.fixed_at or datetime.max)
    while start < end:
        meal_now = [
            (meal, title)
            for meal, title, done in (
                (LUNCH, "Lunch", cursor.lunch_done),
                (DINNER, "Dinner", cursor.dinner_done),
            )
            if not done and cursor.now >= _at(day, meal[0])
        ]
        if meal_now:
            meal, title = meal_now[0]
            if _fixed_due(cursor, fixed, meal[2]):
                _visit_fixed(cursor, fixed)
                continue
            _meal(cursor, meal, title)
            if meal is LUNCH:
                cursor.lunch_done = True
            else:
                cursor.dinner_done = True
            continue
        deadline = _deadline(cursor, fixed)
        options = []
        if cursor.visits + len(fixed) < frame.max_per_day:
            for attraction in pool:
                fit = _fits(cursor, attraction, deadline)
                if fit is not None:
                    options.append((fit[1], fit[0], attraction))
        if options:
            _, visit_at, chosen = min(options, key=lambda option: (option[0], option[1]))
            pool.remove(chosen)
            _visit(cursor, chosen, visit_at)
            continue
        # Nothing fits before the next meal or held slot: move on to whichever comes first.
        meals = [
            (_at(day, meal[0]), meal)
            for meal, done in ((LUNCH, cursor.lunch_done), (DINNER, cursor.dinner_done))
            if not done
        ]
        next_meal = min(meals, key=lambda pair: pair[0]) if meals else None
        if next_meal is not None and not _fixed_due(
            _Cursor(next_meal[0], end, cursor.at, cursor.place, [], True, True),
            fixed,
            next_meal[1][2],
        ):
            _add_free(cursor, next_meal[0])
            cursor.now = max(cursor.now, next_meal[0])
            continue
        if fixed:
            _visit_fixed(cursor, fixed)
            continue
        break
    if cursor.now < _at(day, DINNER[0]):  # the evening after dinner is free anyway
        _add_free(cursor, end)
    if frame.back is not None and frame.back.departs_at.date() == day:
        leg = frame.back
        plan.items.append(
            PlanItem(
                start=leg.departs_at - BEFORE_DEPARTURE,
                end=leg.departs_at,
                kind=ItemKind.TRAVEL,
                title=f"Pick up the bags, to {leg.origin or 'the station'}".strip(),
                place=leg.origin,
            )
        )
        plan.items.append(_leg_item(leg, f"Head home from {leg.origin}".strip()))
    plan.items.sort(key=lambda item: (item.start, item.end))
    return plan


def _leg_item(leg: TransportLeg, title: str) -> PlanItem:
    return PlanItem(
        start=leg.departs_at,
        end=leg.arrives_at,
        kind=ItemKind.TRAVEL,
        title=title,
        place=f"{leg.origin} → {leg.destination}".strip(" →"),
        note=leg.title,
    )


def build_plan(frame: TripFrame, attractions: Sequence[PlannedAttraction]) -> list[PlanDay]:
    """Every trip day with its items, in time order. `attractions` best first; fixed ones
    are kept on their day and time, the rest fill the days greedily."""
    pool = [a for a in attractions if a.fixed_at is None]
    fixed_by_day: dict[date, list[PlannedAttraction]] = {}
    for attraction in attractions:
        if attraction.fixed_at is not None:
            fixed_by_day.setdefault(attraction.fixed_at.date(), []).append(attraction)
    days = frame.days
    plans = [_fill_day(frame, day, pool, fixed_by_day.pop(day, [])) for day in days]
    # A fixed slot outside the trip's days is still the group's ticket — show it on the
    # nearest day rather than dropping it.
    for day, fixed in fixed_by_day.items():
        nearest = min(plans, key=lambda plan: abs((plan.day - day).days))
        for pinned in fixed:
            at = pinned.fixed_at or _at(day, DAY_START)
            nearest.items.append(
                PlanItem(
                    start=at,
                    end=at + timedelta(minutes=pinned.minutes),
                    kind=ItemKind.ATTRACTION,
                    title=pinned.title,
                    place=pinned.place or pinned.title,
                    point=pinned.point,
                    link=pinned.link,
                    attraction_id=pinned.id,
                )
            )
        nearest.items.sort(key=lambda item: (item.start, item.end))
    return plans


def capacity(frame: TripFrame) -> int:
    return len(frame.days) * frame.max_per_day
