"""Execute one planner action against the page, by stable ref.

Supported actions (the planner returns exactly one as JSON):
  {"action": "click", "ref": 12}
  {"action": "type",  "ref": 5, "text": "{{vault.email}}"}
  {"action": "select","ref": 8, "text": "California"}
  {"action": "scroll","direction": "down"}
  {"action": "goto",  "url": "https://..."}
  {"action": "wait"}
  {"action": "done",  "reason": "order confirmation shown"}
  {"action": "handoff","reason": "OTP required"}

Placeholders like {{vault.card_number}} are substituted here (not by the LLM), so
secrets never enter the model context.
"""

import contextlib
import re

from app.agent.vault import Vault

_PLACEHOLDER = re.compile(r"\{\{\s*vault\.([a-zA-Z0-9_.]+)\s*\}\}")


class UnknownVaultKey(ValueError):
    """The planner referenced a vault key that does not exist.

    Substituting "" instead used to leave the field silently empty, and the planner retyped the
    same placeholder until the loop guard killed the run. The message goes back to the planner.
    """


def _resolve(text: str | None, vault: Vault) -> str | None:
    if not text:
        return text

    def repl(m):
        key = m.group(1)
        if key not in vault.planner_keys():
            raise UnknownVaultKey(
                f"vault key {key!r} does not exist; use one of: {', '.join(vault.planner_keys())}"
            )
        return str(vault.get(key))

    return _PLACEHOLDER.sub(repl, text)


def _fill(page, ref, text, vault):
    loc = _locator(page, ref)
    loc.fill("")  # fill() focuses the field; a separate click can time out
    loc.type(_resolve(text or "", vault), delay=25)


def _locator(page, ref):
    return page.locator(f'[data-agent-ref="{ref}"]').first


def _click(page, ref):
    """Click by ref, degrading gracefully. Some elements (notably icon <a> links
    like a cart button) fail Playwright's actionability wait under Camoufox even
    though they're clickable; fall back to scroll -> force click -> DOM click so
    the loop never stalls retrying the same click."""
    loc = _locator(page, ref)
    try:
        loc.click(timeout=6000)
        return
    except Exception:
        pass
    with contextlib.suppress(Exception):
        loc.scroll_into_view_if_needed(timeout=2000)
    try:
        loc.click(timeout=3000, force=True)
        return
    except Exception:
        loc.evaluate("el => el.click()")


def act(browser, action, vault):
    page = browser.page
    kind = action.get("action")

    if kind == "click":
        _click(page, action["ref"])
    elif kind == "type":
        _fill(page, action["ref"], action.get("text", ""), vault)
    elif kind == "fill_form":
        # Many text fields in ONE planner step: a 6-passenger form is 13 fields, i.e. 13
        # planner calls (~2 minutes on the CLI planner) when filled one by one.
        fields = action.get("fields") or []
        if not fields:
            raise ValueError("fill_form needs a non-empty 'fields' list of {ref, text}")
        for field in fields:
            _fill(page, field["ref"], field.get("text", ""), vault)
    elif kind == "select":
        loc = _locator(page, action["ref"])
        val = (_resolve(action.get("text", ""), vault) or "").strip()
        if not val:
            raise ValueError(
                "select needs a non-empty 'text' — pick one of the option labels shown"
            )
        try:
            loc.select_option(label=val, timeout=6000)
        except Exception:
            loc.select_option(value=val, timeout=6000)
    elif kind == "press":
        page.keyboard.press(action.get("text") or "Enter")
    elif kind == "click_xy":
        # normalized 0-1000 coords -> CSS pixels (DPR-independent: fraction of the
        # viewport the screenshot was taken at). Lets the planner click things it
        # SEES but that have no stable DOM ref (custom dropdowns, tiles, canvas).
        vw = page.evaluate("window.innerWidth") or 1280
        vh = page.evaluate("window.innerHeight") or 800
        cx = max(0, min(vw - 1, (action.get("x") or 0) / 1000 * vw))
        cy = max(0, min(vh - 1, (action.get("y") or 0) / 1000 * vh))
        page.mouse.click(cx, cy)
    elif kind == "scroll":
        dy = -800 if action.get("direction") == "up" else 800
        page.mouse.wheel(0, dy)
    elif kind == "goto":
        browser.goto(action["url"])
        return
    elif kind == "wait":
        page.wait_for_timeout(min(int(action.get("ms") or 0), 5000))
    elif kind in ("done", "handoff"):
        pass
    else:
        raise ValueError(f"unknown action: {kind}")

    browser.settle()
