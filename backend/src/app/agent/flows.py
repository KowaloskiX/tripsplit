"""Parametrised flows: a successful run compiled into a replayable PROGRAM, not a tape.

A raw trajectory (`trajectory.py`) replays literal steps: the recorded date, the recorded
party size, the recorded train and exactly the recorded passenger fields. Recorded with six
passengers, it breaks on a purchase of three. A flow fixes that by compiling the run:

  - every target is a stable DESCRIPTOR (role, accessible name, form name/id, testid, row
    context) — never the ephemeral `data-agent-ref`;
  - values are BOUND to variables: `{{vault.passenger_{i}_first_name}}`, `{{goal.date}}`,
    `{{goal.passengers}}`; a literal equal to a vault value is replaced by its placeholder;
  - a repeated per-passenger block of fields is recognised as a LOOP over passengers
    (the descriptor's index is templated too: `p3_first` -> `p{i}_first`), so a flow
    recorded for 6 replays for 1..9;
  - "pick one of N offers" is recorded as a CHOICE resolved from the goal at replay time,
    so a flow recorded on train A books train B when the goal says so.

Replay walks the steps with a cursor. A step whose target cannot be resolved is a MISS: the
runner asks the rule layer (then the planner) for that one step — self-heal — and the cursor
resynchronises by checkout stage. A run that healed is re-compiled and saved.

On disk: `trajectories/<host>.flow.json` (`version: 2`). A legacy `<host>.json` raw trajectory
is still loaded and compiled on the fly, so existing caches keep working.
"""

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.goal import GoalSpec
from app.agent.paths import trajectories_dir
from app.agent.rules import FieldKind, choose_offer, classify_field, vault_placeholder
from app.agent.site_profiles import SiteProfile, Stage
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
# Actions that leave the page as it is, so the next step can run on the same observation.
_BATCHABLE = ("fill_form", "type", "select")
_STAGE_ORDER = {
    Stage.CONSENT: 0,
    Stage.SEARCH: 1,
    Stage.RESULTS: 2,
    Stage.PASSENGERS: 3,
    Stage.REVIEW: 4,
    Stage.CONFIRMATION: 5,
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
    if (goal and goal.date and text == goal.date) or (
        _ISO_DATE.match(text) and kind is FieldKind.TRAVEL_DATE
    ):
        return "{{goal.date}}"
    if text.isdigit() and int(text) == party and kind is FieldKind.PARTY_SIZE:
        return "{{goal.passengers}}"
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


def _compile_fields(fields: list[dict[str, Any]], bind: Callable[..., str | None]) -> list[Step]:
    """Fields -> items; an index-templated per-passenger block becomes one LOOP item."""
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
    if indices == list(range(1, len(indices) + 1)) and len(shapes) == 1:
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
            items = _compile_fields(r.get("fields") or [], bind)
            if items:
                steps.append({**base, "items": items})
            continue
        desc = r.get("desc") or {}
        step = {**base, "target": desc, "value": bind(r.get("text"), desc)}
        if r.get("choice") == "offer" or (
            kind == "click"
            and (r.get("milestone") == "results" or _OFFER_TEXT.search(desc.get("text", "")))
        ):
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


def load(url: str) -> dict[str, Any] | None:
    """The flow for this URL's host; a legacy raw trajectory is compiled on the fly."""
    host = _host(url)
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
    host = _host(url)
    if not host or not flow.get("steps"):
        return None
    os.makedirs(trajectories_dir(), exist_ok=True)
    path = _flow_path(host)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(flow, fh, ensure_ascii=False, indent=1)
    return path
