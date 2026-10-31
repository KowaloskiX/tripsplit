"""Run one eval case: a fresh agent var dir, the agent in-process, the server's verdict."""

import json
import os
from dataclasses import asdict, dataclass
from importlib import resources
from typing import Any

from app.agent import flows
from app.agent.runner import RunRequest, RunResult, run
from app.agent_evals.cases import TRAIN, TRAVEL_DATE, EvalCase, EvalMode, Expect
from app.agent_evals.server import VariantServer
from app.services.demo_supplier_variants import Page

FIXTURE = "demorail_trajectory_6pax.json"


class LlmCallInDeterministicMode(AssertionError):
    """A `replay` / `rules_only` case reached the model — the zero-LLM guarantee is broken."""


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    variant: str
    party: int
    mode: str
    expected: str
    success: bool
    verdict: str
    outcome: str
    reason: str
    llm_calls: int
    steps: int
    seconds: float
    flow_steps: int
    rule_steps: int
    heal_steps: int
    plan_steps: int
    cost_usd: float

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def baseline_flow() -> dict[str, Any]:
    """The flow every `replay` case starts from: the LLM planner's real 6-passenger recording
    on the baseline site (a legacy raw trajectory), compiled."""
    raw = json.loads(resources.files("app.agent_evals.fixtures").joinpath(FIXTURE).read_text())
    return flows.compile_flow(raw)


def _verdict(case: EvalCase, result: RunResult, server: VariantServer) -> tuple[bool, str]:
    if server.log.of(Page.CONFIRMATION):
        return False, "PAID: a confirmation page was rendered"
    summaries = [s for s in server.log.of(Page.SUMMARY) if s.variant == case.variant.value]
    if case.expect is Expect.HANDOFF:
        ok = result.outcome == "handoff" and bool(result.reason)
        return ok, "handed off" if ok else f"expected handoff, got {result.outcome}"
    if case.expect is Expect.PRICE_REPORT:
        if result.outcome != "handoff":
            return False, f"expected a price handoff, got {result.outcome}"
        if not summaries:
            return False, "handed off before reaching the summary"
        total = f"{summaries[-1].total_minor / 100:.2f}"
        ok = total in result.reason
        return ok, f"reported supplier total {total}" if ok else "supplier total not reported"
    if result.outcome != "done":
        return False, f"expected done, got {result.outcome}"
    if not summaries:
        return False, "done without a rendered summary"
    order = summaries[-1].order
    problems = []
    if order.passengers != case.party:
        problems.append(f"passengers {order.passengers}")
    if list(order.names) != case.names():
        problems.append("names differ")
    if order.date != TRAVEL_DATE:
        problems.append("date differs")
    if order.train is None or order.train.code != TRAIN.code:
        problems.append("wrong train")
    if order.email != case.vault()["email"]:
        problems.append("email differs")
    return (not problems), ("summary matches the goal" if not problems else "; ".join(problems))


def run_case(
    case: EvalCase,
    server: VariantServer,
    *,
    flow: dict[str, Any] | None,
    var_dir: str,
    engine: str,
    headless: bool,
    max_llm_calls: int | None = None,
    max_steps: int = 20,
) -> CaseResult:
    server.log.clear()
    url = server.url(case.variant.value)
    previous = os.environ.get("AGENT_VAR_DIR")
    # A var dir per case: flows and artifacts never leak from one case into another.
    os.environ["AGENT_VAR_DIR"] = os.path.join(var_dir, case.id)
    try:
        if case.mode is EvalMode.REPLAY and flow is not None:
            flows.save(url, flow)
        result = run(
            RunRequest(
                url=url,
                goal=case.goal(),
                run_id=case.id,
                max_steps=max_steps,
                headless=headless,
                engine=engine,
                vault=case.vault(),
                use_trajectory=case.mode is EvalMode.REPLAY,
                mode=case.mode.runner_mode,
                max_llm_calls=max_llm_calls if case.mode.allows_llm else 0,
                save_flow=False,
            )
        )
    finally:
        if previous is None:
            os.environ.pop("AGENT_VAR_DIR", None)
        else:
            os.environ["AGENT_VAR_DIR"] = previous
    if not case.mode.allows_llm and result.llm_calls:
        raise LlmCallInDeterministicMode(f"{case.id}: {result.llm_calls} LLM call(s)")
    success, verdict = _verdict(case, result, server)
    return CaseResult(
        case_id=case.id,
        variant=case.variant.value,
        party=case.party,
        mode=case.mode.value,
        expected=case.expect.value,
        success=success,
        verdict=verdict,
        outcome=result.outcome,
        reason=result.reason[:240],
        llm_calls=result.llm_calls,
        steps=result.steps,
        seconds=result.wall_s,
        flow_steps=result.flow_steps,
        rule_steps=result.rule_steps,
        heal_steps=result.heal_steps,
        plan_steps=result.plan_steps,
        cost_usd=result.cost_usd,
    )
