"""Search speed: concurrent suppliers, timeouts, the search cache, PKP dedupe — no network."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.ai.catalog_research import CatalogResearcher
from app.ai.research import SearchOutcome, SupplierProgress, TripBrief, research_progress
from app.core.domain.trips import BookingKind
from app.db.documents import utc_now
from app.services.proposals import progress_message
from app.suppliers.intercity import BrowserTransport, IntercityClient, SharedBrowserTransport
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import Offer, SearchRequest, SupplierAdapter
from app.suppliers.registry import SupplierRegistry
from app.suppliers.search_cache import SearchCache
from app.suppliers.sim import sim_supplier

BRIEF = TripBrief(
    title="Weekend in Prague",
    origin="Warszawa Centralna",
    brief="",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 22),
    travellers=6,
    destination="Praha",
)
REQUEST = SearchRequest("Warszawa", "Praha", date(2026, 11, 20), date(2026, 11, 22), 6)


@dataclass
class Slow:
    """Wraps a simulator: waits `delay_s` (or forever), or raises, before answering."""

    inner: SupplierAdapter
    delay_s: float = 0.0
    hang: bool = False
    fail: bool = False
    calls: int = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def search(self, request: SearchRequest) -> list[Offer]:
        self.calls += 1
        if self.hang:
            await asyncio.Event().wait()
        await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("supplier down")
        return await self.inner.search(request)


def _sim(supplier_id: str, **behaviour: Any) -> Slow:
    return Slow(sim_supplier(supplier_id, utc_now), **behaviour)


def _researcher(*adapters: Slow, **options: Any) -> CatalogResearcher:
    return CatalogResearcher(SupplierRegistry(adapters), **options)


async def _with_progress(researcher: CatalogResearcher) -> list[SupplierProgress]:
    seen: list[SupplierProgress] = []

    async def record(progress: SupplierProgress) -> None:
        seen.append(progress)

    research_progress.set(record)
    await researcher.research(BRIEF)
    return seen


async def test_suppliers_are_searched_concurrently() -> None:
    adapters = [_sim(i, delay_s=0.2) for i in ("sim_rail", "sim_stay", "sim_activity")]
    started = time.monotonic()
    plans = await _researcher(*adapters).research(BRIEF)
    assert len(plans) == 3
    assert time.monotonic() - started < 0.4  # sequential would be >= 0.6


async def test_a_hanging_stay_supplier_times_out_without_failing_the_research() -> None:
    rail, stay = _sim("sim_rail"), _sim("sim_stay", hang=True)
    researcher = _researcher(rail, stay, supplier_timeout_s=0.05)
    started = time.monotonic()
    seen = await _with_progress(researcher)
    assert time.monotonic() - started < 0.5
    outcomes = {progress.supplier_id: progress.outcome for progress in seen}
    assert outcomes == {"sim_rail": SearchOutcome.OK, "sim_stay": SearchOutcome.TIMEOUT}


async def test_a_failing_supplier_yields_no_offers() -> None:
    researcher = _researcher(_sim("sim_rail"), _sim("sim_bus", fail=True), _sim("sim_stay"))
    seen = await _with_progress(researcher)
    failed = [progress for progress in seen if progress.outcome is SearchOutcome.FAILED]
    assert [progress.supplier_id for progress in failed] == ["sim_bus"]


async def test_a_cached_research_does_not_ask_the_suppliers_again() -> None:
    rail, stay = _sim("sim_rail"), _sim("sim_stay")
    cache = SearchCache(ttl_s=300)
    first = await _researcher(rail, stay, cache=cache).research(BRIEF)
    # A rail research asks for the return and for two singles (each direction) once each.
    assert (rail.calls, stay.calls) == (3, 1)
    seen = await _with_progress(_researcher(rail, stay, cache=cache))
    assert (rail.calls, stay.calls) == (3, 1)
    assert {progress.outcome for progress in seen} == {SearchOutcome.CACHED}
    assert await _researcher(rail, stay, cache=cache).research(BRIEF) == first


async def test_a_timed_out_search_fills_the_cache_for_the_next_research() -> None:
    rail, stay = _sim("sim_rail"), _sim("sim_stay", delay_s=0.1)
    cache = SearchCache(ttl_s=300)
    await _researcher(rail, stay, cache=cache, supplier_timeout_s=0.02).research(BRIEF)
    await asyncio.sleep(0.15)
    seen = await _with_progress(_researcher(rail, stay, cache=cache, supplier_timeout_s=0.02))
    assert stay.calls == 1
    assert {p.supplier_id: p.outcome for p in seen}["sim_stay"] is SearchOutcome.CACHED


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def _offer() -> Offer:
    return Offer("sim_rail", "ref", "A train", 100, "PLN", "Seller")


class Counting(Slow):
    """Answers one offer (or none) and counts the searches."""

    def __init__(self, offers: int = 1, delay_s: float = 0.0) -> None:
        super().__init__(sim_supplier("sim_rail", utc_now), delay_s=delay_s)
        self.offers = offers

    async def search(self, request: SearchRequest) -> list[Offer]:
        self.calls += 1
        await asyncio.sleep(self.delay_s)
        return [_offer()] * self.offers


async def test_cache_entries_expire_and_empty_results_are_not_kept() -> None:
    clock = Clock()
    cache = SearchCache(ttl_s=10, clock=clock)
    adapter, empty = Counting(), Counting(offers=0)
    await cache.search(adapter, REQUEST)
    await cache.search(adapter, REQUEST)
    assert adapter.calls == 1
    clock.now = 10
    await cache.search(adapter, REQUEST)
    assert adapter.calls == 2
    await cache.search(empty, REQUEST)
    await cache.search(empty, REQUEST)
    assert empty.calls == 2


async def test_an_entry_answers_only_the_adapter_that_produced_it() -> None:
    cache = SearchCache(ttl_s=10)
    first, other = Counting(), Counting()  # the same supplier id, configured twice
    await cache.search(first, REQUEST)
    await cache.search(other, REQUEST)
    assert (first.calls, other.calls) == (1, 1)


async def test_identical_concurrent_searches_share_one_call() -> None:
    cache = SearchCache(ttl_s=10)
    adapter = Counting(delay_s=0.01)
    answers = await asyncio.gather(*(cache.search(adapter, REQUEST) for _ in range(4)))
    assert adapter.calls == 1 and all(answer == [_offer()] for answer in answers)


async def test_a_zero_ttl_disables_the_cache() -> None:
    cache = SearchCache(ttl_s=0)
    adapter = Counting()
    await cache.search(adapter, REQUEST)
    await cache.search(adapter, REQUEST)
    assert adapter.calls == 2


# ---- PKP Intercity ------------------------------------------------------------------------


def _connection(number: int, departs: str, arrives: str) -> dict[str, Any]:
    return {
        "pociagi": [
            {
                "kategoriaPociagu": "EC",
                "nrPociagu": number,
                "nazwaPociagu": "Praha",
                "dataWyjazdu": departs,
                "dataPrzyjazdu": arrives,
            }
        ],
        "dataWyjazdu": departs,
        "dataPrzyjazdu": arrives,
        "czasJazdy": 500,
    }


@dataclass
class PkpRecorder:
    """Recorded-shape answers; counts requests and the peak of concurrent ones."""

    stations: int = 0
    fares: list[int] = field(default_factory=list)
    in_flight: int = 0
    peak: int = 0

    async def _enter(self) -> None:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1

    async def get_json(self, url: str) -> Any:
        self.stations += 1
        await self._enter()
        code = "5100065" if "Warszawa" in url else "5400014"
        return [{"n": "Warszawa Centralna" if code == "5100065" else "Praha hl.n.", "h": code}]

    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        await self._enter()
        if url.endswith("/Pociagi"):
            day = body["dataWyjazdu"][:10]
            return {
                "polaczenia": [
                    _connection(100 + hour, f"{day} {hour:02d}:10:00", f"{day} 23:00:00")
                    for hour in (6, 8, 10, 14, 16, 18)
                ]
            }
        size = len(body["podrozni"])
        self.fares.append(size)
        return {
            "ceny": [
                {
                    "opisyOfert": [{"nazwaOferty": "Super Promo"}],
                    "klasa": travel_class,
                    "cena": 10000 * travel_class * size,
                    "czyPropozycjaZwrotna": False,
                    "kodPropozycji": "p",
                    "dataWaznosciPropozycji": "2026-11-01 03:00:00",
                    "podrozni": [{}] * size,
                }
                for travel_class in (1, 2)
            ]
        }


async def test_pkp_prices_each_split_size_once_and_concurrently() -> None:
    transport = PkpRecorder()
    supplier = PkpIntercitySupplier(transport)
    offers = await supplier.search(REQUEST)
    assert len(offers) == 2  # 2. and 1. class
    assert offers[0].price_minor == 2 * 6 * 20000  # two legs, six people, 2. class
    # 3 outbound + 3 return trains in the departure windows, one 3-person request each.
    assert transport.fares == [3] * 6
    assert transport.peak > 1
    await supplier.search(REQUEST)
    assert transport.stations == 2  # station lookups are cached


async def test_the_client_bounds_concurrent_calls() -> None:
    transport = PkpRecorder()
    client = IntercityClient(transport, max_concurrent=2)
    await asyncio.gather(*(client.stations("Praha") for _ in range(6)))
    assert transport.peak == 2


class FakeBrowser(BrowserTransport):
    def __init__(self) -> None:
        super().__init__(headless=True)
        self.in_flight = self.peak = 0

    async def __aenter__(self) -> "FakeBrowser":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_json(self, url: str) -> Any:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return url


async def test_the_shared_browser_runs_calls_concurrently_on_one_browser() -> None:
    opened: list[FakeBrowser] = []

    def factory() -> FakeBrowser:
        opened.append(FakeBrowser())
        return opened[-1]

    shared = SharedBrowserTransport(factory, max_concurrent=3)
    await asyncio.gather(*(shared.get_json(f"u{n}") for n in range(6)))
    assert len(opened) == 1 and opened[0].peak == 3


def test_progress_messages() -> None:
    def progress(outcome: SearchOutcome, offers: int = 2) -> str:
        return progress_message(
            SupplierProgress("pkp", "PKP Intercity", BookingKind.TRANSPORT, outcome, offers, 2.94)
        )

    assert progress(SearchOutcome.OK) == "PKP Intercity ✓ 2 offers · 2.9 s"
    assert progress(SearchOutcome.CACHED, 1) == "PKP Intercity ✓ 1 offer · cached"
    assert "too slow" in progress(SearchOutcome.TIMEOUT)
    assert "unavailable" in progress(SearchOutcome.FAILED)
