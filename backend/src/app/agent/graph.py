"""A run's plan as a typed graph the UI can draw and light up, node by node.

`runs/<id>/flow_graph.json` = {"nodes": [...], "edges": [...]}. Each node is
{id, type, stage, label, inputs, outputs}: `type` is one of open_url | fill | choose | click |
loop | verify | approve; `inputs` are VARIABLE NAMES (`vault.passenger_{i}_first_name`,
`goal.date`) — never values. With a flow, nodes are its steps; without one, a generic
checkout skeleton keyed by stage. `status.json.steps[*].node_id` points into this graph.
"""

import re
from enum import StrEnum
from itertools import pairwise
from typing import Any

from app.agent.site_profiles import Stage

_VAR = re.compile(r"\{\{\s*((?:vault|goal)\.[a-zA-Z0-9_{}]+)\s*\}\}")


class NodeType(StrEnum):
    OPEN_URL = "open_url"
    FILL = "fill"
    CHOOSE = "choose"
    CLICK = "click"
    LOOP = "loop"
    VERIFY = "verify"
    APPROVE = "approve"


def _vars(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        for name in _VAR.findall(str(value or "")):
            if name not in out:
                out.append(name)
    return out


def _node(
    node_id: str,
    kind: NodeType,
    stage: str | None,
    label: str,
    inputs: list[str],
    outputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": kind.value,
        "stage": stage,
        "label": label,
        "inputs": inputs,
        "outputs": outputs or [],
    }


def _verify_and_approve() -> list[dict[str, Any]]:
    return [
        _node(
            "verify",
            NodeType.VERIFY,
            Stage.REVIEW.value,
            "Verify the supplier summary",
            ["goal.passengers", "goal.date", "goal.train", "goal.budget"],
            ["summary"],
        ),
        _node("approve", NodeType.APPROVE, Stage.REVIEW.value, "Human approves", ["summary"]),
    ]


def _step_node(index: int, step: dict[str, Any]) -> dict[str, Any]:
    kind = step.get("action")
    stage = step.get("milestone")
    node_id = f"s{index}"
    target = step.get("target") or {}
    label = str(target.get("label") or target.get("text") or target.get("name") or kind)
    if kind == "fill_form":
        items = step.get("items") or []
        loops = [i for i in items if i.get("loop")]
        if loops:
            inputs = _vars(*(b.get("value") for i in loops for b in i.get("body") or []))
            inputs += _vars(*(i.get("value") for i in items if not i.get("loop")))
            return _node(node_id, NodeType.LOOP, stage, "Fill every passenger", inputs)
        return _node(
            node_id, NodeType.FILL, stage, "Fill the form", _vars(*(i.get("value") for i in items))
        )
    if kind in ("type", "select"):
        return _node(node_id, NodeType.FILL, stage, label, _vars(step.get("value")))
    if step.get("choice") == "offer":
        return _node(node_id, NodeType.CHOOSE, stage, "Choose the offer", ["goal.train"])
    if kind == "goto":
        return _node(node_id, NodeType.OPEN_URL, stage, str(step.get("url") or ""), [])
    return _node(node_id, NodeType.CLICK, stage, label, [])


def _chain(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    edges = [{"from": a["id"], "to": b["id"]} for a, b in pairwise(nodes)]
    return {"nodes": nodes, "edges": edges}


def flow_graph(flow: dict[str, Any]) -> dict[str, Any]:
    nodes = [_node("open", NodeType.OPEN_URL, None, "Open the supplier", [], ["page"])]
    nodes += [_step_node(i, s) for i, s in enumerate(flow.get("steps") or [])]
    return {**_chain(nodes + _verify_and_approve()), "source": "flow"}


def generic_graph() -> dict[str, Any]:
    nodes = [
        _node("open", NodeType.OPEN_URL, None, "Open the supplier", [], ["page"]),
        _node(
            "search", NodeType.FILL, Stage.SEARCH.value, "Search", ["goal.date", "goal.passengers"]
        ),
        _node("choose", NodeType.CHOOSE, Stage.RESULTS.value, "Choose the offer", ["goal.train"]),
        _node(
            "passengers",
            NodeType.LOOP,
            Stage.PASSENGERS.value,
            "Fill every passenger",
            ["vault.passenger_{i}_first_name", "vault.passenger_{i}_last_name", "vault.email"],
        ),
    ]
    return {**_chain(nodes + _verify_and_approve()), "source": "generic"}


def node_for(graph: dict[str, Any], stage: str, action: dict[str, Any]) -> str | None:
    """The graph node a non-flow step belongs to: by stage, then by kind."""
    kind = action.get("action")
    if kind in ("done", "handoff") and stage == Stage.REVIEW.value:
        return "verify"
    in_stage = [n for n in graph["nodes"] if n.get("stage") == stage]
    wanted = {
        "fill_form": (NodeType.LOOP.value, NodeType.FILL.value),
        "type": (NodeType.FILL.value,),
        "select": (NodeType.FILL.value,),
        "click": (
            (NodeType.CHOOSE.value,) if action.get("choice") == "offer" else (NodeType.CLICK.value,)
        ),
    }.get(str(kind), ())
    for node in in_stage:
        if node["type"] in wanted:
            return str(node["id"])
    return str(in_stage[0]["id"]) if in_stage else None
