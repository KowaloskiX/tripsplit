"""Macro planning, the LLM call cap and rate-limit handling — with fake model backends."""

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from app.agent import planner as planner_mod
from app.agent.planner import BasePlanner, ClaudeCliPlanner, NullPlanner, PlannerUnavailable
from app.agent.runner import _queue, _revalidate
from tests.agent.pages import passengers_page


class _Scripted(BasePlanner):
    def __init__(self, reply: dict[str, Any]) -> None:
        super().__init__()
        self.reply = reply
        self.systems: list[str] = []

    def _complete(
        self, system: str, user: str, screenshot_png: bytes | None, screenshot_path: str | None
    ) -> dict[str, Any]:
        self.systems.append(system)
        copy: dict[str, Any] = json.loads(json.dumps(self.reply))
        return copy


def _plan(p: BasePlanner) -> list[dict[str, Any]]:
    return list(p.next_plan("goal", True, "page", ["email"], []))


def test_a_macro_plan_is_capped_and_ends_at_a_terminal_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLANNER_MAX_PLAN", "3")
    actions = [
        {"action": "fill_form", "fields": [{"ref": 1, "text": "{{vault.email}}"}]},
        {"action": "done", "reason": "ok"},
        {"action": "click", "ref": 9},
    ]
    p = _Scripted({"actions": actions, "milestone": "passengers"})
    plan = _plan(p)
    assert [a["action"] for a in plan] == ["fill_form", "done"]
    assert all(a["milestone"] == "passengers" for a in plan)
    assert p.calls == 1 and "MACRO MODE" in p.systems[0]


def test_single_action_mode_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANNER_MACRO", "0")
    p = _Scripted({"action": "click", "ref": 3})
    assert _plan(p) == [{"action": "click", "ref": 3}]


def test_the_call_cap_hands_off_without_calling_the_model() -> None:
    p = _Scripted({"actions": [{"action": "wait"}], "milestone": None})
    p.max_calls = 2
    for _ in range(4):
        _plan(p)
    assert p.calls == 2
    assert _plan(p)[0]["action"] == "handoff"


def test_the_null_planner_never_counts_a_call() -> None:
    p = NullPlanner()
    plan = list(p.next_plan("goal", True, "page", [], [], hint="stage 'unknown'"))
    assert plan[0]["action"] == "handoff" and p.calls == 0
    assert "LLM is disabled" in plan[0]["reason"]


def _fake_claude(tmp_path: Path, stdout: dict[str, Any], code: int) -> Path:
    script = tmp_path / "claude"
    args_file = tmp_path / "args.json"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        f"json.dump(sys.argv[1:], open({str(args_file)!r}, 'w'))\n"
        f"print(json.dumps({stdout!r}))\nsys.exit({code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_claude_cli_asks_for_the_plan_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = {"structured_output": {"actions": [{"action": "wait"}], "milestone": "search"}}
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_claude(tmp_path, reply, 0)))
    p = ClaudeCliPlanner()
    assert _plan(p)[0]["action"] == "wait"
    args = json.loads((tmp_path / "args.json").read_text())
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert schema == planner_mod.PLAN_SCHEMA


def test_a_rate_limit_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"result": "API Error: 429 rate limit reached for your plan"}
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_claude(tmp_path, reply, 1)))
    with pytest.raises(PlannerUnavailable, match="429"):
        _plan(ClaudeCliPlanner())


def test_a_queued_macro_action_is_retargeted_or_dropped() -> None:
    before = passengers_page(1)
    click = {"action": "click", "ref": before["elements"][-1]["ref"]}
    queued = _queue(click, before)
    # Same page, refs shifted by a re-render: the descriptor finds the button again.
    shifted = passengers_page(1)
    for element in shifted["elements"]:
        element["ref"] += 10
    retargeted = _revalidate(queued, shifted)
    assert retargeted is not None and retargeted["ref"] == click["ref"] + 10
    # A different page: the rest of the plan is void.
    moved = {**shifted, "url": "http://127.0.0.1/elsewhere"}
    assert _revalidate(queued, moved) is None
