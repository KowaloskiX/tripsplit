"""Test-only adapters behind the product's ports: a clock, a scripted agent and scriptable
prices for a real supplier.

`ScriptedLauncher` speaks the real runner's on-disk protocol (`status.json`, `NN.png`,
`approval.json`, `result.json` under `runs/<run_id>/`), so `BookingService` monitors it exactly
as it monitors a live agent — only much faster and with a chosen outcome.
"""

import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.agent.launcher import AgentLauncher, LaunchSpec, RunHandle
from app.core.domain.bookings import repriced_minor
from app.core.domain.result import Err, Result
from app.core.domain.travellers import TravellerDetails
from app.db.documents import utc_now
from app.db.identifiers import to_object_id
from app.harness.scenario import ScriptedOutcome, Target, TargetSelector
from app.models.bookings import Booking
from app.payments.partner import PaymentPartner
from app.repositories.bookings import BookingRepository
from app.services.escrow import card_charge_from_vault
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
    SupplierAdapter,
)
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SimBehaviour

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
_SCRIPTED_OUTCOMES: dict[str, ScriptedOutcome] = {
    "done": "done",
    "handoff": "handoff",
    "stuck": "stuck",
    "error": "error",
}


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


class HarnessClock:
    """ "Now" for the trip flow and every supplier of a scenario; `AdvanceClock` moves it."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or utc_now()

    def now(self) -> datetime:
        return self._now

    def advance(self, by: timedelta) -> None:
        self._now += by


def matches(booking: Booking, target: TargetSelector) -> bool:
    """`all`, a kind (`transport` / `stay` / `activity`) or a transport mode (`flight`, ...)."""
    if target == "all":
        return True
    return booking.kind.value == target or (
        booking.mode is not None and booking.mode.value == target
    )


def booking_id_of(run_id: str) -> str:
    """`b<booking_id>-<attempt>` -> `<booking_id>` (see `run_id_for`)."""
    return run_id.removeprefix("b").rsplit("-", 1)[0]


@dataclass(frozen=True, slots=True)
class Launch:
    run_id: str
    target: str
    outcome: str
    url: str
    goal: str
    passengers: int


@dataclass(frozen=True, slots=True)
class SiteCheckout:
    """The supplier site's payment step: it charges the card the agent typed from its vault
    for the site's price, through the payment partner's card network."""

    network: PaymentPartner
    vault: dict[str, str]
    amount_minor: int
    merchant: str


class ScriptedHandle:
    def __init__(
        self,
        run_dir: Path,
        outcome: ScriptedOutcome,
        approval_timeout_s: float,
        checkout: SiteCheckout | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.outcome = outcome
        self.approval_timeout_s = approval_timeout_s
        self.checkout = checkout

    async def wait(self) -> int:
        if self.outcome != "done":
            await asyncio.sleep(0.01)
            self._result(self.outcome, _REASONS[self.outcome], _STEPS[self.outcome], "")
            return 0 if self.outcome == "handoff" else 1
        decision = await self._await_approval()
        if decision is None:
            self._result("handoff", "Nobody approved the summary in time.", 7, "")
        elif decision:
            declined = await self._pay_at_checkout()
            if declined is not None:
                self._result("handoff", declined, 8, "")
                return 0
            ref = f"SIM-{self.run_dir.name[-6:].upper()}"
            (self.run_dir / "08-done.png").write_bytes(_PNG)
            self._result("done", "simulated confirmation", 8, ref)
        else:
            self._result("handoff", "The organizer rejected the summary.", 7, "")
        return 0

    async def _pay_at_checkout(self) -> str | None:
        """The agent pays with the trip's single-use card; the reason when it is declined."""
        checkout = self.checkout
        if checkout is None or "card_number" not in checkout.vault:
            return None
        charged = await checkout.network.charge_card(
            card_charge_from_vault(checkout.vault, checkout.amount_minor, checkout.merchant),
            idempotency_key=f"site:{self.run_dir.name}",
        )
        if isinstance(charged, Err):
            return (
                f"The supplier's checkout declined the virtual card ({charged.error}): the site "
                "asks more than the card's limit."
            )
        return None

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
    """Plays the agent. The outcome per booking comes from the scenario's AgentOutcome steps
    (the most specific target wins: a mode before its kind), else from the booking's simulated
    supplier (`SimBehaviour.agent_outcome`, e.g. a CAPTCHA), else `done` = reach the summary,
    wait for the approval, confirm."""

    runs_dir: Path
    suppliers: SupplierRegistry = field(default_factory=SupplierRegistry)
    behaviours: dict[str, SimBehaviour] = field(default_factory=dict)
    approval_timeout_s: float = 120.0
    # Target (a mode or a kind) -> outcome.
    outcomes: dict[str, ScriptedOutcome] = field(default_factory=dict)
    launches: list[Launch] = field(default_factory=list)
    # The card network the scripted checkout charges through (None = nobody pays).
    card_network: PaymentPartner | None = None
    # Target -> percent the supplier site charges above the booked amount at checkout.
    site_markup_percent: dict[str, float] = field(default_factory=dict)

    def script(self, target: Target, outcome: ScriptedOutcome) -> None:
        self.outcomes[target] = outcome

    def outcome_for(self, booking: Booking | None) -> ScriptedOutcome:
        if booking is None:
            return "done"
        for target in (booking.mode.value if booking.mode else None, booking.kind.value):
            if target is not None and target in self.outcomes:
                return self.outcomes[target]
        scripted = self.behaviours.get(booking.supplier_id)
        if scripted is not None and scripted.agent_outcome is not None:
            return _SCRIPTED_OUTCOMES.get(scripted.agent_outcome, "done")
        return "done"

    async def start(self, spec: LaunchSpec) -> RunHandle:
        booking = await self._booking_of(spec.run_id)
        outcome = self.outcome_for(booking)
        target = (booking.mode or booking.kind).value if booking is not None else "?"
        self.launches.append(
            Launch(
                run_id=spec.run_id,
                target=target,
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
        return ScriptedHandle(
            run_dir, outcome, self.approval_timeout_s, self._checkout(booking, spec)
        )

    def _checkout(self, booking: Booking | None, spec: LaunchSpec) -> SiteCheckout | None:
        if self.card_network is None or booking is None:
            return None
        markup = 0.0
        for target in (booking.mode.value if booking.mode else None, booking.kind.value):
            if target is not None and target in self.site_markup_percent:
                markup = self.site_markup_percent[target]
                break
        return SiteCheckout(
            network=self.card_network,
            vault=dict(spec.vault),
            amount_minor=repriced_minor(booking.amount_minor, markup),
            merchant=booking.supplier,
        )

    @staticmethod
    async def _booking_of(run_id: str) -> Booking | None:
        booking_oid = to_object_id(booking_id_of(run_id))
        return await BookingRepository().get(booking_oid) if booking_oid else None


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


class ScriptablePrices:
    """Wraps a REAL supplier (PKP Intercity under `--live-search`) so a scenario can still
    script it: `SupplierPriceChange` moves its next quote, `sold_out` empties it. Everything
    else goes to the real adapter."""

    def __init__(self, inner: SupplierAdapter, behaviour: SimBehaviour) -> None:
        self.inner = inner
        self.behaviour = behaviour
        self.id = inner.id
        self.display_name = inner.display_name
        self.capabilities = inner.capabilities

    async def search(self, request: SearchRequest) -> list[Offer]:
        return await self.inner.search(request)

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        if self.behaviour.sold_out:
            return None
        quoted = await self.inner.quote(offer, party_size)
        change = self.behaviour.price_change_percent
        if quoted is None or change is None:
            return quoted
        self.behaviour.price_change_percent = None
        return Quote(
            price_minor=repriced_minor(quoted.price_minor, change),
            currency=quoted.currency,
            quoted_at=quoted.quoted_at,
            expires_at=quoted.expires_at,
        )

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        return await self.inner.hold(offer, travellers)

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        return await self.inner.purchase(
            offer, travellers, price_minor=price_minor, hold_ref=hold_ref
        )

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return await self.inner.status(booking)
