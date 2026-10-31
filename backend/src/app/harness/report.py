"""Markdown + JSON reports: one per scenario, plus a summary of the whole run."""

import json
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.domain.bookings import format_money
from app.harness.driver import ScenarioResult, StepRecord

_ICONS = {"ok": "ok", "failed": "FAILED", "pending": "PENDING", "skipped": "skipped"}
_VERDICTS = {
    "pass": "PASS",
    "known": "PASS (known violations)",
    "pending": "PENDING",
    "xfail": "XFAIL (documented bug)",
    "xpass": "XPASS",
    "fail": "FAIL",
}
_EVENTS_SHOWN = 4


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _events(step: StepRecord) -> str:
    shown = step.events[:_EVENTS_SHOWN]
    more = len(step.events) - len(shown)
    text = "<br>".join(_cell(event)[:160] for event in shown)
    return text + (f"<br>(+{more} more)" if more > 0 else "")


def scenario_markdown(result: ScenarioResult) -> str:
    lines = [
        f"# {result.title} (`{result.name}`)",
        "",
        f"**Verdict: {_VERDICTS[result.outcome]}**"
        + (f" — {result.reason}" if result.reason else ""),
        "",
        f"Mode: {result.mode} · {result.seconds:.2f} s · final trip status `{result.trip_status}`",
        "",
    ]
    if result.description:
        lines += [result.description, ""]
    if result.suppliers:
        lines += [f"Suppliers: {', '.join(result.suppliers)}", ""]
    lines += [
        "## Timeline",
        "",
        "| # | Step | Result | Time | Trip | Detail | New events |",
        "|---|---|---|---|---|---|---|",
    ]
    for step in result.steps:
        lines.append(
            f"| {step.index} | `{_cell(step.label)}` | {_ICONS[step.outcome]} | "
            f"{step.seconds:.2f}s | {step.trip_status} | {_cell(step.detail)} | {_events(step)} |"
        )
    lines += ["", "## Money", ""]
    if result.money:
        lines += ["| Member | Share | Paid | Status |", "|---|---|---|---|"]
        for row in result.money:
            who = row.member if row.is_member else f"{row.member} (left)"
            lines.append(
                f"| {who} | {format_money(row.share_minor, result.currency)} | "
                f"{format_money(row.paid_minor, result.currency)} | {row.status} |"
            )
        paid = sum(row.paid_minor for row in result.money)
        lines += [
            "",
            f"Trip total {format_money(result.total_minor, result.currency)}, collected "
            f"{format_money(paid, result.currency)}.",
        ]
    else:
        lines.append("No contributions (voting never closed).")
    lines += ["", "## Invariants", ""]
    if result.violations:
        lines += ["| Invariant | Violation | Known? |", "|---|---|---|"]
        for violation in result.violations:
            known = f"known: {violation.known}" if violation.known else "**UNEXPECTED**"
            lines.append(f"| {violation.invariant} | {_cell(violation.message)} | {_cell(known)} |")
    else:
        lines.append("All invariants held after every step.")
    pending = [s for s in result.steps if s.outcome == "pending"]
    if pending or result.outcome in ("xfail", "xpass"):
        lines += ["", "## Expected failures", ""]
        lines += [f"- step {s.index} `{s.label}`: {s.detail}" for s in pending]
        if result.outcome in ("xfail", "xpass"):
            lines.append(f"- scenario: {result.reason}")
    lines += ["", "## Purchases", ""]
    if result.bookings:
        lines += [
            "| Target | Booking | Supplier | Channel | Pax | Amount | Status | Hold until | Ref |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for booking in result.bookings:
            lines.append(
                f"| {booking.target} | {_cell(booking.title)} | {booking.supplier_id} | "
                f"{booking.channel} | {booking.passengers} | "
                f"{format_money(booking.amount_minor, result.currency)} | {booking.status} | "
                f"{booking.hold_expires_at} | {booking.confirmation_ref} |"
            )
    else:
        lines.append("No bookings (voting never closed).")
    lines += ["", "## Agent runs", ""]
    if result.agent_runs:
        lines += [
            "| Run | Kind | Agent | Outcome | Steps | Seconds | Booking | Ref | Reason |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for run in result.agent_runs:
            lines.append(
                f"| `{run.run_id}` | {run.kind} | {'live' if run.live else 'scripted'} | "
                f"{run.outcome} | {run.steps} | {run.seconds:.1f} | {run.booking_status} | "
                f"{run.confirmation_ref} | {_cell(run.reason)[:120]} |"
            )
    else:
        lines.append("No agent was started.")
    if result.live_search is not None:
        log = result.live_search
        lines += [
            "",
            "## Live PKP Intercity search",
            "",
            f"{log.origin} -> {log.destination}, {log.seconds:.1f} s "
            "through a headless Camoufox page.",
            "",
        ]
        if log.legs:
            lines += [
                "| Leg | Train | Departs | Class | Offer | Purchases | Total |",
                "|---|---|---|---|---|---|---|",
            ]
            for leg in log.legs:
                purchases = " + ".join(
                    f"{n} pax {format_money(minor, result.currency)}"
                    for n, minor in zip(leg.passengers, leg.purchases, strict=True)
                )
                lines.append(
                    f"| {leg.direction} | {leg.connection} | {leg.departs_at:%Y-%m-%d %H:%M} | "
                    f"{leg.travel_class} | {leg.offer_name} | {purchases} | "
                    f"{format_money(leg.total_minor, result.currency)} |"
                )
        lines += [f"- {note}" for note in log.notes]
    lines += ["", "## Domain features", ""]
    lines += [f"- `{name}`: {state}" for name, state in result.features.items()]
    return "\n".join(lines) + "\n"


def summary_markdown(results: Sequence[ScenarioResult], started_at: datetime) -> str:
    lines = [
        f"# Trip harness — {started_at:%Y-%m-%d %H:%M:%S}",
        "",
        "| Scenario | Verdict | Steps ok | Violations (unexpected/known) | Time | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        ok = sum(1 for s in result.steps if s.outcome == "ok")
        unexpected = sum(1 for v in result.violations if v.known is None)
        known = len(result.violations) - unexpected
        lines.append(
            f"| [{result.name}]({result.name}.md) | {_VERDICTS[result.outcome]} | "
            f"{ok}/{len(result.steps)} | {unexpected}/{known} | {result.seconds:.1f}s | "
            f"{_cell(result.reason)[:200]} |"
        )
    return "\n".join(lines) + "\n"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def write_reports(out_dir: Path, results: Sequence[ScenarioResult], started_at: datetime) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        (out_dir / f"{result.name}.md").write_text(scenario_markdown(result), encoding="utf-8")
        (out_dir / f"{result.name}.json").write_text(
            json.dumps(_jsonable(result), indent=2, ensure_ascii=False), encoding="utf-8"
        )
    summary = out_dir / "summary.md"
    summary.write_text(summary_markdown(results, started_at), encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(
            [
                {
                    "name": r.name,
                    "outcome": r.outcome,
                    "reason": r.reason,
                    "seconds": r.seconds,
                    "unexpected_violations": sum(1 for v in r.violations if v.known is None),
                    "known_violations": sum(1 for v in r.violations if v.known is not None),
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary


def summary_table(results: Sequence[ScenarioResult]) -> str:
    """The compact table printed to the terminal."""
    rows = [("scenario", "verdict", "steps", "viol u/k", "time", "reason")]
    for result in results:
        ok = sum(1 for s in result.steps if s.outcome == "ok")
        unexpected = sum(1 for v in result.violations if v.known is None)
        rows.append(
            (
                result.name,
                result.outcome.upper(),
                f"{ok}/{len(result.steps)}",
                f"{unexpected}/{len(result.violations) - unexpected}",
                f"{result.seconds:.1f}s",
                result.reason[:70],
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row[:5], widths, strict=True))
        + "  "
        + row[5]
        for row in rows
    )
