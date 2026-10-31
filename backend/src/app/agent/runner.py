"""The loop: observe -> decide -> act -> recover, until done / handoff / step cap.

Two entry points:
  - `run(RunRequest)` — called by a service (in a worker thread or subprocess).
  - `main()` — the `agent-run` CLI for development and recon:
        uv run agent-run --url https://www.saucedemo.com --goal "..." --run-id demo

Per step the runner writes `runs/<run_id>/NN.png`, `status.json` (milestone, step, cost) and,
on Chromium, a continuously refreshed `live.jpg`. A caller streams those to the UI.
"""

import argparse
import contextlib
import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.agent import trajectory as traj_mod
from app.agent.act import act
from app.agent.browser import Browser
from app.agent.observe import observe, render_for_planner
from app.agent.paths import run_dir
from app.agent.planner import make_planner
from app.agent.recover import auto_dismiss, detect_block
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


def run(req: RunRequest) -> RunResult:
    if req.engine:
        os.environ["ENGINE"] = req.engine
    artifacts = run_dir(req.run_id)
    os.makedirs(artifacts, exist_ok=True)
    result = RunResult(run_id=req.run_id, url=req.url, goal=req.goal, artifacts_dir=artifacts)

    vault = Vault(req.vault or None)
    planner = make_planner()
    browser = Browser(headless=req.headless)
    browser.live_frame_path = os.path.join(artifacts, "live.jpg")
    prefs_text = "; ".join(f"{k}: {v}" for k, v in req.preferences.items() if v)

    history: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    milestones: list[str] = []
    last_milestone = None
    prev_sig, repeats = None, 0
    last_notes = ""

    traj = traj_mod.load(req.url) if req.use_trajectory else None
    ti, cache_hits, replay_on, recorded = 0, 0, bool(traj), []
    if traj:
        print(f"[cache] loaded trajectory: {len(traj)} steps")

    def status(step: int, reason: str) -> None:
        _write_json(
            os.path.join(artifacts, "status.json"),
            {
                "milestone": last_milestone,
                "reached": milestones,
                "step": step,
                "reason": reason,
                "outcome": result.outcome,
                "cache_hits": cache_hits,
                "planner_calls": planner.calls,
                "tokens": planner.tokens["total"],
                "cost_usd": _cost_usd(planner.tokens),
            },
        )

    def drive(goal: str, stop_before_pay: bool, first: int, last: int) -> None:
        """Run steps `first..last` towards `goal`; sets `result.outcome` when it stops."""
        nonlocal last_milestone, prev_sig, repeats, last_notes, ti, cache_hits, replay_on
        for step in range(first, last + 1):
            # RECOVER (pre): clear overlays, then check for human-only gates.
            auto_dismiss(browser.page)
            blocked, reason = detect_block(browser.page)
            if blocked:
                browser.screenshot(os.path.join(artifacts, f"{step:02d}-handoff.png"))
                print(f"[step {step}] HANDOFF -> {reason}")
                result.outcome, result.reason, result.steps = "handoff", reason, step
                break

            # OBSERVE
            try:
                state = observe(browser.page)
            except Exception as exc:
                print(f"  [observe error] {exc!r:.120} — settling & retrying")
                browser.settle()
                continue
            shot = os.path.join(artifacts, f"{step:02d}.png")
            browser.screenshot(shot)
            png = None
            with contextlib.suppress(Exception), open(shot, "rb") as fh:
                png = fh.read()

            # DECIDE
            notes = notes_for(state.get("url", ""))
            if notes and notes != last_notes:
                print(f"[skill] loaded site playbook for {state.get('url', '')[:60]}")
                last_notes = notes
            page_render = render_for_planner(state)
            action = None
            from_cache = False
            if replay_on and traj and ti < len(traj):
                cand = traj_mod.action_from_cache(traj[ti], state["elements"])
                if cand is not None:
                    action, from_cache, ti = cand, True, ti + 1
                    cache_hits += 1
                else:
                    replay_on = False
                    print(f"[cache] miss at step {step} -> self-heal via planner")
            if action is None:
                action = planner.next_action(
                    goal,
                    stop_before_pay,
                    page_render,
                    vault.planner_keys(),
                    history,
                    screenshot_png=png,
                    screenshot_path=shot,
                    site_notes=notes,
                    preferences=prefs_text,
                )
            safe = {k: v for k, v in action.items() if k != "text" or "{{" in str(v)}
            print(f"[step {step}]{' [cache]' if from_cache else ''} {json.dumps(safe)}")
            history.append(safe)
            trace.append(
                {"step": step, "url": state.get("url", ""), "render": page_render, "action": safe}
            )
            if action.get("action") not in ("done", "handoff"):
                recorded.append(traj_mod.record_step(action, state["elements"]))

            milestone = action.get("milestone")
            if milestone and milestone != last_milestone:
                last_milestone = milestone
                milestones.append(milestone)
                print(f"[milestone] {milestone}")
            status(step, action.get("reason") or "")

            # Loop guard: nudge on 3x identical, hard-stop on 5x.
            sig = (
                action.get("action"),
                action.get("ref"),
                str(action.get("text") or action.get("fields"))[:80],
                action.get("x"),
                action.get("y"),
                action.get("direction"),
            )
            repeats = repeats + 1 if sig == prev_sig else 0
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
                result.reason = f"Repeated the same action without visible progress ({sig})."
                break

            # Regressive-navigation guard.
            if action.get("action") == "goto" and any(
                m in _ADVANCED_MILESTONES for m in milestones
            ):
                target = (action.get("url") or "").lower()
                if any(k in target for k in _REGRESSIVE_URL_HINTS):
                    print(f"[guard] blocked regressive goto -> {target[:70]}")
                    if recorded and recorded[-1].get("action") == "goto":
                        recorded.pop()
                    history.append(
                        {
                            "note": "Do NOT navigate back to the cart or login page — you are "
                            "already past that step. Finish the current step in place."
                        }
                    )
                    browser.settle()
                    continue

            if action.get("action") == "done":
                browser.screenshot(os.path.join(artifacts, f"{step:02d}-done.png"))
                result.outcome, result.reason, result.steps = "done", action.get("reason", ""), step
                break
            if action.get("action") == "handoff":
                browser.screenshot(os.path.join(artifacts, f"{step:02d}-handoff.png"))
                result.outcome, result.steps = "handoff", step
                result.reason = action.get("reason", "")
                break

            # ACT
            try:
                act(browser, action, vault)
            except Exception as exc:
                print(f"  [act error] {exc!r:.160} — re-observing")
                # Tell the planner what went wrong, otherwise it retries the same action blind.
                history.append({"note": f"The last action FAILED: {str(exc)[:300]}"})
        else:
            result.outcome, result.steps = "max_steps", last
            result.reason = "Hit the step cap without reaching a terminal state."

    def finish_after_approval() -> None:
        """The summary is ready: park the browser until a human decides, then pay or stop."""
        nonlocal replay_on
        result.outcome = "awaiting_approval"
        status(result.steps, result.reason)
        print(f"[approval] waiting for {os.path.join(artifacts, APPROVAL_FILE)}")
        decision = wait_for_approval(artifacts, approval_timeout_s())
        if decision is None:
            result.outcome, result.reason = "handoff", "Nobody approved the summary in time."
            return
        if not decision:
            result.outcome, result.reason = "handoff", "The organizer rejected the summary."
            return
        if final_click_mode() == "real":
            # The pay steps must never land in the trajectory cache: a later stop-before-pay
            # run replaying them would click "pay" without anyone approving it.
            keep = len(recorded)
            replay_on = False
            result.outcome = "unknown"
            drive(PAY_GOAL, False, result.steps + 1, result.steps + PAY_MAX_STEPS)
            del recorded[keep:]
            return
        step = result.steps + 1
        browser.screenshot(os.path.join(artifacts, f"{step:02d}-done.png"))
        result.outcome, result.reason, result.steps = "done", "simulated confirmation", step
        result.confirmation_ref = f"SIM-{secrets.token_hex(3).upper()}"

    try:
        browser.start()
        browser.goto(req.url)
        drive(req.goal, req.stop_before_pay, 1, req.max_steps)
        if req.await_approval and req.stop_before_pay and result.outcome == "done":
            finish_after_approval()
    except Exception as exc:
        result.outcome, result.reason = "error", repr(exc)[:300]
    finally:
        browser.close()

    result.milestones = milestones
    result.planner_calls = planner.calls
    result.tokens = dict(planner.tokens)
    result.cost_usd = _cost_usd(planner.tokens)
    result.cache_hits = cache_hits
    status(result.steps, result.reason)
    _write_json(os.path.join(artifacts, "trace.json"), trace)
    _write_json(os.path.join(artifacts, "result.json"), asdict(result))
    if req.use_trajectory and result.outcome == "done" and recorded:
        with contextlib.suppress(Exception):
            path = traj_mod.save(req.url, recorded)
            if path:
                print(f"[cache] saved trajectory: {len(recorded)} steps -> {path}")
    print(
        f"[tokens] planner calls={planner.calls} total={planner.tokens['total']} "
        f"~${result.cost_usd}  [artifacts] {artifacts}/"
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
        choices=["openai", "claude-cli", "manual"],
        help="overrides PLANNER from the environment",
    )
    ap.add_argument("--vault", help="path to a JSON file with vault values (never committed)")
    ap.add_argument("--no-cache", action="store_true", help="ignore the trajectory cache")
    ap.add_argument("--json", action="store_true", help="emit a machine-readable result line")
    ap.add_argument(
        "--await-approval",
        action="store_true",
        help="at the summary, wait for runs/<id>/approval.json before paying (or simulating)",
    )
    args = ap.parse_args()

    if args.planner:
        os.environ["PLANNER"] = args.planner
    vault: dict[str, Any] = {}
    if args.vault:
        with open(args.vault, encoding="utf-8") as fh:
            vault = json.load(fh)
    result = run(
        RunRequest(
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
        )
    )
    if args.json:
        print(RESULT_MARKER + json.dumps(asdict(result)))


if __name__ == "__main__":
    main()
