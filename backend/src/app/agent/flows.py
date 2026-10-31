"""Parametrised flows: a successful run compiled into a replayable program.

Targets are stable descriptors (role, accessible name, form id, testid, row context), values
are bound to variables (`{{vault.passenger_{i}_first_name}}`, `{{goal.date}}`, ...), repeated
passenger blocks become a loop (recorded for 6, replays for 1..9) and "pick one of N offers" is
a choice resolved from the goal. A step whose target is gone is a miss: the rule layer or the
planner heals it and the healed run is re-compiled. Stored as `trajectories/<host>.flow.json`
(version 2); a legacy `<host>.json` trajectory is compiled on load.
"""

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.goal import GoalSpec
from app.agent.paths import trajectories_dir
from app.agent.rules import (
    FieldKind,
    choose_fare,
    choose_offer,
    classify_field,
    vault_placeholder,
)
from app.agent.site_profiles import SiteProfile, Stage, profile_for
from app.agent.trajectory import _goto_is_replayable, _host

FLOW_VERSION = 2
Element = dict[str, Any]
Step = dict[str, Any]

_DESC_KEYS = ("tag", "type", "role", "testid", "id", "name", "label", "text", "href", "context")
# Descriptor keys that may carry a passenger index worth templating.
_INDEXED_KEYS = ("testid", "id", "name", "label", "text", "context")
_PASSENGER_VAR = re.compile(r"\{\{\s*vault\.passenger_(\d+)_([a-z_]+)\s*\}\}")
_ISO_DATE = re.compile(r"^20\d\d-[01]\d-[0-3]\d$")
_OFFER_TEXT = re.compile(r"^(select|wybierz|choose|kup bilet|buy a ticket)\b", re.I)
_ROW_FACT = re.compile(
    r"\b[0-2]?\d:[0-5]\d\b|\d[.,]\d{2}\s*(?:PLN|zł|EUR|CZK|USD)|[$€£]\s?\d", re.I
)
# Actions that leave the page as it is, so the next step can run on the same observation.
_BATCHABLE = ("fill_form", "type", "select")
_STAGE_ORDER = {
    Stage.CONSENT: 0,
    Stage.SEARCH: 1,
    Stage.RESULTS: 2,
    Stage.FARE: 3,
    Stage.PASSENGERS: 4,
    Stage.REVIEW: 5,
    Stage.CONFIRMATION: 6,
}


def descriptor(el: Element | None) -> dict[str, str] | None:
    """Stable fields of an observed element (never the ephemeral ref, never its value)."""
    if not el:
        return None
    return {k: str(el.get(k, "") or "") for k in _DESC_KEYS}


def record_step(action: dict[str, Any], elements: list[Element]) -> Step:
    """A taken action as a raw step: stable descriptors, placeholders kept as placeholders."""
    by_ref = {e.get("ref"): e for e in elements}
    step: Step = {
        "action": action.get("action"),
        "text": action.get("text"),
        "direction": action.get("direction"),
        "url": action.get("url"),
        "milestone": action.get("milestone"),
    }
    if action.get("choice"):
        step["choice"] = action["choice"]
    if action.get("fields"):
        step["fields"] = [
            {"text": f.get("text"), "desc": descriptor(by_ref.get(f.get("ref")))}
            for f in action["fields"]
        ]
    if action.get("ref") is not None:
        step["desc"] = descriptor(by_ref.get(action["ref"]))
    return step


# --------------------------------------------------------------------------- compile


def _template(desc: dict[str, str], index: int) -> dict[str, str]:
    pattern = re.compile(rf"(?<!\d){index}(?!\d)")
    return {
        k: (pattern.sub("{i}", v) if k in _INDEXED_KEYS else v) for k, v in (desc or {}).items()
    }


def _with_role(desc: dict[str, str]) -> dict[str, str]:
    """Legacy descriptors carry no role: derive the implicit one from tag/type."""
    if desc.get("role"):
        return desc
    tag, kind = desc.get("tag", ""), desc.get("type", "")
    role = {"select": "combobox", "textarea": "textbox", "a": "link", "button": "button"}.get(tag)
    if tag == "input":
        role = {"checkbox": "checkbox", "radio": "radio", "submit": "button"}.get(kind, "textbox")
    return {**desc, "role": role or ""}


def _bind_literal(
    text: str | None,
    desc: dict[str, str] | None,
    goal: GoalSpec | None,
    party: int,
    vault_lookup: dict[str, str],
) -> str | None:
    """Replace a literal with a variable when it obviously is one."""
    if not text or "{{" in text:
        return text
    if text in vault_lookup:
        return vault_placeholder(vault_lookup[text])
    role = classify_field(_with_role(desc)) if desc else None
    kind = role.kind if role else None
    if _ISO_DATE.match(text) and kind is FieldKind.RETURN_DATE:
        return "{{goal.return_date}}"
    if (goal and goal.date and text == goal.date) or (
        _ISO_DATE.match(text) and kind is FieldKind.TRAVEL_DATE
    ):
        return "{{goal.date}}"
    if text.isdigit() and int(text) == party and kind is FieldKind.PARTY_SIZE:
        return "{{goal.passengers}}"
    if goal and goal.origin and text.casefold() == goal.origin.casefold():
        return "{{goal.origin}}"
    if goal and goal.destination and text.casefold() == goal.destination.casefold():
        return "{{goal.destination}}"
    return text


def _recorded_party(raw: list[Step], goal: GoalSpec | None) -> int:
    if goal is not None:
        return goal.passengers
    indices = [
        int(m.group(1))
        for step in raw
        for f in step.get("fields") or [step]
        if (m := _PASSENGER_VAR.search(str(f.get("text") or ""))) is not None
    ]
    return max(indices, default=1)


def _compile_fields(
    fields: list[dict[str, Any]], bind: Callable[..., str | None], party: int = 1
) -> list[Step]:
    """Fields -> items; an index-templated per-passenger block becomes one LOOP item.

    Only when the form had a block for EVERY recorded passenger: a single lead-name field on
    a form for a party of 3 stays literal, it must not grow into three fields on replay.
    """
    items: list[Step] = []
    blocks: dict[int, list[Step]] = {}
    loop_at: int | None = None
    for f in fields:
        text = str(f.get("text") or "")
        desc = f.get("desc") or {}
        m = _PASSENGER_VAR.search(text)
        if m is None:
            items.append({"target": desc, "value": bind(text, desc)})
            continue
        index = int(m.group(1))
        if loop_at is None:
            loop_at = len(items)
        blocks.setdefault(index, []).append(
            {
                "target": _template(desc, index),
                "value": _PASSENGER_VAR.sub(r"{{vault.passenger_{i}_\2}}", text),
                "index": index,
            }
        )
    if not blocks:
        return items
    indices = sorted(blocks)
    shapes = {
        json.dumps([[b["target"], b["value"]] for b in blocks[i]], sort_keys=True) for i in indices
    }
    if indices == list(range(1, len(indices) + 1)) and len(shapes) == 1 and len(indices) >= party:
        body = [{"target": b["target"], "value": b["value"]} for b in blocks[1]]
        compiled: list[Step] = [{"loop": "passengers", "body": body}]
    else:
        # Not a clean 1..N repetition (e.g. a page that splits passengers): keep it literal.
        compiled = [
            {
                "target": {k: v.replace("{i}", str(b["index"])) for k, v in b["target"].items()},
                "value": b["value"].replace("{i}", str(b["index"])),
            }
            for i in indices
            for b in blocks[i]
        ]
    return items[:loop_at] + compiled + items[loop_at:]


def _looks_like_offer(raw: Step, desc: dict[str, str]) -> bool:
    """A click that picked one offer of a list (replayed as a choice, not as this element).

    On a results page a click is an offer pick only if the control sits in a row with a time
    or a price — a header "CHANGE" or a filter button on the same page is not.
    """
    if _OFFER_TEXT.search(desc.get("text", "")):
        return True
    context = desc.get("context", "")
    return raw.get("milestone") == "results" and bool(_ROW_FACT.search(context))


def compile_flow(
    raw: list[Step], goal: GoalSpec | None = None, vault_lookup: dict[str, str] | None = None
) -> dict[str, Any]:
    """Raw recorded steps (legacy trajectory format) -> a version-2 flow."""
    party = _recorded_party(raw, goal)
    lookup = vault_lookup or {}

    def bind(text: str | None, desc: dict[str, str] | None) -> str | None:
        return _bind_literal(text, desc, goal, party, lookup)

    steps: list[Step] = []
    for r in raw:
        kind = r.get("action")
        base: Step = {"action": kind, "milestone": r.get("milestone")}
        if kind in ("done", "handoff", "click_xy", None):
            continue
        if kind == "goto":
            if _goto_is_replayable(r.get("url")):
                steps.append({**base, "url": r.get("url")})
            continue
        if kind in ("scroll", "press", "wait"):
            steps.append({**base, "direction": r.get("direction"), "text": r.get("text")})
            continue
        if kind == "fill_form":
            items = _compile_fields(r.get("fields") or [], bind, party)
            if items:
                steps.append({**base, "items": items})
            continue
        desc = r.get("desc") or {}
        step = {**base, "target": desc, "value": bind(r.get("text"), desc)}
        if r.get("choice") == "fare" or r.get("milestone") == Stage.FARE.value:
            step["choice"] = "fare"
        elif r.get("choice") == "offer" or (kind == "click" and _looks_like_offer(r, desc)):
            step["choice"] = "offer"
        steps.append(step)
    return {"version": FLOW_VERSION, "recorded_party": party, "steps": steps}


# --------------------------------------------------------------------------- resolve


def _n(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def resolve(desc: dict[str, str] | None, elements: list[Element]) -> int | None:
    """The CURRENT ref of the unique element matching a descriptor, else None."""
    if not desc:
        return None
    same_kind = [
        e
        for e in elements
        if e.get("tag") == desc.get("tag") or (desc.get("role") and e.get("role") == desc["role"])
    ]

    def uniq(cands: list[Element]) -> int | None:
        if len(cands) > 1 and desc.get("text"):
            narrowed = [e for e in cands if _n(e.get("text")) == _n(desc["text"])]
            cands = narrowed or cands
        return cands[0].get("ref") if len(cands) == 1 else None

    for key in ("testid", "id", "name"):
        if desc.get(key):
            ref = uniq([e for e in same_kind if e.get(key) == desc[key]])
            if ref is not None:
                return ref
    if desc.get("label"):
        ref = uniq([e for e in same_kind if _n(e.get("label")) == _n(desc["label"])])
        if ref is not None:
            return ref
    if desc.get("text"):
        ref = uniq(
            [
                e
                for e in same_kind
                if (e.get("type") or "") == (desc.get("type") or "")
                and _n(e.get("text")) == _n(desc["text"])
            ]
        )
        if ref is not None:
            return ref
    if desc.get("href"):
        return uniq([e for e in elements if e.get("href") == desc["href"]])
    return None


def _instantiate(target: dict[str, str], index: int) -> dict[str, str]:
    return {k: v.replace("{i}", str(index)) for k, v in target.items()}


def _goal_value(value: str | None, goal: GoalSpec) -> str | None:
    if not value:
        return value
    variables = goal.variables()
    return re.sub(
        r"\{\{\s*goal\.([a-z_]+)\s*\}\}", lambda m: variables.get(m.group(1), m.group(0)), value
    )


@dataclass
class FlowPlayer:
    flow: dict[str, Any]
    goal: GoalSpec
    profile: SiteProfile
    cursor: int = 0
    misses: int = 0
    executed: int = 0
    log: list[str] = field(default_factory=list)
    last_indices: list[int] = field(default_factory=list)
    patience_at: int = -1
    patience: int = 0

    @property
    def steps(self) -> list[Step]:
        return list(self.flow.get("steps") or [])

    def finished(self) -> bool:
        return self.cursor >= len(self.steps)

    def _stage_of(self, step: Step) -> Stage | None:
        try:
            stage = Stage(step.get("milestone") or "")
        except ValueError:
            return None
        return stage if stage in _STAGE_ORDER else None

    def _resync(self, current: Stage) -> None:
        """Skip steps that belong to a checkout stage the page is already past."""
        if current not in _STAGE_ORDER:
            return
        while not self.finished():
            stage = self._stage_of(self.steps[self.cursor])
            if stage is None or _STAGE_ORDER[stage] >= _STAGE_ORDER[current]:
                return
            self.log.append(f"skip step {self.cursor} ({stage}) — page is at {current}")
            self.cursor += 1

    def next_actions(self, elements: list[Element], current: Stage) -> list[dict[str, Any]] | None:
        """The next steps for THIS page as executable actions, or None (a miss / the end).

        Consecutive steps of the same stage are batched — fills and selects followed by the
        click that leaves the page — since filling a form does not change what is on it.
        """
        self._resync(current)
        if self.finished():
            return None
        step = self.steps[self.cursor]
        stage = self._stage_of(step)
        if stage is not None and current in _STAGE_ORDER and stage != current:
            self.misses += 1
            self.log.append(f"miss step {self.cursor}: page at {current}, step for {stage}")
            return None
        action = self._resolve_step(step, elements)
        if action is None:
            # Real sites render controls late (after prices load): give the target a few
            # seconds before declaring a miss and handing the page to the rules/planner.
            if self.patience_at != self.cursor:
                self.patience_at, self.patience = self.cursor, 0
            if self.patience < self.profile.target_patience:
                self.patience += 1
                return [{"action": "wait", "ms": 1500, "milestone": step.get("milestone")}]
            self.misses += 1
            self.log.append(f"miss step {self.cursor}: target not found")
            return None
        batch = [action]
        self.last_indices = [self.cursor]
        self.cursor += 1
        while action["action"] in _BATCHABLE and not self.finished():
            step = self.steps[self.cursor]
            if step.get("milestone") != batch[0].get("milestone"):
                break
            nxt = self._resolve_step(step, elements)
            if nxt is None:
                break
            batch.append(nxt)
            self.last_indices.append(self.cursor)
            self.cursor += 1
            action = nxt
        self.executed += len(batch)
        return batch

    def _resolve_step(self, step: Step, elements: list[Element]) -> dict[str, Any] | None:
        kind = step.get("action")
        ms = step.get("milestone")
        if kind == "goto":
            return {"action": "goto", "url": step.get("url"), "milestone": ms}
        if kind in ("scroll", "press", "wait"):
            return {
                "action": kind,
                "direction": step.get("direction"),
                "text": step.get("text"),
                "milestone": ms,
            }
        if kind == "fill_form":
            fields = []
            for item in step.get("items") or []:
                if item.get("loop") == "passengers":
                    for i in range(1, self.goal.passengers + 1):
                        for body in item.get("body") or []:
                            ref = resolve(_instantiate(body["target"], i), elements)
                            if ref is None:
                                return None
                            value = str(body.get("value") or "").replace("{i}", str(i))
                            fields.append({"ref": ref, "text": value})
                    continue
                ref = resolve(item.get("target"), elements)
                if ref is None:
                    return None
                fields.append({"ref": ref, "text": _goal_value(item.get("value"), self.goal)})
            return {"action": "fill_form", "fields": fields, "milestone": ms} if fields else None
        if step.get("choice") == "fare":
            fare = choose_fare(elements, self.goal, self.profile)
            if fare is None:
                return None
            return {"action": "click", "ref": fare["ref"], "milestone": ms, "choice": "fare"}
        if step.get("choice") == "offer":
            offer = choose_offer(elements, self.goal, self.profile)
            if offer is None:
                return None
            return {"action": "click", "ref": offer["ref"], "milestone": ms, "choice": "offer"}
        if kind in ("click", "type", "select"):
            ref = resolve(step.get("target"), elements)
            if ref is None:
                return None
            return {
                "action": kind,
                "ref": ref,
                "text": _goal_value(step.get("value"), self.goal),
                "milestone": ms,
            }
        return None


# --------------------------------------------------------------------------- storage


def _flow_path(host: str) -> str:
    return os.path.join(trajectories_dir(), f"{host}.flow.json")


def _flow_key(url: str) -> str:
    """The URL's host, plus the site profile's scope when it shares the host with another."""
    host = _host(url)
    scope = profile_for(url).flow_scope
    return f"{host}.{scope}" if host and scope else host


def load(url: str) -> dict[str, Any] | None:
    """The flow for this URL's host; a legacy raw trajectory is compiled on the fly."""
    host = _flow_key(url)
    if not host:
        return None
    legacy_path = os.path.join(trajectories_dir(), f"{host}.json")
    for path, legacy in ((_flow_path(host), False), (legacy_path, True)):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            continue
        if legacy and isinstance(data, list) and data:
            return compile_flow(data)
        if isinstance(data, dict) and data.get("version") == FLOW_VERSION and data.get("steps"):
            return data
    return None


def save(url: str, flow: dict[str, Any]) -> str | None:
    host = _flow_key(url)
    if not host or not flow.get("steps"):
        return None
    os.makedirs(trajectories_dir(), exist_ok=True)
    path = _flow_path(host)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(flow, fh, ensure_ascii=False, indent=1)
    return path
