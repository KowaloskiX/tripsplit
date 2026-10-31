"""The decide step: page state + goal -> exactly one next action (JSON).

Backend is OpenAI. The planner only needs to return a single JSON action object,
so swapping providers (or back to Anthropic) means rewriting only `_complete()` —
the SYSTEM prompt, schema, and `next_action()` interface stay put. It is given
vault KEY NAMES (never values) and told to emit {{vault.<key>}} placeholders for
anything sensitive; harness/act.py substitutes real values at action time.
"""

import base64
import json
import os
import re
import time

SYSTEM = """You are the planner for an autonomous purchasing agent driving a real browser.
Your job: get the target product to a completed (or ready-to-submit) checkout.

You are given a SCREENSHOT of the current page, a compact list of INTERACTIVE ELEMENTS
(each with a #ref), and the page text. LOOK AT THE SCREENSHOT FIRST, then act.
Return EXACTLY ONE action as a single JSON object, nothing else. Valid actions:
  {"action":"click","ref":N}
  {"action":"type","ref":N,"text":"..."}      # for form fields
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
- Prefer #ref actions. For something you can SEE but that has NO usable #ref (an option inside a custom dropdown/flyout, a size tile, a canvas control), use click_xy with x,y as integers 0-1000 (fraction of image width/height). A fresh screenshot follows every action so you can verify it worked.
- Fill ONE field per step with a SINGLE value. NEVER concatenate multiple values into one field.
- Check RECENT ACTIONS: if you already typed a value into a field, do not type it again — move to the next field or the next step (e.g. click Continue). Never repeat the exact same action.
- Dismiss nothing manually — banners are handled for you. Focus on the purchase path.
- If stop_before_pay is set, do NOT submit the final order; call done once the review page is fully populated.
- If you see an order number / "thank you" / confirmation, call done.
- If you hit a captcha, OTP/2FA, SMS code, or 3-D Secure, call handoff — you cannot solve those.
- Always set "milestone" to the checkout phase of the CURRENT page (browsing, cart, account, address, delivery, payment, review, done, blocked) so progress can be tracked.
Think silently; output ONLY the JSON object."""

# Strict schema so the model always returns exactly this shape. Optional fields
# are nullable (OpenAI strict mode requires every property in `required`).
ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "click",
                "type",
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
            "description": "checkout phase of the CURRENT page: browsing|cart|account|address|delivery|payment|review|done|blocked",
        },
    },
    "required": ["action", "ref", "text", "direction", "url", "reason", "x", "y", "milestone"],
}


class Planner:
    def __init__(self):
        self.model = os.getenv("PLANNER_MODEL", "gpt-5.5")
        # reasoning_effort keeps per-step latency sane over a long loop; "low" is
        # plenty for "pick the next action". Set PLANNER_EFFORT="" to omit it.
        env_effort = os.getenv("PLANNER_EFFORT", "low")
        self.effort = env_effort or None
        from openai import OpenAI

        self.client = OpenAI()  # reads OPENAI_API_KEY from the environment
        self.tokens = {"in": 0, "out": 0, "total": 0}  # cumulative planner usage
        self.calls = 0

    def next_action(
        self,
        goal,
        stop_before_pay,
        page_render,
        vault_keys,
        history,
        screenshot_png=None,
        site_notes="",
        preferences="",
    ):
        # No str.format here: SYSTEM contains literal JSON braces and {{vault.x}}
        # placeholders that must reach the model verbatim (act.py matches {{...}}).
        notes = (
            f"SITE NOTES for this host (a trusted playbook — follow it):\n{site_notes}\n\n"
            if site_notes
            else ""
        )
        prefs = (
            f"USER PREFERENCES (honor these when a page offers a choice, e.g. delivery "
            f"method or payment method — pick the option matching the preference; if none "
            f"matches, pick the closest sensible one): {preferences}\n\n"
            if preferences
            else ""
        )
        user = (
            f"GOAL: {goal}\n"
            f"stop_before_pay: {stop_before_pay}\n\n"
            f"{prefs}"
            f"{notes}"
            f"AVAILABLE VAULT KEYS: {', '.join(vault_keys)}\n\n"
            f"RECENT ACTIONS: {json.dumps(history[-6:])}\n\n"
            f"CURRENT PAGE:\n{page_render}\n\n"
            "Look at the screenshot, then return the single next action as JSON."
        )
        return self._complete(SYSTEM, user, screenshot_png)

    # ---- the only provider-specific code ------------------------------------
    def _complete(self, system, user, screenshot_png=None):
        if screenshot_png:
            data_url = "data:image/png;base64," + base64.b64encode(screenshot_png).decode()
            user_content = [
                {"type": "text", "text": user},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url,
                        "detail": os.getenv("PLANNER_IMAGE_DETAIL", "low"),
                    },
                },
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
                "json_schema": {"name": "action", "strict": True, "schema": ACTION_SCHEMA},
            },
            max_completion_tokens=2000,
        )
        if self.effort:
            kwargs["reasoning_effort"] = self.effort
        # Retry transient API failures (connection blips, 5xx, rate spikes) so a
        # single hiccup doesn't kill a long checkout run. First retry also drops
        # reasoning_effort in case a non-reasoning model rejected it.
        resp = None
        last_err = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:
                last_err = e
                kwargs.pop("reasoning_effort", None)
                time.sleep(1.5 * (attempt + 1))
        if resp is None:
            raise last_err
        try:
            u = resp.usage
            self.tokens["in"] += u.prompt_tokens or 0
            self.tokens["out"] += u.completion_tokens or 0
            self.tokens["total"] += u.total_tokens or 0
            self.calls += 1
        except Exception:
            pass
        return self._sanitize(self._parse(resp.choices[0].message.content))

    @staticmethod
    def _sanitize(action):
        # Guard against a model degenerating into a runaway repeated string in a
        # type/select field — cap it so we never dump a huge blob into an input.
        t = action.get("text")
        if action.get("action") in ("type", "select") and isinstance(t, str) and len(t) > 100:
            action["text"] = t[:100]
        return action

    @staticmethod
    def _parse(text):
        if not text:
            return {"action": "wait"}
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                return {"action": "wait"}
            try:
                return json.loads(m.group(0))
            except Exception:
                return {"action": "wait"}
