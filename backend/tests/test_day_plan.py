"""The day plan's scheduling rules and the attraction readers — pure, no database."""

from datetime import date, datetime, time, timedelta
from itertools import pairwise

import pytest

from app.core.domain.attractions import (
    AttractionKind,
    OpeningHours,
    Tally,
    coordinate,
    kind_of,
    parse_hours,
    select_for_plan,
    visit_minutes,
)
from app.core.domain.day_plan import (
    ItemKind,
    PlanDay,
    PlannedAttraction,
    Point,
    TransportLeg,
    TripFrame,
    build_plan,
    distance_km,
    round_up,
    travel_time,
)

FRI, SAT, SUN = date(2026, 11, 20), date(2026, 11, 21), date(2026, 11, 22)
CENTRE = Point(50.0870, 14.4208)  # Old Town Square, Prague


def at(day: date, clock: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock))


def near(km_north: float) -> Point:
    """A point `km_north` km north of the centre (1 degree of latitude ~ 111 km)."""
    return Point(CENTRE.lat + km_north / 111.2, CENTRE.lon)


def attraction(
    ident: str,
    *,
    km: float = 0.5,
    minutes: int = 90,
    hours: OpeningHours | None = None,
    fixed_at: datetime | None = None,
    ticketed: bool = False,
) -> PlannedAttraction:
    return PlannedAttraction(
        id=ident,
        title=ident.title(),
        point=near(km),
        minutes=minutes,
        hours=hours,
        fixed_at=fixed_at,
        ticketed=ticketed,
    )


THERE = TransportLeg("EC 131", at(FRI, "07:52"), at(FRI, "13:52"), "Warszawa", "Praha")
BACK = TransportLeg("EC 117", at(SUN, "15:08"), at(SUN, "21:00"), "Praha", "Warszawa")
FRAME = TripFrame(FRI, SUN, there=THERE, back=BACK, base=CENTRE, base_name="Hostel")


def visits(day: PlanDay) -> list[str]:
    return [item.attraction_id or "" for item in day.items if item.kind is ItemKind.ATTRACTION]


def all_visits(plan: list[PlanDay]) -> list[str]:
    return [ident for day in plan for ident in visits(day)]


def assert_no_overlap(day: PlanDay) -> None:
    timed = sorted(day.items, key=lambda item: item.start)
    for first, second in pairwise(timed):
        assert first.end <= second.start, f"{first.title} overlaps {second.title}"


# ---- travel ---------------------------------------------------------------------------------


def test_walking_under_two_km_transit_above() -> None:
    assert distance_km(CENTRE, near(1.0)) == pytest.approx(1.0, rel=0.01)
    assert travel_time(CENTRE, near(1.0)) == timedelta(minutes=12)  # 1 km at 5 km/h
    # 5 km at 25 km/h = 12 min, plus 10 min of waiting and walking.
    assert travel_time(CENTRE, near(5.0)) == timedelta(minutes=22)
    assert travel_time(None, CENTRE) == timedelta(minutes=15)


def test_round_up_to_a_slot() -> None:
    assert round_up(at(SAT, "10:01"), 15) == at(SAT, "10:15")
    assert round_up(at(SAT, "10:30"), 30) == at(SAT, "10:30")
    assert round_up(at(SAT, "10:31"), 30) == at(SAT, "11:00")


# ---- transport bounds -----------------------------------------------------------------------


def test_nothing_before_the_arrival_or_after_the_departure() -> None:
    plan = build_plan(FRAME, [attraction(f"a{i}") for i in range(8)])
    friday, sunday = plan[0], plan[-1]
    arrival = next(i for i in friday.items if i.kind is ItemKind.TRAVEL)
    assert arrival.start == THERE.departs_at and arrival.end == THERE.arrives_at
    for item in friday.items:
        if item.kind is ItemKind.ATTRACTION:
            assert item.start >= THERE.arrives_at + timedelta(minutes=45)
    for item in sunday.items:
        if item.kind in (ItemKind.ATTRACTION, ItemKind.MEAL):
            assert item.end <= BACK.departs_at - timedelta(minutes=90)
    assert sunday.items[-1].kind is ItemKind.TRAVEL and sunday.items[-1].start == BACK.departs_at


def test_a_day_without_room_gets_travel_only() -> None:
    late = TransportLeg("EN 407", at(FRI, "13:00"), at(FRI, "22:30"), "Warszawa", "Praha")
    plan = build_plan(TripFrame(FRI, SAT, there=late, base=CENTRE), [attraction("a")])
    assert visits(plan[0]) == []
    assert {item.kind for item in plan[0].items} == {ItemKind.TRAVEL}
    assert visits(plan[1]) == ["a"]


def test_no_transport_means_full_days() -> None:
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [attraction("a", hours=None)])
    (day,) = plan
    assert visits(day) == ["a"]
    first = next(i for i in day.items if i.kind is ItemKind.ATTRACTION)
    assert first.start == at(SAT, "10:00")  # the default opening, not before


# ---- opening hours, meals, limits ------------------------------------------------------------


def test_opening_hours_are_respected() -> None:
    evening = attraction("tower", hours=OpeningHours(time(17), time(22)), minutes=60)
    morning = attraction("museum", hours=OpeningHours(time(9, 30), time(12)), minutes=120)
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [evening, morning])
    items = {i.attraction_id: i for i in plan[0].items if i.kind is ItemKind.ATTRACTION}
    assert items["museum"].start >= at(SAT, "09:30") and items["museum"].end <= at(SAT, "12:00")
    assert items["tower"].start >= at(SAT, "17:00") and items["tower"].end <= at(SAT, "22:00")


def test_a_visit_that_cannot_fit_its_hours_is_left_out() -> None:
    short = attraction("chapel", hours=OpeningHours(time(10), time(11)), minutes=120)
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [short])
    assert all_visits(plan) == []


def test_lunch_and_dinner_get_a_slot() -> None:
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [attraction(f"a{i}") for i in range(4)])
    (day,) = plan
    meals = [i for i in day.items if i.kind is ItemKind.MEAL]
    assert [m.title for m in meals] == ["Lunch", "Dinner"]
    lunch, dinner = meals
    assert at(SAT, "12:00") <= lunch.start <= at(SAT, "14:00")
    assert at(SAT, "19:00") <= dinner.start <= at(SAT, "20:30")
    assert_no_overlap(day)


def test_at_most_four_attractions_a_day() -> None:
    many = [attraction(f"a{i:02d}", minutes=45, km=0.1 * i) for i in range(12)]
    plan = build_plan(TripFrame(SAT, SUN, base=CENTRE), many)
    assert all(len(visits(day)) <= 4 for day in plan)
    assert len(all_visits(plan)) == 8


def test_items_never_overlap() -> None:
    plan = build_plan(FRAME, [attraction(f"a{i}", km=i * 0.7) for i in range(10)])
    for day in plan:
        assert_no_overlap(day)


# ---- clustering -----------------------------------------------------------------------------


def test_nearby_attractions_cluster_on_the_same_day() -> None:
    west = [
        PlannedAttraction(f"w{i}", f"W{i}", Point(CENTRE.lat, CENTRE.lon - 0.10 - i * 0.004), 90)
        for i in range(3)
    ]
    east = [
        PlannedAttraction(f"e{i}", f"E{i}", Point(CENTRE.lat, CENTRE.lon + 0.10 + i * 0.004), 90)
        for i in range(3)
    ]
    # Interleaved and best-first: clustering must come from the nearest-neighbour walk.
    ordered = [west[0], east[0], west[1], east[1], west[2], east[2]]
    frame = TripFrame(SAT, SUN, base=CENTRE, max_per_day=3)
    saturday, sunday = build_plan(frame, ordered)
    groups = [{ident[0] for ident in visits(saturday)}, {ident[0] for ident in visits(sunday)}]
    assert all(len(group) == 1 for group in groups), groups
    assert groups[0] != groups[1]


def test_travel_items_between_far_places() -> None:
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [attraction("far", km=4.0)])
    travel = [i for i in plan[0].items if i.kind is ItemKind.TRAVEL]
    assert travel and travel[0].title.startswith("Public transport")
    assert travel[0].end == next(i for i in plan[0].items if i.attraction_id == "far").start


# ---- tickets ------------------------------------------------------------------------------


def test_ticketed_visits_start_on_the_half_hour() -> None:
    plan = build_plan(
        TripFrame(SAT, SAT, base=near(0.9)),
        [attraction("museum", km=0.0, ticketed=True)],
    )
    visit = next(i for i in plan[0].items if i.kind is ItemKind.ATTRACTION)
    assert visit.start.minute in (0, 30)


def test_a_held_slot_is_never_moved() -> None:
    held = attraction("vasa", fixed_at=at(SAT, "15:00"), minutes=120, ticketed=True)
    others = [attraction(f"a{i}", km=0.3 * i) for i in range(5)]
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [*others, held])
    (day,) = plan
    item = next(i for i in day.items if i.attraction_id == "vasa")
    assert item.start == at(SAT, "15:00") and item.end == at(SAT, "17:00")
    assert len(visits(day)) <= 4
    assert_no_overlap(day)


def test_a_held_slot_on_a_day_outside_the_trip_still_shows() -> None:
    held = attraction("vasa", fixed_at=at(date(2026, 11, 25), "11:00"))
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [held])
    assert all_visits(plan) == ["vasa"]


# ---- selection and readers -----------------------------------------------------------------


def test_majority_first_then_most_voted_up_to_capacity() -> None:
    tallies = [
        Tally("few", 1, 0),
        Tally("half", 3, 5),
        Tally("most", 5, 9),
        Tally("none", 0, 1),
        Tally("two", 2, 2),
    ]
    assert select_for_plan(tallies, members=6, capacity=10) == ["most", "half", "two", "few"]
    assert select_for_plan(tallies, members=6, capacity=2) == ["most", "half"]
    assert select_for_plan([Tally("x", 0, 0)], members=6, capacity=4) == []


def test_opening_hours_parsing() -> None:
    assert parse_hours("09:00-17:30") == OpeningHours(time(9), time(17, 30))
    assert parse_hours("Mo-Su 10:00–18:00") == OpeningHours(time(10), time(18))  # noqa: RUF001 — an en dash as suppliers write it
    assert parse_hours({"open": "08:00", "close": "12:00"}) == OpeningHours(time(8), time(12))
    assert parse_hours("24/7") is None
    assert parse_hours("18:00-10:00") is None
    assert parse_hours(None) is None


def test_kind_and_visit_length() -> None:
    assert kind_of("museum", "anything") is AttractionKind.MUSEUM
    assert kind_of("castle", "National Museum") is AttractionKind.MUSEUM
    assert kind_of(None, "Petřín Lookout Tower") is AttractionKind.VIEWPOINT
    assert kind_of(None, "Charles Bridge") is AttractionKind.LANDMARK
    assert visit_minutes(None, AttractionKind.MUSEUM) == 150
    assert visit_minutes("45", AttractionKind.MUSEUM) == 45
    assert visit_minutes(9000, AttractionKind.MUSEUM) == 240


def test_coordinates_are_read_defensively() -> None:
    assert coordinate("50.08", 90) == pytest.approx(50.08)
    assert coordinate(True, 90) is None
    assert coordinate("north", 90) is None
    assert coordinate(200.0, 180) is None


def test_a_food_market_over_lunch_is_lunch() -> None:
    market = PlannedAttraction(
        "market", "Market", near(0.2), 90, OpeningHours(time(12), time(20)), is_meal=True
    )
    plan = build_plan(TripFrame(SAT, SAT, base=CENTRE), [market, attraction("museum")])
    (day,) = plan
    assert [i.title for i in day.items if i.kind is ItemKind.MEAL] == ["Dinner"]
    assert "market" in visits(day)
