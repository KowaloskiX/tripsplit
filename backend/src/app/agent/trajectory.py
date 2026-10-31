"""Trajectory cache — record a successful action sequence per host, then REPLAY it
on later runs to skip the planner LLM call on steps that still match (token saver).

Two-tier memory with skills.py:
  - skill (.md)      = semantic playbook, used by the planner to self-heal.
  - trajectory (.json) = the winning action sequence, replayed mechanically here.

Refs (data-agent-ref) change every run, so we never cache them. We cache a stable
DESCRIPTOR per element (testid / name / tag+type+text / href) and, at replay time,
resolve it to the CURRENT ref via a unique match. No unique match -> cache "miss"
-> the caller falls back to the planner (self-heal), and the corrected sequence is
re-recorded on success.
"""

import json
import os
from typing import Any
from urllib.parse import urlparse

from app.agent.paths import trajectories_dir

# Terminal / non-portable actions are never replayed blindly.
_NO_REPLAY = ("done", "handoff", "click_xy")

# A cached `goto` is only replayed when it targets a checkout-flow page (cart,
# delivery, payment, order review, login). The run ALWAYS starts on the buyer's
# chosen product URL, so a cached goto to a product / arbitrary page would jump
# to whatever product was recorded — the per-host trajectory otherwise dragged
# every buy back to the first product it ever saw. Path-substring match, PL + EN.
_GOTO_REPLAY_KEYWORDS = (
    "koszyk",
    "cart",
    "basket",
    "checkout",
    "kasa",
    "zamowienie",
    "zamówienie",
    "order",
    "platnosc",
    "płatność",
    "payment",
    "dostawa",
    "transport",
    "delivery",
    "adres",
    "address",
    "podsumowanie",
    "summary",
    "review",
    "logowanie",
    "login",
    "konto",
    "account",
)


def _goto_is_replayable(url):
    """True only for checkout-flow navigations — never a product/arbitrary page."""
    path = urlparse(url or "").path.lower()
    return any(kw in path for kw in _GOTO_REPLAY_KEYWORDS)


def _host(url):
    h = (urlparse(url or "").hostname or "").lower().lstrip(".")
    return h[4:] if h.startswith("www.") else h


def _path(host):
    return os.path.join(trajectories_dir(), f"{host}.json")


def load(url):
    p = _path(_host(url))
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            steps = json.load(f)
        return steps or None
    except (ValueError, OSError):
        return None


def save(url, steps):
    host = _host(url)
    if not host or not steps:
        return None
    os.makedirs(trajectories_dir(), exist_ok=True)
    p = _path(host)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(steps, f, ensure_ascii=False, indent=1)
    return p


def descriptor(el):
    """Stable fields of an observe element (never the ephemeral ref)."""
    if not el:
        return None
    return {k: el.get(k, "") or "" for k in ("tag", "type", "testid", "name", "text", "href")}


def _find_ref(elements, d):
    """Return the CURRENT ref of the unique element matching descriptor d, else None."""
    if not d:
        return None

    def uniq(cands):
        return cands[0].get("ref") if len(cands) == 1 else None

    if d.get("testid"):
        m = [e for e in elements if e.get("testid") == d["testid"]]
        if len(m) > 1:
            m = [e for e in m if e.get("text") == d.get("text")] or m
        r = uniq(m)
        if r is not None:
            return r
    if d.get("name"):
        r = uniq([e for e in elements if e.get("name") == d["name"]])
        if r is not None:
            return r
    if d.get("text"):
        r = uniq(
            [
                e
                for e in elements
                if e.get("tag") == d.get("tag")
                and (e.get("type") or "") == (d.get("type") or "")
                and e.get("text") == d["text"]
            ]
        )
        if r is not None:
            return r
    if d.get("href"):
        r = uniq([e for e in elements if e.get("href") == d["href"]])
        if r is not None:
            return r
    return None


def action_from_cache(
    cached: dict[str, Any], elements: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Turn a cached step into an executable action for the CURRENT page, or None
    (a miss) if it can't be resolved — caller then self-heals via the planner."""
    kind = cached.get("action")
    if kind in _NO_REPLAY:
        return None
    ms = cached.get("milestone")
    if kind == "goto":
        url = cached.get("url")
        if not _goto_is_replayable(url):
            return None  # miss -> planner handles navigation from the real product page
        return {"action": "goto", "url": url, "milestone": ms}
    if kind in ("scroll", "press", "wait"):
        return {
            "action": kind,
            "direction": cached.get("direction"),
            "text": cached.get("text"),
            "milestone": ms,
        }
    if kind == "fill_form":
        fields = []
        for cached_field in cached.get("fields") or []:
            ref = _find_ref(elements, cached_field.get("desc"))
            if ref is None:
                return None
            fields.append({"ref": ref, "text": cached_field.get("text")})
        return {"action": kind, "fields": fields, "milestone": ms} if fields else None
    if kind in ("click", "type", "select"):
        ref = _find_ref(elements, cached.get("desc"))
        if ref is None:
            return None
        return {"action": kind, "ref": ref, "text": cached.get("text"), "milestone": ms}
    return None


def record_step(action: dict[str, Any], elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Capture a taken action as a replayable step (stable descriptor, no live ref)."""
    step = {
        "action": action.get("action"),
        "text": action.get("text"),
        "direction": action.get("direction"),
        "url": action.get("url"),
        "milestone": action.get("milestone"),
    }
    if action.get("fields"):
        step["fields"] = [
            {
                "text": f.get("text"),
                "desc": descriptor(
                    next((e for e in elements if e.get("ref") == f.get("ref")), None)
                ),
            }
            for f in action["fields"]
        ]
    ref = action.get("ref")
    if ref is not None:
        el = next((e for e in elements if e.get("ref") == ref), None)
        step["desc"] = descriptor(el)
    return step
