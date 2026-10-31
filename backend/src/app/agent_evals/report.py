"""The eval report: `report.json` (every case) and `report.md` (tables a human reads)."""

import json
import os
from collections import defaultdict
from typing import Any

from app.agent_evals.harness import CaseResult


def summarise(results: list[CaseResult]) -> dict[str, dict[str, Any]]:
    by_mode: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_mode[r.mode].append(r)
    out: dict[str, dict[str, Any]] = {}
    for mode, rows in by_mode.items():
        passed = sum(r.success for r in rows)
        out[mode] = {
            "cases": len(rows),
            "passed": passed,
            "success_rate": round(passed / len(rows), 3) if rows else 0.0,
            "llm_calls": sum(r.llm_calls for r in rows),
            "mean_seconds": round(sum(r.seconds for r in rows) / len(rows), 2) if rows else 0.0,
            "mean_steps": round(sum(r.steps for r in rows) / len(rows), 2) if rows else 0.0,
            "cost_usd": round(sum(r.cost_usd for r in rows), 5),
        }
    return out


def _markdown(results: list[CaseResult], meta: dict[str, Any]) -> str:
    lines = ["# Agent eval", ""]
    lines += [f"- {k}: `{v}`" for k, v in meta.items()]
    lines += ["", "## Summary", ""]
    lines += ["| mode | passed | success | LLM calls | mean steps | mean s | cost $ |"]
    lines += ["|---|---|---|---|---|---|---|"]
    for mode, s in summarise(results).items():
        lines.append(
            f"| {mode} | {s['passed']}/{s['cases']} | {s['success_rate']:.0%} | "
            f"{s['llm_calls']} | {s['mean_steps']} | {s['mean_seconds']} | {s['cost_usd']} |"
        )
    lines += ["", "## Cases", ""]
    lines += [
        "| variant | party | mode | ok | outcome | LLM | steps "
        "| flow/rule/heal/plan | s | verdict |"
    ]
    lines += ["|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r.variant} | {r.party} | {r.mode} | {'✅' if r.success else '❌'} | "
            f"{r.outcome} | {r.llm_calls} | {r.steps} | "
            f"{r.flow_steps}/{r.rule_steps}/{r.heal_steps}/{r.plan_steps} | {r.seconds} | "
            f"{r.verdict.replace('|', '/')} |"
        )
    failures = [r for r in results if not r.success]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- `{r.case_id}`: {r.verdict} — agent said: {r.reason}" for r in failures]
    return "\n".join(lines) + "\n"


def write_report(out_dir: str, results: list[CaseResult], meta: dict[str, Any]) -> str:
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "meta": meta,
        "summary": summarise(results),
        "cases": [r.to_json() for r in results],
    }
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    path = os.path.join(out_dir, "report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_markdown(results, meta))
    return path
