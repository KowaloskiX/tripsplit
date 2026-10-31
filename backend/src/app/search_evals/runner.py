"""Runs one brief: the REAL research path (`CatalogResearcher` over the wrapped suppliers), then
the oracle over every offer, optional re-quotes of what the packages chose, then the metrics."""

import time
from collections.abc import Sequence

from app.ai.catalog_research import CatalogResearcher
from app.ai.research import PackagePlan
from app.search_evals.cassette import CassetteMiss, RecordingSupplier
from app.search_evals.dataset import EvalBrief
from app.search_evals.llm_guard import no_llm
from app.search_evals.metrics import BriefResult, evaluate
from app.search_evals.oracle import collect, solve
from app.suppliers.ports import OfferRef
from app.suppliers.registry import SupplierRegistry


async def _quote_drift(
    packages: Sequence[PackagePlan], suppliers: SupplierRegistry, party: int, notes: list[str]
) -> float | None:
    """The mean |quote - search price| / search price over the chosen items, in percent."""
    drifts: list[float] = []
    seen: set[tuple[str, str]] = set()
    for package in packages:
        for item in package.items:
            adapter = suppliers.get(item.supplier_id)
            key = (item.supplier_id, item.offer_ref)
            if adapter is None or key in seen or item.price_minor <= 0:
                continue
            seen.add(key)
            ref = OfferRef(item.supplier_id, item.offer_ref, dict(item.supplier_data))
            try:
                quote = await adapter.quote(ref, party)
            except CassetteMiss:
                notes.append(f"quote not recorded: {item.supplier_id}")
                continue
            except Exception as failure:
                notes.append(f"quote failed at {item.supplier_id}: {type(failure).__name__}")
                continue
            if quote is None:
                notes.append(f"no longer offered at re-quote: {item.title}")
                continue
            drifts.append(abs(quote.price_minor - item.price_minor) / item.price_minor * 100)
    return round(sum(drifts) / len(drifts), 2) if drifts else None


async def run_brief(
    brief: EvalBrief, suppliers: SupplierRegistry, *, quotes: bool = False
) -> BriefResult:
    started = time.monotonic()
    notes: list[str] = []
    packages: list[PackagePlan] = []
    with no_llm() as llm:
        try:
            packages = await CatalogResearcher(suppliers).research(brief.trip_brief())
        except CassetteMiss as miss:
            return BriefResult(brief.id, error=f"cassette miss: {miss}")
        except ValueError as refused:
            notes.append(f"research gave up: {refused}")
        try:
            raw = await collect(brief, suppliers)
        except CassetteMiss as miss:
            return BriefResult(brief.id, error=f"cassette miss (oracle): {miss}")
    result = evaluate(brief, packages, raw, solve(brief, raw))
    result.llm_calls = llm.calls
    if quotes and packages:
        result.quote_drift_percent = await _quote_drift(packages, suppliers, brief.party, notes)
    result.notes.extend(notes)
    result.seconds = time.monotonic() - started
    return result


def stats_of(wrapped: Sequence[RecordingSupplier]) -> dict[str, dict[str, object]]:
    return {supplier.id: supplier.stats.json() for supplier in wrapped}
