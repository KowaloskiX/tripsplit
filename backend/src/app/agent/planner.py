"""The decide step: page state + goal -> exactly one next action (JSON).

The prompt, the action schema and the parsing are shared; only `_complete()` differs per
backend. Select one with `PLANNER=`:

  openai      the OpenAI API (`OPENAI_API_KEY`, `OPENAI_BASE_URL` for compatible endpoints)
  claude-cli  Claude Code in non-interactive mode (`claude -p`) — runs on a Claude subscription,
              no API key. Dev/demo only: it is a consumer subscription, not a production backend.
  manual      actions are read from stdin — a human (or an assistant driving the terminal) is
              the planner. Used to record trajectories and write supplier playbooks.

The planner is given vault KEY NAMES (never values) and told to emit `{{vault.<key>}}`
placeholders for anything sensitive; `act.py` substitutes real values at action time.
"""

import base64
import json
import os
import subprocess
import sys
import time
from typing import Any

SYSTEM = """You are the planner for an autonomous booking agent driving a real browser for a group trip.
Your job: get the requested train / stay / activity to a completed (or ready-to-submit) checkout.

You are given a SCREENSHOT of the current page, a compact list of INTERACTIVE ELEMENTS
(each with a #ref), and the page text. LOOK AT THE SCREENSHOT FIRST, then act.
Return EXACTLY ONE action as a single JSON object, nothing else. Valid actions:
  {"action":"click","ref":N}
  {"action":"type","ref":N,"text":"..."}      # for a single form field
  {"action":"fill_form","fields":[{"ref":N,"text":"..."},...]}  # several text fields at once
  {"action":"select","ref":N,"text":"Label"}  # for a native <select>
  {"action":"press","text":"Enter"}           # press a key on the focused field (e.g. Enter to submit a search)
  {"action":"click_xy","x":0,"y":0}           # click a point you SEE; x,y are 0-1000 (fraction of screenshot w/h). Use when the target has no #ref.
  {"action":"scroll","direction":"down|up"}
  {"action":"goto","url":"https://..."}
  {"action":"wait"}                            # let the page settle, then re-observe
  {"action":"done","reason":"..."}             # goal reached (confirmation OR ready-to-submit if stop_before_pay)
  {"action":"handoff","reason":"..."}          # a human is required (OTP, captcha, login you can't complete)

Rules:
- For sensitive values use placeholders, NEVER literals: e.g. {"action":"type","ref":4,"text":"{{vault.email}}"}.
  The available vault keys are listed in the user message. Login username/password are {{vault.username}} / {{vault.password}}.
- Prefer testid/aria labels to guess intent. One logical step at a time.
- Prefer #ref actions. For something you can SEE but that has NO usable #ref (an option inside a custom dropdown/flyout, a date tile, a canvas control), use click_xy with x,y as integers 0-1000 (fraction of image width/height). A fresh screenshot follows every action so you can verify it worked.
- When several text fields are visible (passenger names, contact details), fill them ALL in one fill_form action — one entry per field, a SINGLE value per field. NEVER concatenate multiple values into one field. Use only vault keys that are listed; never invent key names.
- Check RECENT ACTIONS: if you already typed a value into a field, do not type it again — move to the next field or the next step (e.g. click Continue). Never repeat the exact same action.
- Dismiss nothing manually — banners are handled for you. Focus on the booking path.
- If stop_before_pay is set, do NOT submit the final order; call done once the summary page is fully populated and matches the goal.
- If you see a booking number / "thank you" / confirmation, call done.
- If you hit a captcha, OTP/2FA, SMS code, BLIK code, or 3-D Secure, call handoff — you cannot solve those.
- Always set "milestone" to the checkout phase of the CURRENT page (browsing, search, results, cart, account, passengers, address, delivery, payment, review, done, blocked) so progress can be tracked.
Think silently; output ONLY the JSON object."""

# Strict schema so the model always returns exactly this shape. Optional fields are nullable
# (OpenAI strict mode requires every property in `required`).
ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "click",
                "type",
                "fill_form",
                "select",
                "press",
                "click_xy",
                "scroll",
                "goto",
                "wait",
                "done",
                "handoff",
            ],
        },
        "ref": {"type": ["integer", "null"]},
        "fields": {
            "type": ["array", "null"],
            "description": "fill_form only: one {ref, text} per text field",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"ref": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["ref", "text"],
            },
        },
        "text": {"type": ["string", "null"]},
        "direction": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
        "x": {
            "type": ["integer", "null"],
            "description": "click_xy horizontal, 0-1000 fraction of screenshot width",
        },
        "y": {
            "type": ["integer", "null"],
            "description": "click_xy vertical, 0-1000 fraction of screenshot height",
        },
        "milestone": {
            "type": ["string", "null"],
            "description": "checkout phase of the CURRENT page: browsing|search|results|cart|account|passengers|address|delivery|payment|review|done|blocked",
        },
    },
    "required": [
        "action",
        "ref",
        "fields",
        "text",
        "direction",
        "url",
        "reason",
        "x",
        "y",
        "milestone",
    ],
}


MACRO_ADDENDUM = """

MACRO MODE: instead of a single action, return {"actions":[...], "milestone":"..."} — a SHORT
PLAN of 1 to {max_actions} actions to perform IN ORDER on the CURRENT page, each in the action
format above (e.g. a fill_form of every visible field followed by the click on Continue).
Each action is validated against the page before it runs; the plan is cut at the first one
that no longer matches. End the plan at the first action that navigates or reloads the page.
done / handoff may only be the LAST action of a plan."""

# Macro plan: up to N actions on the current page, each in the single-action shape.
PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "actions": {"type": "array", "items": None},  # filled below with ACTION_SCHEMA
        "milestone": {"type": ["string", "null"]},
    },
    "required": ["actions", "milestone"],
}
PLAN_SCHEMA["properties"]["actions"]["items"] = ACTION_SCHEMA


class PlannerUnavailable(RuntimeError):
    """The model backend refused (rate limit, spend cap, auth): retrying will not help."""


_LIMIT_HINTS = (
    "429",
    "rate limit",
    "rate_limit",
    "usage limit",
    "limit reached",
    "spend limit",
    "quota",
    "overloaded",
)


def _is_limit(detail: str) -> bool:
    low = (detail or "").lower()
    return any(h in low for h in _LIMIT_HINTS)


def macro_enabled() -> bool:
    return os.getenv("PLANNER_MACRO", "1") != "0"


def macro_max_actions() -> int:
    try:
        return max(1, int(os.getenv("PLANNER_MAX_PLAN", "4")))
    except ValueError:
        return 4


def make_planner(max_calls=None):
    """Pick the backend from `PLANNER` (default: openai); `none` disables the LLM."""
    kind = (os.getenv("PLANNER") or "openai").lower()
    planner = _make(kind)
    planner.max_calls = max_calls
    return planner


def _make(kind):
    if kind in ("none", "off", "disabled"):
        return NullPlanner()
    if kind == "openai":
        return OpenAIPlanner()
    if kind in ("claude-cli", "claude"):
        return ClaudeCliPlanner()
    if kind == "manual":
        return ManualPlanner()
    raise ValueError(f"unknown PLANNER={kind!r}; use openai | claude-cli | manual")


class BasePlanner:
    enabled = True

    def __init__(self) -> None:
        self.tokens = {"in": 0, "out": 0, "total": 0}  # cumulative usage
        self.calls = 0
        self.max_calls: int | None = None  # a hard cap on model calls for this run; None = unlimited

    def budget_left(self):
        return self.max_calls is None or self.calls < self.max_calls

    def next_plan(
        self,
        goal: str,
        stop_before_pay: bool,
        page_render: str,
        vault_keys: list[str],
        history: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """A short plan (list of actions) for the current page — macro mode — or one action.

        Never exceeds `max_calls`: past the cap it returns a handoff without calling a model.
        """
        if not self.budget_left():
            return [
                {
                    "action": "handoff",
                    "reason": f"LLM call budget exhausted ({self.max_calls} calls)",
                    "milestone": "blocked",
                }
            ]
        macro = macro_enabled()
        raw = self.next_action(
            goal, stop_before_pay, page_render, vault_keys, history, _macro=macro, **kwargs
        )
        if not macro or not isinstance(raw.get("actions"), list):
            return [raw]
        plan = [_sanitize(a) for a in raw["actions"] if isinstance(a, dict) and a.get("action")]
        plan = plan[: macro_max_actions()] or [{"action": "wait"}]
        for action in plan:
            action.setdefault("milestone", raw.get("milestone"))
            if not action.get("milestone"):
                action["milestone"] = raw.get("milestone")
        # done / handoff end a plan.
        for i, action in enumerate(plan):
            if action.get("action") in ("done", "handoff"):
                return plan[: i + 1]
        return plan

    def next_action(
        self,
        goal,
        stop_before_pay,
        page_render,
        vault_keys,
        history,
        screenshot_png=None,
        screenshot_path=None,
        site_notes="",
        preferences="",
        hint="",
        _macro=False,
    ):
        # No str.format here: SYSTEM contains literal JSON braces and {{vault.x}} placeholders
        # that must reach the model verbatim (act.py matches {{...}}).
        notes = (
            f"SITE NOTES for this host (a trusted playbook — follow it):\n{site_notes}\n\n"
            if site_notes
            else ""
        )
        prefs = (
            f"USER PREFERENCES (honor these when a page offers a choice, e.g. class, "
            f"cancellation policy, payment method — pick the matching option; if none "
            f"matches, pick the closest sensible one): {preferences}\n\n"
            if preferences
            else ""
        )
        rule_note = f"RULE LAYER (deterministic, could not decide): {hint}\n\n" if hint else ""
        has_shot = bool(screenshot_png or screenshot_path)
        ask = "the plan" if _macro else "the single next action"
        user = (
            f"GOAL: {goal}\n"
            f"stop_before_pay: {stop_before_pay}\n\n"
            f"{prefs}"
            f"{notes}"
            f"AVAILABLE VAULT KEYS: {', '.join(vault_keys)}\n\n"
            f"RECENT ACTIONS: {json.dumps(history[-6:])}\n\n"
            f"{rule_note}"
            f"CURRENT PAGE:\n{page_render}\n\n"
            + (
                f"Look at the screenshot, then return {ask} as JSON."
                if has_shot
                else f"Return {ask} as JSON."
            )
        )
        system = SYSTEM
        if _macro:
            system += MACRO_ADDENDUM.replace("{max_actions}", str(macro_max_actions()))
        self.calls += 1
        self.macro = _macro
        return _sanitize(self._complete(system, user, screenshot_png, screenshot_path))

    def schema(self):
        return PLAN_SCHEMA if getattr(self, "macro", False) else ACTION_SCHEMA

    def _complete(self, system, user, screenshot_png, screenshot_path):
        raise NotImplementedError


class NullPlanner(BasePlanner):
    """No model at all: the deterministic layers must carry the run (evals, `--mode rules`).

    Asking it for a plan is not an LLM call; it answers a handoff explaining why.
    """

    enabled = False

    def next_plan(
        self,
        goal: str,
        stop_before_pay: bool,
        page_render: str,
        vault_keys: list[str],
        history: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        hint = kwargs.get("hint") or "no rule matched"
        return [
            {
                "action": "handoff",
                "reason": f"no deterministic action and the LLM is disabled ({hint})",
                "milestone": "blocked",
            }
        ]

    def _complete(self, system, user, screenshot_png, screenshot_path):
        raise PlannerUnavailable("the LLM planner is disabled")


class OpenAIPlanner(BasePlanner):
    """The OpenAI API — or any OpenAI-compatible endpoint via OPENAI_BASE_URL."""

    def __init__(self) -> None:
        super().__init__()
        self.model = os.getenv("PLANNER_MODEL", "gpt-5.5")
        # reasoning_effort keeps per-step latency sane over a long loop; "low" is plenty for
        # "pick the next action". Set PLANNER_EFFORT="" to omit it.
        self.effort = os.getenv("PLANNER_EFFORT", "low") or None
        from openai import OpenAI

        self.client = OpenAI()  # OPENAI_API_KEY / OPENAI_BASE_URL from the environment

    def _complete(self, system, user, screenshot_png, screenshot_path):
        if screenshot_png:
            data_url = "data:image/png;base64," + base64.b64encode(screenshot_png).decode()
            detail = os.getenv("PLANNER_IMAGE_DETAIL", "low")
            user_content = [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": data_url, "detail": detail}},
            ]
        else:
            user_content = user
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "action", "strict": True, "schema": self.schema()},
            },
            max_completion_tokens=2000,
        )
        if self.effort:
            kwargs["reasoning_effort"] = self.effort
        # Retry transient API failures so a single hiccup doesn't kill a long run. The first
        # retry also drops reasoning_effort in case a non-reasoning model rejected it.
        resp, last_err = None, None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                last_err = e
                if _is_limit(str(e)):
                    raise PlannerUnavailable(str(e)[-400:]) from e
                kwargs.pop("reasoning_effort", None)
                time.sleep(1.5 * (attempt + 1))
        if resp is None:
            raise last_err
        try:
            u = resp.usage
            self.tokens["in"] += u.prompt_tokens or 0
            self.tokens["out"] += u.completion_tokens or 0
            self.tokens["total"] += u.total_tokens or 0
        except Exception:
            pass
        return _parse(resp.choices[0].message.content)


class ClaudeCliPlanner(BasePlanner):
    """Claude Code in non-interactive mode: `claude -p ... --output-format json`.

    The screenshot is passed as a FILE PATH and Claude reads it with its Read tool (the only
    tool allowed). No other tools, no session persistence — one isolated call per step.
    """

    def __init__(self) -> None:
        super().__init__()
        self.binary = os.getenv("CLAUDE_BIN", "claude")
        self.model = os.getenv("PLANNER_MODEL", "sonnet")
        self.timeout = int(os.getenv("PLANNER_TIMEOUT_S", "120"))

    def _complete(self, system, user, screenshot_png, screenshot_path):
        if screenshot_path:
            user = f"First, Read the screenshot file at: {screenshot_path}\n\n{user}"
        cmd = [
            self.binary,
            "-p",
            user,
            "--output-format",
            "json",
            "--model",
            self.model,
            "--system-prompt",
            system,
            "--allowed-tools",
            "Read",
            # Schema-validated output: the CLI returns the action in `structured_output`, so a
            # model that "thinks out loud" around its JSON cannot derail parsing.
            "--json-schema",
            json.dumps(self.schema()),
            "--no-session-persistence",
        ]
        last_err = None
        for attempt in range(3):
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=os.path.dirname(screenshot_path) if screenshot_path else None,
                )
                if proc.returncode != 0:
                    # Claude Code reports API failures (429 spend limit, auth) in the JSON
                    # envelope on stdout, with an empty stderr.
                    detail = proc.stderr.strip() or _envelope_error(proc.stdout)
                    if _is_limit(detail):
                        raise PlannerUnavailable(detail[-400:])
                    raise RuntimeError(detail[-400:] or f"exit {proc.returncode}")
                envelope = json.loads(proc.stdout)
                usage = envelope.get("usage") or {}
                self.tokens["in"] += int(usage.get("input_tokens") or 0)
                self.tokens["out"] += int(usage.get("output_tokens") or 0)
                self.tokens["total"] = self.tokens["in"] + self.tokens["out"]
                structured = envelope.get("structured_output")
                if isinstance(structured, dict) and (
                    structured.get("action") or isinstance(structured.get("actions"), list)
                ):
                    return structured
                return _parse(envelope.get("result") or "")
            except PlannerUnavailable:
                raise
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise last_err


class ManualPlanner(BasePlanner):
    """A human is the planner: the page render goes to stdout, the action comes from stdin.

    Used to RECORD a trajectory for a supplier (replayed later with no model at all) and to
    write its playbook while watching how the site behaves.
    """

    def _complete(self, system, user, screenshot_png, screenshot_path):
        print("\n" + "=" * 78, file=sys.stderr)
        if screenshot_path:
            print(f"SCREENSHOT: {screenshot_path}", file=sys.stderr)
        print(user, file=sys.stderr)
        print("-" * 78, file=sys.stderr)
        print("action JSON> ", end="", file=sys.stderr, flush=True)
        line = sys.stdin.readline()
        if not line:
            return {"action": "handoff", "reason": "stdin closed"}
        return _parse(line.strip())


def _sanitize(action):
    # Guard against a model degenerating into a runaway repeated string in a type/select
    # field — cap it so we never dump a huge blob into an input.
    t = action.get("text")
    if action.get("action") in ("type", "select") and isinstance(t, str) and len(t) > 100:
        action["text"] = t[:100]
    return action


def _envelope_error(stdout):
    """The `result` text of a Claude Code JSON envelope, or "" when there is none."""
    try:
        envelope = json.loads(stdout or "")
    except ValueError:
        return ""
    return str(envelope.get("result") or "") if isinstance(envelope, dict) else ""


def _parse(text):
    """The LAST JSON object with an "action" key in free text, else a harmless `wait`.

    A greedy `{.*}` used to swallow prose containing braces (e.g. a mentioned
    `{{vault.email}}`) and fail, so every step degraded into `wait` until the loop guard fired.
    """
    if not text:
        return {"action": "wait"}
    decoder = json.JSONDecoder()
    found = None
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        try:
            candidate, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(candidate, dict) and (
            candidate.get("action") or isinstance(candidate.get("actions"), list)
        ):
            found = candidate
    return found or {"action": "wait"}
