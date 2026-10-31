"""Test-only adapters behind the product's ports: a scripted agent and a scripted supplier price.

`ScriptedLauncher` speaks the real runner's on-disk protocol (`status.json`, `NN.png`,
`approval.json`, `result.json` under `runs/<run_id>/`), so `BookingService` monitors it exactly
as it monitors a live agent — only much faster and with a chosen outcome.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.launcher import AgentLauncher, LaunchSpec, RunHandle
from app.core.domain.bookings import repriced_minor
from app.core.domain.trips import BookingKind
from app.db.identifiers import to_object_id
from app.harness.scenario import ScriptedOutcome
from app.models.bookings import Booking
from app.repositories.bookings import BookingRepository

STATUS_FILE = "status.json"
RESULT_FILE = "result.json"
APPROVAL_FILE = "approval.json"
# A 1x1 PNG: the live preview needs *a* frame, not a pretty one.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
_REASONS: dict[str, str] = {
    "handoff": "A CAPTCHA blocks the supplier page — a human has to finish this booking.",
    "stuck": "The page stopped reacting to the planner's actions.",
    "error": "The browser crashed (scripted).",
}
_STEPS = {"done": 7, "handoff": 4, "stuck": 9, "error": 2}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic, like the runner: the monitor must never read half a file."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, path)


def _read_approval(run_dir: Path) -> bool | None:
    try:
        payload: Any = json.loads((run_dir / APPROVAL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    approved = payload.get("approved") if isinstance(payload, dict) else None
    return approved if isinstance(approved, bool) else None


def booking_id_of(run_id: str) -> str:
    """`b<booking_id>-<attempt>` -> `<booking_id>` (see `run_id_for`)."""
    return run_id.removeprefix("b").rsplit("-", 1)[0]


@dataclass(frozen=True, slots=True)
class Launch:
    run_id: str
    kind: BookingKind | None
    outcome: str
    url: str
    goal: str
    passengers: int


class ScriptedHandle:
    def __init__(self, run_dir: Path, outcome: ScriptedOutcome, approval_timeout_s: float) -> None:
        self.run_dir = run_dir
        self.outcome = outcome
        self.approval_timeout_s = approval_timeout_s

    async def wait(self) -> int:
        if self.outcome != "done":
            await asyncio.sleep(0.01)
            self._result(self.outcome, _REASONS[self.outcome], _STEPS[self.outcome], "")
            return 0 if self.outcome == "handoff" else 1
        decision = await self._await_approval()
        if decision is None:
            self._result("handoff", "Nobody approved the summary in time.", 7, "")
        elif decision:
            ref = f"SIM-{self.run_dir.name[-6:].upper()}"
            (self.run_dir / "08-done.png").write_bytes(_PNG)
            self._result("done", "simulated confirmation", 8, ref)
        else:
            self._result("handoff", "The organizer rejected the summary.", 7, "")
        return 0

    async def _await_approval(self) -> bool | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.approval_timeout_s
        while loop.time() < deadline:
            decision = await asyncio.to_thread(_read_approval, self.run_dir)
            if decision is not None:
                return decision
            await asyncio.sleep(0.02)
        return None

    def _result(self, outcome: str, reason: str, steps: int, ref: str) -> None:
        status = {"milestone": "review", "reached": ["search"], "step": steps, "outcome": outcome}
        _write_json(self.run_dir / STATUS_FILE, {**status, "reason": reason})
        result = {
            "outcome": outcome,
            "reason": reason,
            "steps": steps,
            "cost_usd": 0.0,
            "confirmation_ref": ref,
        }
        _write_json(self.run_dir / RESULT_FILE, result)


@dataclass
class ScriptedLauncher:
    """Plays the agent. The outcome per booking kind is set by the scenario's AgentOutcome step
    and applies to every later start of that kind (default: `done` = reach the summary, wait for
    the approval, confirm)."""

    runs_dir: Path
    approval_timeout_s: float = 120.0
    outcomes: dict[BookingKind, ScriptedOutcome] = field(default_factory=dict)
    launches: list[Launch] = field(default_factory=list)

    async def start(self, spec: LaunchSpec) -> RunHandle:
        kind = await self._kind_of(spec.run_id)
        outcome: ScriptedOutcome = self.outcomes.get(kind, "done") if kind else "done"
        self.launches.append(
            Launch(
                run_id=spec.run_id,
                kind=kind,
                outcome=outcome,
                url=spec.url,
                goal=spec.goal,
                passengers=int(spec.vault.get("passengers", "0")),
            )
        )
        run_dir = self.runs_dir / spec.run_id
        await asyncio.to_thread(run_dir.mkdir, parents=True, exist_ok=True)
        (run_dir / "01.png").write_bytes(_PNG)
        live = outcome if outcome != "done" else "awaiting_approval"
        status = {"milestone": "review", "reached": ["search", "review"], "step": _STEPS[outcome]}
        if outcome == "done":
            _write_json(run_dir / STATUS_FILE, {**status, "outcome": live})
        return ScriptedHandle(run_dir, outcome, self.approval_timeout_s)

    @staticmethod
    async def _kind_of(run_id: str) -> BookingKind | None:
        booking_oid = to_object_id(booking_id_of(run_id))
        booking = await BookingRepository().get(booking_oid) if booking_oid else None
        return booking.kind if booking is not None else None


@dataclass
class RoutingLauncher:
    """`--live-agent`: the real subprocess agent for the demo rail supplier, scripted otherwise."""

    live: AgentLauncher
    scripted: ScriptedLauncher
    live_url_marker: str = "/api/demo-supplier/rail"
    live_runs: list[str] = field(default_factory=list)

    async def start(self, spec: LaunchSpec) -> RunHandle:
        if self.live_url_marker in spec.url:
            self.live_runs.append(spec.run_id)
            return await self.live.start(spec)
        return await self.scripted.start(spec)


@dataclass
class ScriptedQuotes:
    """The `QuoteProvider` port (`app/suppliers/quotes.py`, feat/domain-lifecycle): the
    supplier's current price for a booking. A change set by SupplierPriceChange is one-shot — it
    is consumed by the next quote of that kind, after which the price is stable again."""

    percent: dict[BookingKind, float] = field(default_factory=dict)
    sold_out: set[BookingKind] = field(default_factory=set)
    asked: list[tuple[str, int, int | None]] = field(default_factory=list)

    async def quote(self, booking: Booking) -> int | None:
        if booking.kind in self.sold_out:
            price: int | None = None
        else:
            change = self.percent.pop(booking.kind, None)
            price = (
                booking.amount_minor
                if change is None
                else repriced_minor(booking.amount_minor, change)
            )
        self.asked.append((booking.kind.value, booking.amount_minor, price))
        return price
