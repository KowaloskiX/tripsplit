"""A small headless eval: the real agent, a real browser, zero LLM calls.

baseline + renamed_buttons + reordered_fields, party 3, in `replay` (the LLM's 6-passenger
recording) and `rules_only`. The full matrix is `uv run agent-eval run --mode ...`, or this
file with `AGENT_EVAL_SLOW=1`.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.agent_evals.cases import DEFAULT_PARTIES, EvalCase, EvalMode, matrix
from app.agent_evals.harness import baseline_flow, run_case
from app.agent_evals.server import VariantServer
from app.services.demo_supplier_variants import Variant

ENGINE = os.getenv("AGENT_EVAL_ENGINE", "chromium")


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    ENGINE == "chromium" and not _browser_available(), reason="no headless Chromium installed"
)


@pytest.fixture(scope="module")
def server() -> Iterator[VariantServer]:
    with VariantServer() as running:
        yield running


SMALL = matrix(
    [Variant.BASELINE, Variant.RENAMED_BUTTONS, Variant.REORDERED_FIELDS],
    [3],
    [EvalMode.REPLAY, EvalMode.RULES_ONLY],
)


@pytest.mark.parametrize("case", SMALL, ids=[c.id for c in SMALL])
def test_small_eval_succeeds_without_the_model(
    case: EvalCase, server: VariantServer, tmp_path: Path
) -> None:
    result = run_case(
        case, server, flow=baseline_flow(), var_dir=str(tmp_path), engine=ENGINE, headless=True
    )
    assert result.success, f"{result.verdict} — {result.reason}"
    assert result.llm_calls == 0
    if case.mode is EvalMode.REPLAY:
        assert result.flow_steps >= 2, "the recorded flow should carry most of the run"


FULL = matrix(list(Variant), list(DEFAULT_PARTIES), [EvalMode.REPLAY, EvalMode.RULES_ONLY])


@pytest.mark.skipif(os.getenv("AGENT_EVAL_SLOW") != "1", reason="slow: set AGENT_EVAL_SLOW=1")
@pytest.mark.parametrize("case", FULL, ids=[c.id for c in FULL])
def test_full_eval_matrix(case: EvalCase, server: VariantServer, tmp_path: Path) -> None:
    result = run_case(
        case, server, flow=baseline_flow(), var_dir=str(tmp_path), engine=ENGINE, headless=True
    )
    assert result.success, f"{result.verdict} — {result.reason}"
    assert result.llm_calls == 0
