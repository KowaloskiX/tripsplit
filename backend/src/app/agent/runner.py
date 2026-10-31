"""The loop: observe -> decide -> act -> recover, until done / handoff / step cap.

DECIDE is a cascade, cheapest and most certain first:

  1. a pending macro plan  — the rest of a plan the planner returned last step, each action
                             re-validated against the fresh page before it runs;
  2. the FLOW              — a compiled, parametrised recording of a past success
                             (`flows.py`); a step whose target is gone is a miss;
  3. the RULE LAYER        — deterministic, structural decisions (`rules.py`) driven by the
                             typed site profile (`site_profiles.py`);
  4. the PLANNER           — an LLM, only when 1-3 have no confident action. It returns a
                             short plan for the page (macro planning), not one action.

`--mode` picks which layers may run: `auto` (all), `replay` (flow + rules, no LLM), `rules`
(rules only, no LLM), `llm` (rules + planner, no flow) and `planner` (the LLM alone — the
pre-engine behaviour, kept as an eval baseline). `--max-llm-calls` caps the model.

Two entry points:
  - `run(RunRequest)` — called by a service (in a worker thread or subprocess).
  - `main()` — the `agent-run` CLI for development and recon:
        uv run agent-run --url https://www.saucedemo.com --goal "..." --run-id demo

Per step the runner writes `runs/<run_id>/NN.png`, `status.json` (milestone, step, cost) and
a continuously refreshed `live.jpg` (a CDP screencast on Chromium, a screenshot every ~300 ms
on Camoufox/Firefox). A caller streams those to the UI.
"""

import argparse
import contextlib
import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from app.agent import flows
from app.agent import graph as graph_mod
from app.agent.act import act
from app.agent.browser import Browser
from app.agent.goal import parse_goal
from app.agent.observe import observe, render_for_planner
from app.agent.paths import run_dir
from app.agent.planner import NullPlanner, PlannerUnavailable, make_planner
from app.agent.recover import auto_dismiss, detect_block
from app.agent.rules import RuleEngine, detect_stage, pay_button
from app.agent.site_profiles import Stage, profile_for
from app.agent.skills import notes_for
from app.agent.vault import Vault

RESULT_MARKER = "__AGENT_RESULT__ "

# Human approval of the final pay click (`--await-approval`). The backend writes
# `runs/<run_id>/approval.json` = {"approved": true|false}; the runner polls for it.
APPROVAL_FILE = "approval.json"
PAY_GOAL = "Submit the order / pay now and wait for the confirmation"
PAY_MAX_STEPS = 10
_DEFAULT_APPROVAL_TIMEOUT_S = 900.0

# Checkout phases after which navigating back to the cart/login only restarts a loop.
_ADVANCED_MILESTONES = ("delivery", "address", "payment", "review", "summary")
_REGRESSIVE_URL_HINTS = ("koszyk", "logowanie", "login", "/cart", "basket")
_DESC_CHECK = ("tag", "name", "id", "label", "text")
# Re-observations (500 ms apart) while a page shows no interactive element yet.
_RENDER_PATIENCE = 8


class Mode(StrEnum):
    AUTO = "auto"
    REPLAY = "replay"
    RULES = "rules"
    LLM = "llm"
    PLANNER = "planner"  # the LLM alone, as before the engine: a baseline for evals

    @property
    def uses_flow(self) -> bool:
        return self in (Mode.AUTO, Mode.REPLAY)

    @property
    def uses_rules(self) -> bool:
        return self is not Mode.PLANNER

    @property
    def uses_llm(self) -> bool:
        return self in (Mode.AUTO, Mode.LLM, Mode.PLANNER)


class Source(StrEnum):
    FLOW = "flow"
    RULE = "rule"
    LLM = "llm"
    PLAN = "plan"  # a validated follow-up action of an earlier macro plan


@dataclass
class RunRequest:
    url: str
    goal: str
    run_id: str
    stop_before_pay: bool = True
    max_steps: int = 40
    headless: bool = True
    engine: str | None = None
    vault: dict[str, Any] = field(default_factory=dict)
    # Non-secret preferences (class, seat, cancellation policy...) shown to the planner in
    # plain text so it picks the matching option.
    preferences: dict[str, str] = field(default_factory=dict)
    use_trajectory: bool = True
    # After a stop-before-pay `done`, wait for a human decision instead of exiting.
    await_approval: bool = False
    # Which decision layers may run (see the module docstring) and the hard LLM cap.
    mode: str = field(default_factory=lambda: os.getenv("AGENT_MODE", Mode.AUTO.value))
    max_llm_calls: int | None = None
    # Persist a (re-)compiled flow after a successful run that had no flow or healed one.
    save_flow: bool = True


@dataclass
class RunResult:
    run_id: str
    url: str
    goal: str
    outcome: str = "unknown"  # done | handoff | stuck | max_steps | error | unknown
    reason: str = ""
    steps: int = 0
    artifacts_dir: str = ""
    milestones: list[str] = field(default_factory=list)
    planner_calls: int = 0
    tokens: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    cache_hits: int = 0
    # The supplier's booking number; `SIM-xxxxxx` when the final click is simulated.
    confirmation_ref: str = ""
    # --- engine stats (new fields; older readers ignore them) ---
    mode: str = Mode.AUTO.value
    llm_calls: int = 0
    flow_steps: int = 0
    rule_steps: int = 0
    plan_steps: int = 0
    heal_steps: int = 0
    flow_misses: int = 0
    wall_s: float = 0.0
    final_stage: str = ""
    # The supplier summary as read before `done` (names masked); None if never reached.
    summary: dict[str, Any] | None = None


def approval_timeout_s() -> float:
    try:
        return float(os.getenv("AGENT_APPROVAL_TIMEOUT_S", _DEFAULT_APPROVAL_TIMEOUT_S))
    except ValueError:
        return _DEFAULT_APPROVAL_TIMEOUT_S


def final_click_mode() -> str:
    """`simulate` (the default) never presses pay; only an explicit `real` does."""
    mode = os.getenv("AGENT_FINAL_CLICK", "simulate").strip().lower()
    return "real" if mode == "real" else "simulate"


def read_approval(artifacts: str) -> bool | None:
    """The decision in `approval.json`, or None while there is none (or it is unreadable)."""
    try:
        with open(os.path.join(artifacts, APPROVAL_FILE), encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    approved = payload.get("approved") if isinstance(payload, dict) else None
    return approved if isinstance(approved, bool) else None


def wait_for_approval(
    artifacts: str,
    timeout_s: float,
    poll_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool | None:
    """Poll for the human decision. True / False, or None when the timeout elapses."""
    deadline = clock() + timeout_s
    while True:
        decision = read_approval(artifacts)
        if decision is not None:
            return decision
        if clock() >= deadline:
            return None
        sleep(poll_s)


def _cost_usd(tokens: dict[str, int]) -> float:
    """Rough USD estimate from token counts. Prices per 1M tokens, env-configurable."""
    price_in = float(os.getenv("PRICE_IN_PER_M", "1.25"))
    price_out = float(os.getenv("PRICE_OUT_PER_M", "10"))
    return round(tokens.get("in", 0) / 1e6 * price_in + tokens.get("out", 0) / 1e6 * price_out, 5)


def _write_json(path: str, payload: Any) -> None:
    with contextlib.suppress(Exception), open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def _parse_mode(raw: str | None) -> Mode:
    try:
        return Mode((raw or Mode.AUTO.value).strip().lower())
    except ValueError:
        return Mode.AUTO


def _screenshot_policy(stage: Stage, failed_last: bool, elements: list[dict[str, Any]]) -> bool:
    """Send the screenshot to the planner? `auto` = only when text alone is likely too thin."""
    policy = os.getenv("PLANNER_SCREENSHOT", "auto").lower()
    if policy in ("always", "1"):
        return True
    if policy in ("never", "0"):
        return False
    return failed_last or stage is Stage.UNKNOWN or len(elements) < 3


def _same_target(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    return bool(a and b) and all((a or {}).get(k) == (b or {}).get(k) for k in _DESC_CHECK)


def _revalidate(pending: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """A queued macro action re-targeted to the CURRENT page, or None if the page moved on."""
    if pending["url"] != state.get("url"):
        return None
    elements = state["elements"]
    by_ref = {e.get("ref"): e for e in elements}
    action = dict(pending["action"])

    def retarget(ref: Any, desc: dict[str, Any] | None) -> Any:
        if desc is None:
            return ref
        if _same_target(flows.descriptor(by_ref.get(ref)), desc):
            return ref
        return flows.resolve(desc, elements)

    if action.get("ref") is not None:
        action["ref"] = retarget(action["ref"], pending["descs"].get("ref"))
        if action["ref"] is None:
            return None
    if action.get("fields"):
        fields = []
        for i, f in enumerate(action["fields"]):
            ref = retarget(f.get("ref"), pending["descs"].get(f"field{i}"))
            if ref is None:
                return None
            fields.append({**f, "ref": ref})
        action["fields"] = fields
    return action


def _queue(action: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    by_ref = {e.get("ref"): e for e in state["elements"]}
    descs: dict[str, Any] = {}
    if action.get("ref") is not None:
        descs["ref"] = flows.descriptor(by_ref.get(action["ref"]))
    for i, f in enumerate(action.get("fields") or []):
        descs[f"field{i}"] = flows.descriptor(by_ref.get(f.get("ref")))
    return {"action": action, "url": state.get("url"), "descs": descs}


def run(req: RunRequest) -> RunResult:
    started = time.monotonic()
    if req.engine:
        os.environ["ENGINE"] = req.engine
    mode = _parse_mode(req.mode)
    artifacts = run_dir(req.run_id)
    os.makedirs(artifacts, exist_ok=True)
    result = RunResult(
        run_id=req.run_id, url=req.url, goal=req.goal, artifacts_dir=artifacts, mode=mode.value
    )

    vault = Vault(req.vault or None)
    goal = parse_goal(req.goal, vault)
    planner = make_planner(max_calls=req.max_llm_calls) if mode.uses_llm else NullPlanner()
    browser = Browser(headless=req.headless)
    browser.live_frame_path = os.path.join(artifacts, "live.jpg")
    browser.type_delay_ms = 25 if profile_for(req.url).human_typing else 0
    prefs_text = "; ".join(f"{k}: {v}" for k, v in req.preferences.items() if v)

    history: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    milestones: list[str] = []
    last_milestone = None
    prev_sig, repeats = None, 0
    last_notes = ""
    pending: list[dict[str, Any]] = []
    recorded: list[dict[str, Any]] = []
    counts = {source: 0 for source in Source}
    heal_steps = 0
    failed_last = False
    step_missed = False
    step_log: list[dict[str, Any]] = []

    flow = flows.load(req.url) if (req.use_trajectory and mode.uses_flow) else None
    player = flows.FlowPlayer(flow, goal, profile_for(req.url)) if flow else None
    if flow:
        party = flow.get("recorded_party")
        print(f"[flow] loaded: {len(flow['steps'])} steps (recorded for {party})")
    plan_graph = graph_mod.flow_graph(flow) if flow else graph_mod.generic_graph()
    _write_json(os.path.join(artifacts, "flow_graph.json"), plan_graph)

    def status(step: int, reason: str) -> None:
        _write_json(
            os.path.join(artifacts, "status.json"),
            {
                "milestone": last_milestone,
                "reached": milestones,
                "step": step,
                "reason": reason,
                "outcome": result.outcome,
                "cache_hits": counts[Source.FLOW],
                "planner_calls": planner.calls,
                "tokens": planner.tokens["total"],
                "cost_usd": _cost_usd(planner.tokens),
                "flow_steps": counts[Source.FLOW],
                "rule_steps": counts[Source.RULE],
                "llm_calls": planner.calls,
                "steps": step_log,
            },
        )

    def decide(
        goal_text: str,
        stop_before_pay: bool,
        rules: RuleEngine,
        state: dict[str, Any],
        stage: Stage,
        shot: str,
        use_flow: bool,
    ) -> tuple[list[dict[str, Any]], Source]:
        nonlocal heal_steps, step_missed
        step_missed = False
        if pending:
            queued = _revalidate(pending.pop(0), state)
            if queued is not None:
                return [queued], Source.PLAN
            pending.clear()
        missed = False
        if use_flow and player is not None and not player.finished():
            batch = player.next_actions(state["elements"], stage)
            if batch is not None:
                return batch, Source.FLOW
            missed = step_missed = not player.finished()
            if missed:
                print(f"[flow] {player.log[-1] if player.log else 'miss'} -> self-heal")
        decision = rules.decide(state) if mode.uses_rules else None
        if decision is not None:
            heal_steps += int(missed)
            print(f"[rules] {decision.stage}: {decision.why}")
            return decision.actions, Source.RULE
        hint = f"stage looks like '{stage}'" + (f"; {rules.notes[-1]}" if rules.notes else "")
        with_shot = planner.enabled and _screenshot_policy(stage, failed_last, state["elements"])
        if planner.enabled and not with_shot:
            with contextlib.suppress(Exception):
                state["aria"] = observe(browser.page, with_aria=True).get("aria", "")
        png = None
        if with_shot:
            with contextlib.suppress(Exception), open(shot, "rb") as fh:
                png = fh.read()
        notes = notes_for(state.get("url", ""))
        plan = planner.next_plan(
            goal_text,
            stop_before_pay,
            render_for_planner(state),
            vault.planner_keys(),
            history,
            screenshot_png=png,
            screenshot_path=shot if with_shot else None,
            site_notes=notes,
            preferences=prefs_text,
            hint=hint,
        )
        heal_steps += int(missed and planner.enabled)
        for extra in plan[1:]:
            pending.append(_queue(extra, state))
        return plan[:1], Source.LLM

    def guard(
        action: dict[str, Any],
        source: Source,
        rules: RuleEngine,
        state: dict[str, Any],
        stage: Stage,
        stop_before_pay: bool,
    ) -> dict[str, Any]:
        """Deterministic vetoes on model-made decisions: verify a `done`, never press pay."""
        if source is Source.RULE:
            return action
        kind = action.get("action")
        presses_pay = (
            kind == "click"
            and stop_before_pay
            and (btn := pay_button(state["elements"], rules.profile)) is not None
            and btn.get("ref") == action.get("ref")
        )
        if (kind == "done" and stage is Stage.REVIEW) or presses_pay:
            check = rules.summary_check(state)
            verdict = "done" if check.ok else "handoff"
            return {"action": verdict, "reason": check.reason(goal), "milestone": "review"}
        return action

    def drive(goal_text: str, stop_before_pay: bool, first: int, last: int, use_flow: bool) -> None:
        """Run steps `first..last` towards the goal; sets `result.outcome` when it stops."""
        nonlocal last_milestone, prev_sig, repeats, last_notes, failed_last
        profile = profile_for(req.url)
        rules = RuleEngine(
            goal=goal,
            profile=profile,
            vault_get=vault.get,
            vault_keys=vault.planner_keys(),
            stop_before_pay=stop_before_pay,
        )
        for step in range(first, last + 1):
            # RECOVER (pre): clear overlays, then check for human-only gates.
            auto_dismiss(browser.page)
            blocked, reason = detect_block(browser.page)
            if blocked:
                browser.screenshot(os.path.join(artifacts, f"{step:02d}-handoff.png"))
                print(f"[step {step}] HANDOFF -> {reason}")
                result.outcome, result.reason, result.steps = "handoff", reason, step
                break

            # OBSERVE (patiently: a page that renders late gets a few seconds, not a step each)
            try:
                state = observe(browser.page)
                for _ in range(_RENDER_PATIENCE):
                    if state["elements"] or detect_stage(state, rules.profile) != Stage.UNKNOWN:
                        break
                    browser.idle(0.5)
                    state = observe(browser.page)
            except Exception as exc:
                print(f"  [observe error] {exc!r:.120} — settling & retrying")
                browser.settle()
                continue
            shot = os.path.join(artifacts, f"{step:02d}.png")
            browser.screenshot(shot)
            stage = detect_stage(state, rules.profile)
            result.final_stage = stage.value
            notes = notes_for(state.get("url", ""))
            if notes and notes != last_notes:
                print(f"[skill] loaded site playbook for {state.get('url', '')[:60]}")
                last_notes = notes

            # DECIDE
            decided_at = time.monotonic()
            plan, source = decide(goal_text, stop_before_pay, rules, state, stage, shot, use_flow)
            counts[source] += 1
            flow_nodes = (
                [f"s{i}" for i in player.last_indices]
                if source is Source.FLOW and player is not None
                else []
            )
            page_render = vault.mask(render_for_planner(state))
            plan = [guard(a, source, rules, state, stage, stop_before_pay) for a in plan]
            safe_plan = [
                {k: v for k, v in a.items() if k != "text" or "{{" in str(v)} for a in plan
            ]
            print(f"[step {step}] [{source}] {json.dumps(safe_plan)[:300]}")
            history.extend(safe_plan)
            trace.append(
                {
                    "step": step,
                    "url": vault.mask(state.get("url", "")),
                    "stage": stage.value,
                    "source": source.value,
                    "render": page_render,
                    "action": safe_plan[0] if len(safe_plan) == 1 else {"plan": safe_plan},
                }
            )
            for action in plan:
                if action.get("action") not in ("done", "handoff"):
                    recorded.append(flows.record_step(action, state["elements"]))

            milestone = plan[-1].get("milestone") or plan[0].get("milestone")
            if milestone and milestone != last_milestone:
                last_milestone = milestone
                milestones.append(milestone)
                print(f"[milestone] {milestone}")
            status(step, plan[-1].get("reason") or "")

            # Loop guard: nudge on 3x identical, hard-stop on 5x.
            sig = json.dumps(
                [
                    (
                        a.get("action"),
                        a.get("ref"),
                        str(a.get("text") or a.get("fields"))[:80],
                        a.get("x"),
                        a.get("y"),
                        a.get("direction"),
                    )
                    for a in plan
                ]
            )
            repeats = repeats + 1 if sig == prev_sig and plan[0].get("action") != "wait" else 0
            prev_sig = sig
            if repeats == 2:
                history.append(
                    {
                        "note": "You repeated the same action 3x with no visible progress — a "
                        "consent banner may be blocking the page; dismiss it or pick a different "
                        "visible control."
                    }
                )
            if repeats >= 4:
                browser.screenshot(os.path.join(artifacts, f"{step:02d}-stuck.png"))
                result.outcome, result.steps = "stuck", step
                result.reason = f"Repeated the same action without visible progress ({sig[:200]})."
                break

            terminal = False
            failed_last = False
            for position, action in enumerate(plan):
                kind = action.get("action")
                entry = {
                    "index": step,
                    "node_id": (
                        flow_nodes[position]
                        if position < len(flow_nodes)
                        else graph_mod.node_for(plan_graph, stage.value, action)
                    ),
                    "kind": kind,
                    "status": "running",
                    "duration_ms": 0,
                    "source": source.value,
                }
                step_log.append(entry)
                # Regressive-navigation guard.
                if kind == "goto" and any(m in _ADVANCED_MILESTONES for m in milestones):
                    target = (action.get("url") or "").lower()
                    if any(k in target for k in _REGRESSIVE_URL_HINTS):
                        print(f"[guard] blocked regressive goto -> {target[:70]}")
                        if recorded and recorded[-1].get("action") == "goto":
                            recorded.pop()
                        history.append(
                            {
                                "note": "Do NOT navigate back to the cart or login page — you "
                                "are already past that step. Finish the current step in place."
                            }
                        )
                        pending.clear()
                        entry["status"] = "failed"
                        browser.settle()
                        break
                if kind in ("done", "handoff"):
                    browser.screenshot(os.path.join(artifacts, f"{step:02d}-{kind}.png"))
                    result.outcome, result.steps = kind, step
                    result.reason = vault.mask(action.get("reason") or "")
                    entry["status"] = "done" if kind == "done" else "failed"
                    entry["duration_ms"] = int((time.monotonic() - decided_at) * 1000)
                    terminal = True
                    break
                # ACT
                try:
                    act(browser, action, vault)
                except Exception as exc:
                    print(f"  [act error] {exc!r:.160} — re-observing")
                    # Tell the planner what went wrong, otherwise it retries the same action.
                    history.append({"note": f"The last action FAILED: {str(exc)[:300]}"})
                    failed_last = True
                    pending.clear()
                    entry["status"] = "failed"
                    break
                finally:
                    entry["duration_ms"] = int((time.monotonic() - decided_at) * 1000)
                if entry["status"] == "running":
                    entry["status"] = "healed" if step_missed else "done"
                status(step, plan[-1].get("reason") or "")
            if rules.last_summary is not None:
                result.summary = rules.last_summary.masked()
            if terminal:
                break
        else:
            result.outcome, result.steps = "max_steps", last
            result.reason = "Hit the step cap without reaching a terminal state."

    def finish_after_approval() -> None:
        """The summary is ready: park the browser until a human decides, then pay or stop."""
        result.outcome = "awaiting_approval"
        status(result.steps, result.reason)
        print(f"[approval] waiting for {os.path.join(artifacts, APPROVAL_FILE)}")
        waited_from = time.monotonic()
        decision = wait_for_approval(artifacts, approval_timeout_s(), sleep=browser.idle)
        step_log.append(
            {
                "index": result.steps,
                "node_id": "approve",
                "kind": "approve",
                "status": "done" if decision else "failed",
                "duration_ms": int((time.monotonic() - waited_from) * 1000),
                "source": "human",
            }
        )
        if decision is None:
            result.outcome, result.reason = "handoff", "Nobody approved the summary in time."
            return
        if not decision:
            result.outcome, result.reason = "handoff", "The organizer rejected the summary."
            return
        if final_click_mode() == "real":
            # The pay steps must never land in a flow: a later stop-before-pay run replaying
            # them would click "pay" without anyone approving it.
            keep = len(recorded)
            result.outcome = "unknown"
            drive(PAY_GOAL, False, result.steps + 1, result.steps + PAY_MAX_STEPS, False)
            del recorded[keep:]
            return
        step = result.steps + 1
        browser.screenshot(os.path.join(artifacts, f"{step:02d}-done.png"))
        result.outcome, result.reason, result.steps = "done", "simulated confirmation", step
        result.confirmation_ref = f"SIM-{secrets.token_hex(3).upper()}"

    try:
        browser.start()
        browser.goto(req.url)
        drive(req.goal, req.stop_before_pay, 1, req.max_steps, True)
        if req.await_approval and req.stop_before_pay and result.outcome == "done":
            finish_after_approval()
    except PlannerUnavailable as exc:
        result.outcome, result.reason = "error", f"planner unavailable: {str(exc)[:240]}"
    except Exception as exc:
        result.outcome, result.reason = "error", repr(exc)[:300]
    finally:
        browser.close()

    result.milestones = milestones
    result.planner_calls = result.llm_calls = planner.calls
    result.tokens = dict(planner.tokens)
    result.cost_usd = _cost_usd(planner.tokens)
    result.cache_hits = result.flow_steps = counts[Source.FLOW]
    result.rule_steps = counts[Source.RULE]
    result.plan_steps = counts[Source.PLAN]
    result.heal_steps = heal_steps
    result.flow_misses = player.misses if player else 0
    result.wall_s = round(time.monotonic() - started, 2)
    status(result.steps, result.reason)
    _write_json(os.path.join(artifacts, "trace.json"), trace)
    _write_json(os.path.join(artifacts, "result.json"), asdict(result))
    healed = player is None or player.misses > 0
    if req.use_trajectory and req.save_flow and result.outcome == "done" and recorded and healed:
        with contextlib.suppress(Exception):
            compiled = flows.compile_flow(recorded, goal, vault.lookup())
            path = flows.save(req.url, compiled)
            if path:
                print(f"[flow] saved: {len(compiled['steps'])} steps -> {path}")
    print(
        f"[stats] mode={mode} steps={result.steps} flow={result.flow_steps} "
        f"rules={result.rule_steps} llm_calls={planner.calls} plan={result.plan_steps} "
        f"heal={heal_steps} {result.wall_s}s ~${result.cost_usd}  [artifacts] {artifacts}/"
    )
    return result


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv("../.env")
    load_dotenv()
    ap = argparse.ArgumentParser(description="Run the booking agent on a supplier URL.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--goal", required=True)
    ap.add_argument("--run-id", default=f"cli-{int(time.time())}")
    ap.add_argument("--pay", action="store_true", help="do NOT stop before the final pay click")
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--headful", action="store_true", help="show the browser window")
    ap.add_argument("--engine", choices=["camoufox", "chromium", "firefox"])
    ap.add_argument(
        "--planner",
        choices=["openai", "claude-cli", "manual", "none"],
        help="overrides PLANNER from the environment",
    )
    ap.add_argument("--vault", help="path to a JSON file with vault values (never committed)")
    ap.add_argument("--no-cache", action="store_true", help="ignore the flow/trajectory cache")
    ap.add_argument("--json", action="store_true", help="emit a machine-readable result line")
    ap.add_argument(
        "--await-approval",
        action="store_true",
        help="at the summary, wait for runs/<id>/approval.json before paying (or simulating)",
    )
    ap.add_argument(
        "--mode",
        choices=[m.value for m in Mode],
        help="decision layers: auto (flow+rules+LLM), replay (flow+rules), rules, llm (rules+LLM), "
        "planner (LLM only)",
    )
    ap.add_argument("--max-llm-calls", type=int, help="hard cap on planner (LLM) calls")
    args = ap.parse_args()

    if args.planner:
        os.environ["PLANNER"] = args.planner
    vault: dict[str, Any] = {}
    if args.vault:
        with open(args.vault, encoding="utf-8") as fh:
            vault = json.load(fh)
    request = RunRequest(
        url=args.url,
        goal=args.goal,
        run_id=args.run_id,
        stop_before_pay=not args.pay,
        max_steps=args.max_steps,
        headless=not args.headful,
        engine=args.engine,
        vault=vault,
        use_trajectory=not args.no_cache,
        await_approval=args.await_approval,
        max_llm_calls=args.max_llm_calls,
    )
    if args.mode:
        request.mode = args.mode
    result = run(request)
    if args.json:
        print(RESULT_MARKER + json.dumps(asdict(result)))


if __name__ == "__main__":
    main()
