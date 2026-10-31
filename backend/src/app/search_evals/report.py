"""Markdown + JSON reports of an eval run, and the comparison of two runs."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.search_evals.metrics import WEIGHTS, BriefResult, Summary

type Json = dict[str, Any]

REPORT_JSON = "report.json"
REPORT_MD = "report.md"

DEFINITIONS = """\
| metric | weight | definition |
|---|---|---|
| completeness | 0.25 | share of the 3 packages with transport both ways + a stay |
| budget | 0.15 | feasible: >=1 package fits; infeasible: cheapest possible (.5) + says so (.5) |
| optimality | 0.15 | 1 - gap of the cheapest package (transport+stay) vs the oracle's best |
| diversity | 0.10 | distinct stays and distinct transports across packages |
| schedule | 0.15 | share of schedule checks passed (days, check-in, connections, places, hours) |
| consistency | 0.10 | PLN, positive prices, price = offer, per-person rounding, dates in trip |
| mode | 0.10 | packages honouring the mode wish (rail / flight / fly there, train back) |
"""


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.0f}"


def _money(minor: int | None) -> str:
    return "—" if minor is None else f"{minor / 100:,.0f}".replace(",", " ")


def brief_table(results: Sequence[BriefResult]) -> list[str]:
    names = list(WEIGHTS)
    lines = [
        "| brief | score | " + " | ".join(names) + " | gap % | cheapest pkg | oracle | notes |",
        "|---" * (len(names) + 6) + "|",
    ]
    for result in results:
        if result.error:
            lines.append(
                f"| {result.brief_id} | 0 | " + " | ".join("—" for _ in names) + " | — | — | — | "
                f"ERROR {result.error[:80]} |"
            )
            continue
        cheapest = min((p.total_minor for p in result.packages if p.complete), default=None)
        oracle = result.oracle.reference_total if result.oracle else None
        failed = sorted({c for p in result.packages for c in p.json()["failed_checks"]})
        notes = ", ".join([*failed, *result.notes])[:120]
        gap = "—" if result.gap_percent is None else f"{result.gap_percent:.1f}"
        lines.append(
            f"| {result.brief_id} | {100 * result.score:.0f} | "
            + " | ".join(_pct(result.scores.get(name)) for name in names)
            + f" | {gap} | {_money(cheapest)} | {_money(oracle)} | {notes} |"
        )
    return lines


def summary_lines(summary: Summary) -> list[str]:
    metrics = " | ".join(f"{name} {_pct(value)}" for name, value in summary.metrics.items())
    return [
        f"**Score {summary.score:.1f} / 100** over {summary.briefs} briefs "
        f"({summary.errors} errors), mean optimality gap "
        f"{summary.mean_gap_percent if summary.mean_gap_percent is not None else '—'} %, "
        f"LLM calls {summary.llm_calls}. Research live latency per brief (recorded supplier "
        f"time): {summary.mean_live_seconds_sequential} s asked one after another, "
        f"{summary.mean_live_seconds_parallel} s with suppliers in parallel.",
        "",
        metrics,
    ]


def supplier_lines(stats: Mapping[str, Json]) -> list[str]:
    lines = [
        "| supplier | searches | quotes | live calls | misses | offers | s now | s when recorded |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for supplier_id, s in sorted(stats.items()):
        lines.append(
            f"| {supplier_id} | {s['searches']} | {s['quotes']} | {s['live_calls']} | "
            f"{s['misses']} | {s['offers']} | {s['seconds']:.2f} | {s['recorded_seconds']:.1f} |"
        )
    return lines


def package_lines(results: Sequence[BriefResult]) -> list[str]:
    lines: list[str] = []
    for result in results:
        lines.append(f"### {result.brief_id}")
        if result.oracle:
            lines.append(
                f"- oracle: {result.oracle.options} transport options, {result.oracle.stays} "
                f"stays, cheapest sane {_money(result.oracle.cheapest_sane_total)} "
                f"(any {_money(result.oracle.cheapest_total)}): "
                f"{result.oracle.cheapest_description}"
            )
        for package in result.packages:
            data = package.json()
            failed = data["failed_checks"] + data["failed_consistency"]
            lines.append(
                f"- {package.title} — {_money(package.total_minor)} PLN "
                f"({_money(package.per_person_minor)} pp), {'+'.join(package.modes)}, "
                f"{package.travel_hours} h" + (f"; FAILS {', '.join(failed)}" if failed else "")
            )
        lines.append("")
    return lines


def write(
    out_dir: Path,
    results: Sequence[BriefResult],
    summary: Summary,
    config: Json,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "config": config,
        "summary": summary.json(),
        "briefs": [result.json() for result in results],
    }
    (out_dir / REPORT_JSON).write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    lines = [
        f"# Search eval — {config.get('started_at', '')}",
        "",
        f"mode `{config.get('mode')}`, suppliers {', '.join(config.get('suppliers', []))}",
        "",
        *summary_lines(summary),
        "",
        "## Metrics",
        "",
        DEFINITIONS,
        "## Briefs",
        "",
        *brief_table(results),
        "",
        "## Suppliers",
        "",
        *supplier_lines(summary.supplier_stats),
        "",
        "## Packages",
        "",
        *package_lines(results),
    ]
    (out_dir / REPORT_MD).write_text("\n".join(lines), encoding="utf-8")


def _load(path: Path) -> Json:
    target = path / REPORT_JSON if path.is_dir() else path
    loaded: Json = json.loads(target.read_text(encoding="utf-8"))
    return loaded


def _delta(before: float | None, after: float | None, scale: float = 100) -> str:
    if before is None or after is None:
        return f"{before} -> {after}"
    return f"{before * scale:.1f} -> {after * scale:.1f} ({(after - before) * scale:+.1f})"


def compare(before_dir: Path, after_dir: Path) -> str:
    before, after = _load(before_dir), _load(after_dir)
    b_sum, a_sum = before["summary"], after["summary"]
    lines = [
        f"# Compare {before_dir.name} -> {after_dir.name}",
        "",
        f"- score: {_delta(b_sum['score'], a_sum['score'], 1)}",
        f"- mean gap %: {b_sum['mean_gap_percent']} -> {a_sum['mean_gap_percent']}",
        f"- errors: {b_sum['errors']} -> {a_sum['errors']}",
        f"- LLM calls: {b_sum['llm_calls']} -> {a_sum['llm_calls']}",
        f"- live latency s (sequential / parallel): "
        f"{b_sum.get('mean_live_seconds_sequential')} / "
        f"{b_sum.get('mean_live_seconds_parallel')} -> "
        f"{a_sum.get('mean_live_seconds_sequential')} / "
        f"{a_sum.get('mean_live_seconds_parallel')}",
        "",
        "| metric | before -> after |",
        "|---|---|",
    ]
    for name in WEIGHTS:
        change = _delta(b_sum["metrics"].get(name), a_sum["metrics"].get(name))
        lines.append(f"| {name} | {change} |")
    lines += ["", "| brief | score before -> after | changed metrics |", "|---|---|---|"]
    previous = {brief["brief_id"]: brief for brief in before["briefs"]}
    for brief in after["briefs"]:
        old = previous.get(brief["brief_id"])
        if old is None:
            lines.append(f"| {brief['brief_id']} | new: {100 * brief['score']:.0f} | |")
            continue
        changed = [
            f"{name} {_delta(old['scores'].get(name), brief['scores'].get(name))}"
            for name in WEIGHTS
            if old["scores"].get(name) != brief["scores"].get(name)
        ]
        if changed or old["score"] != brief["score"]:
            lines.append(
                f"| {brief['brief_id']} | {_delta(old['score'], brief['score'])} | "
                f"{'; '.join(changed)} |"
            )
    return "\n".join(lines) + "\n"
