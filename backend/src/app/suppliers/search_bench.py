"""`search-bench`: how long a package research takes, per supplier and in total.

Three fixed briefs (6 people, a weekend about three weeks out):

- `prague_rail` — Warszawa -> Praha by rail: live PKP Intercity (Camoufox `BrowserTransport`)
  + simulated stays and activities;
- `barcelona_flight` — Warszawa -> Barcelona by air: live Duffel (test key from `.env`)
  + simulated stays and activities;
- `prague_sim` — Warszawa -> Praha with every supplier simulated (the control).

Each brief runs twice: `cold` (empty search cache) and `warm` (the same research again — what
a re-generate costs). The PKP browser is warmed up once before timing, as the API server's
shared browser would be; that warm-up is printed separately. Network-bound: not a test.

    uv run search-bench                       # all briefs
    uv run search-bench prague_rail --runs 1
"""

import argparse
import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.ai.catalog_research import CatalogResearcher
from app.ai.research import SupplierProgress, TripBrief, research_progress
from app.core.config import Settings
from app.core.domain.trips import TransportMode
from app.db.documents import utc_now
from app.suppliers.intercity import BrowserTransport
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import SupplierAdapter
from app.suppliers.providers import duffel_config, duffel_supplier
from app.suppliers.registry import SupplierRegistry
from app.suppliers.search_cache import SearchCache
from app.suppliers.sim import sim_supplier

SIM_EXTRAS = ("sim_stay", "sim_activity")


@dataclass(frozen=True)
class Bench:
    name: str
    brief: TripBrief
    transport: Callable[[], SupplierAdapter | None]


def _weekend() -> tuple[date, date]:
    start = date.today() + timedelta(days=21)
    friday = start + timedelta(days=(4 - start.weekday()) % 7)
    return friday, friday + timedelta(days=2)


def _brief(destination: str, mode: TransportMode) -> TripBrief:
    date_from, date_to = _weekend()
    return TripBrief(
        title=f"Weekend in {destination}",
        origin="Warszawa",
        brief=f"Six friends, a weekend in {destination}.",
        date_from=date_from,
        date_to=date_to,
        travellers=6,
        budget_per_person_minor=150_000,
        destination=destination,
        transport_mode=mode,
    )


def _row(cells: Sequence[str]) -> str:
    return " | ".join(
        cell.ljust(width) for cell, width in zip(cells, (18, 5, 16, 8, 10), strict=True)
    )


async def _run(bench: Bench, runs: int, cache_ttl_s: float) -> None:
    transport = bench.transport()
    if transport is None:
        print(f"{bench.name}: skipped (supplier not configured)")
        return
    cache = SearchCache(ttl_s=cache_ttl_s)
    registry = SupplierRegistry(
        [transport, *(sim_supplier(supplier_id, utc_now) for supplier_id in SIM_EXTRAS)]
    )
    for run in range(runs):
        label = "cold" if run == 0 else "warm"
        finished: list[SupplierProgress] = []

        async def record(
            progress: SupplierProgress, into: list[SupplierProgress] = finished
        ) -> None:
            into.append(progress)

        research_progress.set(record)
        researcher = CatalogResearcher(registry, cache=cache)
        started = time.monotonic()
        try:
            plans = await researcher.research(bench.brief)
            outcome = f"{len(plans)} packages"
        except Exception as failure:
            outcome = f"FAILED: {failure}"
        total = time.monotonic() - started
        for progress in finished:
            print(
                _row(
                    [
                        bench.name,
                        label,
                        progress.supplier_id,
                        f"{progress.seconds:6.2f}s",
                        f"{progress.offers} {progress.outcome.value}",
                    ]
                )
            )
        print(_row([bench.name, label, "TOTAL", f"{total:6.2f}s", ""]) + f" | {outcome}")


async def browser_stations(pkp: PkpIntercitySupplier, *names: str) -> list[int]:
    codes = []
    for name in names:
        found = await pkp.client.stations(name)
        if not found:
            raise RuntimeError(f"PKP knows no station {name!r}")
        codes.append(found[0].code)
    return codes


async def _main(names: Sequence[str], runs: int, cache_ttl_s: float) -> None:
    settings = Settings()
    async with BrowserTransport(headless=True) as browser:
        pkp = PkpIntercitySupplier(browser)
        if "prague_rail" in names:
            # Opens both pages on a route the benches do not use, so no cache is primed.
            started = time.monotonic()
            krakow, gdansk = await browser_stations(pkp, "Kraków Główny", "Gdańsk Główny")
            await pkp.client.connections(krakow, gdansk, date.today() + timedelta(days=1))
            print(f"PKP browser warm-up: {time.monotonic() - started:.2f}s")
        duffel = duffel_config(settings)
        benches = [
            Bench("prague_rail", _brief("Praha", TransportMode.RAIL), lambda: pkp),
            Bench(
                "barcelona_flight",
                _brief("Barcelona", TransportMode.FLIGHT),
                lambda: duffel_supplier(duffel) if duffel is not None else None,
            ),
            Bench(
                "prague_sim",
                _brief("Praha", TransportMode.RAIL),
                lambda: sim_supplier("sim_rail", utc_now),
            ),
        ]
        print(_row(["brief", "run", "supplier", "seconds", "offers"]))
        for bench in benches:
            if bench.name in names:
                await _run(bench, runs, cache_ttl_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "briefs", nargs="*", default=["prague_rail", "barcelona_flight", "prague_sim"]
    )
    parser.add_argument("--runs", type=int, default=2, help="1 = cold only")
    parser.add_argument("--cache-ttl", type=float, default=300.0, help="0 disables the cache")
    args = parser.parse_args()
    asyncio.run(_main(args.briefs, args.runs, args.cache_ttl))


if __name__ == "__main__":
    main()
