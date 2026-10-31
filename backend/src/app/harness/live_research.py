"""`--live-search`: the fixture packages with the train priced from the REAL PKP Intercity API.

Stays and activities stay deterministic; each package's train item is replaced by the cheapest
real group fare (outbound on `date_from`, return on `date_to`, split into purchases of at most
five passengers the way the carrier sells them) through a headless Camoufox page.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime

from app.ai.fixture_research import FixtureResearcher
from app.ai.research import PackageItemPlan, PackagePlan, TripBrief
from app.core.domain.trips import BookingKind
from app.suppliers.intercity import (
    BrowserTransport,
    Connection,
    FareQuote,
    IntercityClient,
    Station,
    results_url,
    split_group,
)

# Departure windows the fixture packages promise (outbound morning, return afternoon).
OUTBOUND_HOURS = range(5, 12)
RETURN_HOURS = range(13, 21)
MAX_CONNECTIONS = 6


@dataclass(frozen=True, slots=True)
class LegQuote:
    direction: str  # "outbound" | "return"
    connection: str
    departs_at: datetime
    arrives_at: datetime
    travel_class: int
    offer_name: str
    purchases: tuple[int, ...]  # grosze per purchase
    passengers: tuple[int, ...]

    @property
    def total_minor(self) -> int:
        return sum(self.purchases)


@dataclass
class LiveSearchLog:
    origin: str = ""
    destination: str = ""
    seconds: float = 0.0
    legs: list[LegQuote] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _in_window(connections: Sequence[Connection], hours: range) -> list[Connection]:
    preferred = [c for c in connections if c.departs_at.hour in hours]
    return (preferred or list(connections))[:MAX_CONNECTIONS]


def _cheapest(fares: Sequence[FareQuote], travel_class: int) -> FareQuote | None:
    matching = [f for f in fares if f.travel_class == travel_class and not f.refundable]
    return min(matching, key=lambda fare: fare.total_minor, default=None)


class LiveIntercityResearcher:
    def __init__(self, origin_station: str, destination_station: str) -> None:
        self.origin_station = origin_station
        self.destination_station = destination_station
        self.fixture = FixtureResearcher()
        self.log = LiveSearchLog()
        self.stations: tuple[Station, Station] | None = None

    def _results_url(self, day: date, departs_at: datetime) -> str:
        if self.stations is None:
            return ""
        origin, destination = self.stations
        return results_url(day, origin.code, destination.code, f"{departs_at:%H:%M}")

    async def research(self, brief: TripBrief) -> list[PackagePlan]:
        plans = await self.fixture.research(brief)
        started = time.monotonic()
        try:
            async with BrowserTransport(headless=True) as browser:
                client = IntercityClient(browser)
                legs = await self._legs(client, brief)
        finally:
            self.log.seconds = round(time.monotonic() - started, 1)
        if legs is None:
            return plans
        return [self._with_real_train(plan, legs, brief) for plan in plans]

    async def _legs(
        self, client: IntercityClient, brief: TripBrief
    ) -> dict[int, tuple[LegQuote, LegQuote]] | None:
        origin = await client.station(self.origin_station)
        destination = await client.station(self.destination_station)
        if origin is None or destination is None:
            self.log.notes.append("unknown station — the fixture train price is kept")
            return None
        self.log.origin, self.log.destination = origin.name, destination.name
        by_class: dict[int, tuple[LegQuote, LegQuote]] = {}
        self.stations = (origin, destination)
        outbound = await self._best(
            client, (origin, destination), brief.date_from, brief.travellers, OUTBOUND_HOURS
        )
        back = await self._best(
            client, (destination, origin), brief.date_to, brief.travellers, RETURN_HOURS
        )
        for travel_class in (1, 2):
            there = outbound.get(travel_class)
            home = back.get(travel_class)
            if there is not None and home is not None:
                by_class[travel_class] = (
                    replace(there, direction="outbound"),
                    replace(home, direction="return"),
                )
                self.log.legs.extend(by_class[travel_class])
            else:
                self.log.notes.append(f"no {travel_class}. class fare found both ways")
        return by_class or None

    @staticmethod
    async def _best(
        client: IntercityClient,
        route: tuple[Station, Station],
        day: date,
        travellers: int,
        hours: range,
    ) -> dict[int, LegQuote]:
        """The cheapest whole-group fare per class over the connections in the window."""
        origin, to = route
        connections = await client.connections(origin.code, to.code, day)
        best: dict[int, LegQuote] = {}
        for connection in _in_window(connections, hours):
            per_size = [
                await client.fares(connection, origin.code, to.code, size)
                for size in split_group(travellers)
            ]
            for travel_class in (1, 2):
                picks = [_cheapest(fares, travel_class) for fares in per_size]
                if any(pick is None for pick in picks):
                    continue
                chosen = [pick for pick in picks if pick is not None]
                quote = LegQuote(
                    direction="",
                    connection=connection.label,
                    departs_at=connection.departs_at,
                    arrives_at=connection.arrives_at,
                    travel_class=travel_class,
                    offer_name=chosen[0].offer_name,
                    purchases=tuple(pick.total_minor for pick in chosen),
                    passengers=tuple(pick.passengers for pick in chosen),
                )
                current = best.get(travel_class)
                if current is None or quote.total_minor < current.total_minor:
                    best[travel_class] = quote
        return best

    def _with_real_train(
        self, plan: PackagePlan, legs: dict[int, tuple[LegQuote, LegQuote]], brief: TripBrief
    ) -> PackagePlan:
        items: list[PackageItemPlan] = []
        for item in plan.items:
            travel_class = 1 if "1st" in item.title else 2
            if item.kind is not BookingKind.TRAIN or travel_class not in legs:
                items.append(item)
                continue
            there, home = legs[travel_class]
            split = "+".join(str(n) for n in there.passengers)
            items.append(
                replace(
                    item,
                    title=(
                        f"PKP Intercity {there.connection} {self.log.origin} -> "
                        f"{self.log.destination} ({travel_class}. class, return)"
                    )[:120],
                    price_minor=there.total_minor + home.total_minor,
                    supplier_url=self._results_url(brief.date_from, there.departs_at),
                    details=(
                        f"Outbound {there.departs_at:%Y-%m-%d %H:%M} {there.connection}; return "
                        f"{home.departs_at:%Y-%m-%d %H:%M} {home.connection}. "
                        f"{there.offer_name}. Sold as {split} passengers per purchase "
                        "(PKP Intercity sells at most 5 per transaction)."
                    ),
                    starts_at=there.departs_at,
                )
            )
        return replace(plan, items=tuple(items))
