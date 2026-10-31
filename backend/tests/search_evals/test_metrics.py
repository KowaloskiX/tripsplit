"""Metrics: schedule checks, the oracle and the scores, over the simulated suppliers."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.ai.research import PackageItemPlan, PackagePlan
from app.core.domain.trips import BookingKind, TransportMode
from app.search_evals.checks import Journey, place_key, schedule_checks, split_directions
from app.search_evals.dataset import BRIEFS, BudgetTier, EvalBrief, ModeWish, select
from app.search_evals.llm_guard import LlmCallRefused, no_llm
from app.search_evals.metrics import evaluate, mode_ok, summarise
from app.search_evals.oracle import collect, solve
from app.search_evals.runner import run_brief
from app.suppliers.ports import Segment
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import sim_supplier

LOCAL = ZoneInfo("Europe/Warsaw")
TRIP = Journey("Warszawa", "Praha", date(2026, 11, 20), date(2026, 11, 22))


def _clock() -> datetime:
    return datetime(2026, 10, 31, 12, tzinfo=UTC)


def _sims(*ids: str) -> SupplierRegistry:
    return SupplierRegistry(sim_supplier(supplier_id, _clock) for supplier_id in ids)


def _leg(origin: str, destination: str, day: int, hour: int, hours: float) -> Segment:
    start = datetime(2026, 11, day, hour, tzinfo=LOCAL)
    return Segment("X", "X 1", origin, destination, start, start + timedelta(hours=hours))


def _brief(**changes: object) -> EvalBrief:
    return replace(select(["waw-prg-rail-4"])[0], **changes)  # type: ignore[arg-type]  # test-only field overrides


def test_places_compare_at_city_level() -> None:
    assert place_key("WMI") == place_key("Warszawa Centralna") == "WAW"
    assert place_key("Praga Gł./Praha hl.n.") == place_key("PRG")
    assert place_key("Budapest-Keleti") == "BUD"
    assert place_key("Nowhere") == "nowhere"


def test_a_sane_journey_passes_every_check() -> None:
    segments = [
        _leg("WAW", "PRG", 20, 9, 1.5),
        _leg("Praha hl.n.", "Warszawa Centralna", 22, 14, 8),
    ]
    out, back = split_directions(segments)
    assert len(out) == len(back) == 1
    assert all(schedule_checks(segments, TRIP).values())


def test_late_arrivals_bad_connections_and_early_starts_fail() -> None:
    segments = [
        _leg("WAW", "VIE", 20, 18, 1),
        _leg("VIE", "PRG", 20, 19, 6),  # departs before the first leg lands
        _leg("PRG", "WAW", 21, 6, 1.5),  # the day before checkout
    ]
    checks = schedule_checks(segments, replace(TRIP, earliest_departure_hour=8))
    failed = {name for name, ok in checks.items() if not ok}
    assert failed == {
        "arrives_before_check_in_day_ends",
        "return_departs_on_checkout_day",
        "connections_ok",
        "no_departure_before_preferred_hour",
    }


def test_the_dataset_covers_the_matrix() -> None:
    assert len(BRIEFS) >= 24 and len({brief.id for brief in BRIEFS}) == len(BRIEFS)
    assert {b.origin for b in BRIEFS} == {"Warszawa", "Kraków", "Gdańsk"}
    assert {b.party for b in BRIEFS} == {2, 4, 6, 8}
    assert set(ModeWish) == {b.mode for b in BRIEFS}
    assert set(BudgetTier) == {b.budget for b in BRIEFS}


async def test_a_rail_brief_on_the_simulators_scores_and_calls_no_llm() -> None:
    result = await run_brief(_brief(), _sims("sim_rail", "sim_flight", "sim_stay", "sim_activity"))
    assert result.error is None and result.llm_calls == 0
    assert result.scores["completeness"] == 1.0
    assert result.scores["mode"] == 1.0
    assert result.scores["consistency"] == 1.0
    assert result.oracle is not None and result.oracle.complete_possible
    assert result.gap_percent is not None and result.gap_percent >= 0


async def test_an_unreachable_budget_is_reported_infeasible() -> None:
    registry = _sims("sim_flight", "sim_stay", "sim_activity")
    fits = _brief(budget=BudgetTier.TIGHT)
    assert solve(fits, await collect(fits, _sims("sim_rail", "sim_stay"))).feasible is True
    (barcelona,) = select(["waw-bcn-any-6-tight"])
    result = await run_brief(barcelona, registry)
    assert result.oracle is not None and result.oracle.feasible is False
    assert result.scores["budget"] in (0.0, 0.5, 1.0)


def _transport(mode: TransportMode, day: int) -> PackageItemPlan:
    return PackageItemPlan(
        kind=BookingKind.TRANSPORT,
        title=f"{mode} {day}",
        supplier="X",
        supplier_url="",
        price_minor=100,
        mode=mode,
        segments=(_leg("WAW", "PRG", day, 9, 1),),
    )


def test_fly_there_train_back_needs_that_order() -> None:
    brief = _brief(mode=ModeWish.FLY_THERE_TRAIN_BACK)
    right = PackagePlan(
        "a", "a", (_transport(TransportMode.FLIGHT, 20), _transport(TransportMode.RAIL, 22))
    )
    wrong = PackagePlan(
        "b", "b", (_transport(TransportMode.RAIL, 20), _transport(TransportMode.FLIGHT, 22))
    )
    assert mode_ok(right, brief) and not mode_ok(wrong, brief)


async def test_no_packages_score_zero_but_do_not_crash() -> None:
    brief = _brief()
    raw = await collect(brief, _sims("sim_rail", "sim_stay"))
    result = evaluate(brief, [], raw, solve(brief, raw))
    assert result.scores["completeness"] == 0.0 and result.score < 0.3
    summary = summarise([result], {})
    assert summary.briefs == 1 and summary.errors == 0


async def test_the_guard_counts_and_refuses_llm_calls() -> None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key="sk-test")
    with no_llm() as counter, pytest.raises(LlmCallRefused):
        await client.chat.completions.create(model="x", messages=[])
    assert counter.calls == 1
