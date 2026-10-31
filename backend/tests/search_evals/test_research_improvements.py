"""The research changes the search evals drove, pinned on the simulators (fast, no network)."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.ai.catalog_research import CatalogResearcher
from app.ai.itinerary import fits_calendar, leg_fits
from app.ai.research import TripBrief
from app.core.domain.packages import per_person
from app.core.domain.result import Err, Result
from app.core.domain.suppliers import SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import BookingKind, SupplierChannel, TransportMode
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
    Segment,
)
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import sim_supplier

LOCAL = ZoneInfo("Europe/Warsaw")
BRIEF = TripBrief(
    title="Prague with friends",
    origin="Warszawa",
    brief="4 friends, a weekend in Prague.",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 22),
    travellers=4,
    destination="Praha",
)


def _clock() -> datetime:
    return datetime(2026, 10, 31, 12, tzinfo=UTC)


def _research(*ids: str) -> CatalogResearcher:
    return CatalogResearcher(SupplierRegistry(sim_supplier(i, _clock) for i in ids))


def _segment(day: int, hour: int, hours: float, origin: str = "WAW", to: str = "PRG") -> Segment:
    start = datetime(2026, 11, day, hour, tzinfo=LOCAL)
    return Segment("X", "X 1", origin, to, start, start + timedelta(hours=hours))


def test_a_leg_must_leave_on_its_day_and_not_at_night() -> None:
    assert leg_fits([_segment(20, 9, 2)], date(2026, 11, 20), arrive_same_day=True)
    assert not leg_fits([_segment(20, 2, 2)], date(2026, 11, 20), arrive_same_day=True)
    assert not leg_fits([_segment(20, 22, 4)], date(2026, 11, 20), arrive_same_day=True)
    assert leg_fits([_segment(22, 22, 9)], date(2026, 11, 22), arrive_same_day=False)
    assert not leg_fits([_segment(20, 7, 2)], date(2026, 11, 20), 8, arrive_same_day=True)


def test_the_calendar_needs_both_directions() -> None:
    there, back = _segment(20, 9, 2), _segment(22, 15, 2, "PRG", "WAW")
    assert fits_calendar([there, back], date(2026, 11, 20), date(2026, 11, 22))
    assert not fits_calendar([there], date(2026, 11, 20), date(2026, 11, 22))
    assert fits_calendar([], date(2026, 11, 20), date(2026, 11, 22))


async def test_no_train_anywhere_falls_back_to_flights_and_says_so() -> None:
    barcelona = replace(
        BRIEF, destination="Barcelona", transport_mode=TransportMode.RAIL, brief="by train"
    )
    packages = await _research("sim_rail", "sim_flight", "sim_stay", "sim_activity").research(
        barcelona
    )
    assert len(packages) == 3
    assert all(item.mode is TransportMode.FLIGHT for item in packages[0].items[:2])
    assert all("No train there and back" in package.summary for package in packages)


async def test_an_unreachable_budget_is_said_with_the_cheapest_price() -> None:
    tight = replace(BRIEF, budget_per_person_minor=10_000)
    budget, *_ = await _research("sim_rail", "sim_stay", "sim_activity").research(tight)
    share = per_person(budget.total_minor, 4)
    assert "Nothing found fits the budget of 100 PLN per person" in budget.summary
    assert f"{-(-share // 100)} PLN per person" in budget.summary


async def test_the_earliest_hour_keeps_the_dawn_flight_out() -> None:
    flights = replace(BRIEF, transport_mode=TransportMode.FLIGHT)
    early = await _research("sim_flight", "sim_stay").research(flights)
    late = await _research("sim_flight", "sim_stay").research(
        replace(flights, earliest_departure_hour=8)
    )
    assert early[0].items[0].supplier == "Ryanair"  # 06:25 out of Modlin
    assert late[0].items[0].supplier == "Wizz Air"  # 09:40


RAIL = SupplierCapabilities(
    kind=BookingKind.TRANSPORT,
    mode=TransportMode.RAIL,
    channel=SupplierChannel.AGENT,
    max_party_per_purchase=None,
)


@dataclass
class _OneWaysAreCheaper:
    """A rail carrier whose two one-ways cost less than its return ticket."""

    id: str = "cheap_one_ways"
    display_name: str = "One-way rail"
    capabilities: SupplierCapabilities = RAIL

    async def search(self, request: SearchRequest) -> list[Offer]:
        day = request.depart_date.day
        there = _segment(day, 8, 6, request.origin, request.destination)
        if request.return_date is None:
            return [self._offer(f"one-way-{day}", 30_000, (there,))]
        back = _segment(request.return_date.day, 15, 6, request.destination, request.origin)
        return [self._offer("return", 100_000, (there, back))]

    def _offer(self, ref: str, price: int, segments: tuple[Segment, ...]) -> Offer:
        return Offer(self.id, ref, ref, price, "PLN", "Rail", segments)

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        return None

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        return None

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        return Err("no")

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return None


async def test_two_one_ways_win_when_they_beat_the_return() -> None:
    registry = SupplierRegistry([_OneWaysAreCheaper(), sim_supplier("sim_stay", _clock)])
    budget, *_ = await CatalogResearcher(registry).research(BRIEF)
    transport = [item for item in budget.items if item.kind is BookingKind.TRANSPORT]
    assert [item.offer_ref for item in transport] == ["one-way-20", "one-way-22"]
    assert "Rail train both ways" in budget.title
