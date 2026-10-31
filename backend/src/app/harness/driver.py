"""Executes a scenario step by step and records everything the report needs.

Every step: run it through the real service (or check an expectation), wait for background
work to settle (research drained, agent monitors at a terminal or awaiting-approval state),
snapshot the database and check every invariant. Domain errors are captured as codes, so a
scenario can say "the next step must fail with `trip_not_ready`".
"""

import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from beanie import PydanticObjectId

from app.core.domain.bookings import format_money
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import hold_is_live
from app.core.domain.travellers import masked_document_number
from app.core.domain.trips import (
    BookingStatus,
    ContributionStatus,
    EventActor,
    TripStatus,
)
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.harness.adapters import matches
from app.harness.features import Feature, all_features, feature
from app.harness.invariants import InvariantContext, Snapshot, Violation, check_all, load_snapshot
from app.harness.scenario import (
    EXPECTATIONS,
    AdvanceClock,
    AgentOutcome,
    Approve,
    CastVotes,
    CheckDisruptions,
    CloseVoting,
    CompleteManually,
    Disrupt,
    EnterTravellerDetails,
    ExpectAgentMessage,
    ExpectAgentRuns,
    ExpectBookingStatus,
    ExpectBudget,
    ExpectError,
    ExpectEvent,
    ExpectHold,
    ExpectPurchases,
    ExpectShares,
    ExpectStatus,
    ExpectWinner,
    GeneratePackages,
    Leave,
    Pay,
    StartBookings,
    Step,
    SupplierDisruption,
    SupplierPriceChange,
    Target,
    TargetSelector,
    describe,
)
from app.harness.world import World
from app.models.bookings import Booking
from app.repositories.trips import ProposalRepository
from app.services.bookings import running_monitors
from app.suppliers.duffel import DuffelLog
from app.suppliers.pkp import LiveSearchLog
from app.suppliers.ports import DisruptionKind
from app.suppliers.sim import SimDisruption

type StepOutcome = Literal["ok", "failed", "pending", "skipped"]
type ScenarioOutcome = Literal["pass", "known", "pending", "xfail", "xpass", "fail"]

_BUSY = frozenset({BookingStatus.RUNNING, BookingStatus.APPROVED})
_STARTABLE = frozenset({BookingStatus.PENDING, BookingStatus.FAILED})
_NEEDS: dict[type, Feature] = {
    SupplierPriceChange: Feature.QUOTES,
    Leave: Feature.LEAVE,
    CompleteManually: Feature.COMPLETE_MANUALLY,
}


class StepFailed(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class StepPending(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StepRecord:
    index: int
    label: str
    outcome: StepOutcome
    detail: str
    seconds: float
    trip_status: str
    events: list[str]
    violations: list[Violation]


@dataclass(frozen=True, slots=True)
class MoneyRow:
    member: str
    share_minor: int
    paid_minor: int
    status: str
    is_member: bool


@dataclass(frozen=True, slots=True)
class BookingRecord:
    """One purchase as the report shows it — no traveller data."""

    target: str  # "flight", "rail", "stay", ...
    title: str
    supplier_id: str
    channel: str
    passengers: int
    amount_minor: int
    status: str
    hold_expires_at: str
    confirmation_ref: str
    hold_ref: str = ""  # the supplier's id of the held order (a Duffel order id)


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    run_id: str
    kind: str
    title: str
    booking_status: str
    outcome: str
    steps: int
    reason: str
    confirmation_ref: str
    seconds: float
    live: bool


@dataclass
class ScenarioResult:
    name: str
    title: str
    description: str
    mode: str
    outcome: ScenarioOutcome = "pass"
    reason: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)  # deduplicated, first seen
    money: list[MoneyRow] = field(default_factory=list)
    currency: str = "PLN"
    total_minor: int = 0
    trip_status: str = ""
    agent_runs: list[AgentRunRecord] = field(default_factory=list)
    bookings: list[BookingRecord] = field(default_factory=list)
    suppliers: list[str] = field(default_factory=list)
    live_search: LiveSearchLog | None = None
    duffel: DuffelLog | None = None
    # Who travelled, as the report may show it: name, fields present, masked document.
    travellers: list[str] = field(default_factory=list)
    features: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


def _code(error: object) -> str:
    return str(getattr(error, "value", error))


class Driver:
    def __init__(self, world: World, *, wait_timeout_s: float = 15.0, mode: str = "fast") -> None:
        self.world = world
        self.scenario = world.scenario
        self.wait_timeout_s = wait_timeout_s
        self.mode = mode
        self.trail: list[TripStatus] = []
        self.initial_shares: dict[str, int] = {}

    # ---- the loop -----------------------------------------------------------------------

    async def run(self) -> ScenarioResult:
        started = time.monotonic()
        result = ScenarioResult(
            name=self.scenario.name,
            title=self.scenario.title,
            description=self.scenario.description,
            mode=self.mode,
            suppliers=world_suppliers(self.world),
            features={
                name.value: "present" if info.present else f"missing: {info.missing}"
                for name, info in all_features().items()
            },
        )
        if self.scenario.live_flights_only and not self.world.options.live_flights:
            result.steps.append(
                StepRecord(
                    0,
                    "Setup",
                    "pending",
                    "pending — needs --live-flights (the real Duffel test API)",
                    0.0,
                    "",
                    [],
                    [],
                )
            )
            await self.world.close()
            self._judge(result)
            return result
        try:
            await self.world.setup()
            before = await self._snapshot()
            result.steps.append(
                StepRecord(
                    0,
                    "Setup (register members, create + join)",
                    "ok",
                    f"{len(before.members)} members",
                    0.0,
                    before.trip.status.value,
                    [],
                    [],
                )
            )
            await self._steps(before, result)
            final = await self._snapshot()
            self._summarize(final, result)
            if self.world.duffel_log is not None:
                result.travellers = await self._travellers(final)
        except Exception as exc:  # the harness itself must always produce a report
            result.steps.append(
                StepRecord(len(result.steps), "harness crash", "failed", repr(exc), 0.0, "", [], [])
            )
        finally:
            await self._release_agents()
            await self.world.close()
        result.live_search = self.world.live_search_log
        result.duffel = self.world.duffel_log
        result.seconds = round(time.monotonic() - started, 2)
        self._judge(result)
        return result

    async def _steps(self, before: Snapshot, result: ScenarioResult) -> None:
        expected_error: str | None = None
        stopped = False
        seen: set[tuple[str, str]] = set()
        for index, step in enumerate(self.scenario.steps, start=1):
            label = describe(step)
            if stopped:
                result.steps.append(StepRecord(index, label, "skipped", "", 0.0, "", [], []))
                continue
            if isinstance(step, ExpectError):
                expected_error = step.code
                result.steps.append(
                    StepRecord(
                        index,
                        label,
                        "ok",
                        "armed for the next step",
                        0.0,
                        before.trip.status.value,
                        [],
                        [],
                    )
                )
                continue
            self.trail = [before.trip.status]
            clock = time.monotonic()
            outcome: StepOutcome = "ok"
            code: str | None = None
            expected_events: Sequence[str] = ()
            try:
                needed = _NEEDS.get(type(step))
                if needed is not None and not (info := feature(needed)).present:
                    raise StepPending(f"pending — missing {info.missing}")
                detail, expected_events = await self._execute(step)
            except StepPending as pending:
                outcome, detail = "pending", str(pending)
                stopped = True
            except StepFailed as failure:
                outcome, detail, code = "failed", str(failure), failure.code
            except Exception as exc:
                outcome, detail = "failed", f"crashed: {exc!r}"
            if expected_error is not None and outcome != "pending":
                outcome, detail, expected_events = self._against_expected(
                    expected_error, outcome, code, detail
                )
                expected_error = None
            if outcome == "failed" and not isinstance(step, EXPECTATIONS):
                stopped = True
            after = await self._snapshot()
            self.trail.append(after.trip.status)
            context = InvariantContext(
                before=before,
                after=after,
                status_trail=self.trail,
                expected_events=expected_events if outcome == "ok" else (),
                suppliers=self.world.suppliers,
                now=self.world.clock.now(),
                holds=self.scenario.holds,
            )
            violations = check_all(context, dict(self.scenario.known_violations))
            for violation in violations:
                key = (violation.invariant, violation.message)
                if key not in seen:
                    seen.add(key)
                    result.violations.append(violation)
            result.steps.append(
                StepRecord(
                    index=index,
                    label=label,
                    outcome=outcome,
                    detail=detail,
                    seconds=round(time.monotonic() - clock, 3),
                    trip_status=after.trip.status.value,
                    events=[f"{e.kind.value}: {e.message}" for e in context.new_events],
                    violations=violations,
                )
            )
            before = after

    @staticmethod
    def _against_expected(
        expected: str, outcome: StepOutcome, code: str | None, detail: str
    ) -> tuple[StepOutcome, str, Sequence[str]]:
        if outcome == "failed" and code == expected:
            events = ("price_changed",) if expected == "price_changed" else ()
            return "ok", f"failed as expected with `{code}` — {detail}", events
        if outcome == "ok":
            return "failed", f"expected `{expected}`, but the step succeeded ({detail})", ()
        return "failed", f"expected `{expected}`, got `{code}`: {detail}", ()

    # ---- steps ----------------------------------------------------------------------------

    async def _execute(self, step: Step) -> tuple[str, Sequence[str]]:
        match step:
            case GeneratePackages():
                return await self._generate(), ()
            case CastVotes():
                return await self._vote(step), ()
            case CloseVoting():
                return await self._close(), ("proposal_chosen",)
            case Pay():
                return await self._pay(step)
            case StartBookings():
                return await self._start_step(step), ("booking_started",)
            case AgentOutcome():
                self.world.scripted.script(step.target, step.outcome)
                return f"{step.target}: {step.outcome}", ()
            case Approve():
                return await self._approve(step), ()
            case Disrupt():
                return await self._disrupt(step), ("disruption", "resplit")
            case SupplierPriceChange():
                for supplier_id in self._suppliers_of(step.target):
                    self.world.behaviours[supplier_id].price_change_percent = step.percent
                return f"{step.target} suppliers now ask {step.percent:+g}%", ()
            case SupplierDisruption():
                return self._script_disruption(step), ()
            case CheckDisruptions():
                return await self._check_disruptions(), ("disruption", "resplit")
            case AdvanceClock():
                self.world.advance(step.hours)
                return f"now {self.world.clock.now():%Y-%m-%d %H:%M} UTC", ()
            case EnterTravellerDetails():
                await self.world.enter_details(list(step.members))
                return f"{', '.join(step.members)} entered their details", ()
            case Leave():
                return await self._leave(step), ("resplit",)
            case CompleteManually():
                return await self._complete(step), ("booking_confirmed",)
            case _:
                return await self._expect(step), ()

    async def _generate(self) -> str:
        world = self.world
        generated = await world.proposals.generate(world.trip_id, world.organizer_id)
        self._raise_on(generated)
        await self._observe()
        await world.runner.drain()
        snap = await self._observe()
        proposals = await ProposalRepository().for_trip(world.trip_oid)
        lines = [
            f"#{i} {p.title}: {format_money(p.total_minor, snap.trip.currency)} "
            f"({format_money(p.per_person_minor, snap.trip.currency)} pp)"
            for i, p in enumerate(proposals)
        ]
        return "; ".join(lines) or "no packages"

    async def _vote(self, step: CastVotes) -> str:
        world = self.world
        proposals = await ProposalRepository().for_trip(world.trip_oid)
        picks = (
            {name: step.picks for name in self.scenario.members}
            if isinstance(step.picks, int)
            else dict(step.picks)
        )
        for name, index in picks.items():
            if not 0 <= index < len(proposals):
                raise StepFailed(f"{name} picks package #{index}, there are {len(proposals)}")
            voted = await world.proposals.vote(
                world.trip_id, world.users[name], to_text(identifier_of(proposals[index]))
            )
            self._raise_on(voted, f"{name}: ")
        tally: dict[int, int] = {}
        for index in picks.values():
            tally[index] = tally.get(index, 0) + 1
        return ", ".join(f"#{index}: {count} vote(s)" for index, count in sorted(tally.items()))

    async def _close(self) -> str:
        world = self.world
        closed = await world.proposals.close_voting(world.trip_id, world.organizer_id)
        self._raise_on(closed)
        snap = await self._snapshot()
        names = self._names()
        self.initial_shares = {
            names.get(c.user_id, "?"): c.amount_minor for c in snap.contributions
        }
        chosen = snap.trip.chosen_proposal_id
        winner = await ProposalRepository().get(chosen) if chosen is not None else None
        money = format_money(snap.trip.total_minor, snap.trip.currency)
        title = winner.title if winner else "?"
        return f"winner “{title}”, total {money}, {len(snap.bookings)} booking(s)"

    async def _pay(self, step: Pay) -> tuple[str, Sequence[str]]:
        world = self.world
        snap = await self._snapshot()
        names = self._names()
        owes = {
            names.get(c.user_id, "?"): c.amount_minor - c.paid_minor for c in snap.contributions
        }
        current = {names.get(m.user_id, "?") for m in snap.members}
        if step.members is None:
            payers = [
                name
                for name in self.scenario.members
                if name not in step.everyone_except and name in current and owes.get(name, 0) > 0
            ]
        else:
            payers = list(step.members)
        if not payers:
            return "nobody owes anything", ()
        paid, errors = [], []
        for name in payers:
            result = await world.contributions.pay(world.trip_id, world.users[name])
            if isinstance(result, Err):
                errors.append((name, _code(result.error)))
            else:
                paid.append(f"{name} {format_money(result.value.paid_minor, snap.trip.currency)}")
        if errors:
            name, code = errors[0]
            raise StepFailed(f"{name} could not pay: {code}", code)
        return "paid: " + ", ".join(paid), ("contribution_paid",)

    def _suppliers_of(self, target: Target) -> list[str]:
        """The scenario's scriptable suppliers selling `target` (a kind or a mode)."""
        found = [
            adapter.id
            for adapter in self.world.suppliers
            if adapter.id in self.world.behaviours
            and (
                adapter.capabilities.kind.value == target
                or (
                    adapter.capabilities.mode is not None
                    and adapter.capabilities.mode.value == target
                )
            )
        ]
        if not found:
            raise StepFailed(f"no scriptable {target} supplier in this scenario")
        return found

    def _script_disruption(self, step: SupplierDisruption) -> str:
        kind = DisruptionKind.CANCELLATION if step.cancelled else DisruptionKind.DELAY
        for supplier_id in self._suppliers_of(step.target):
            self.world.behaviours[supplier_id].disruption = SimDisruption(
                kind=kind,
                delay_minutes=step.delay_minutes,
                replacement_price_percent=step.replacement_percent,
            )
        return f"{step.target}: {kind.value} scripted, replacement {step.replacement_percent:+g}%"

    async def _check_disruptions(self) -> str:
        world = self.world
        result = await world.bookings.check_disruptions(world.trip_id, world.organizer_id)
        if not isinstance(result, Ok):
            raise StepFailed(_code(result.error), _code(result.error))
        if not result.value:
            raise StepFailed("no supplier reported a disruption")
        lines = []
        for done in result.value:
            currency = done.trip.currency
            old = format_money(sum(b.amount_minor for b in done.cancelled), currency)
            new = format_money(sum(b.amount_minor for b in done.replacements), currency)
            titles = ", ".join(f"“{b.title}”" for b in done.replacements)
            lines.append(f"rebooked onto {titles}: {old} -> {new}")
        return "; ".join(lines)

    async def _start_step(self, step: StartBookings) -> str:
        """A live supplier may re-price at the purchase: with `top_up_on_price_change` the
        group tops up its re-split shares and the organizer starts once more."""
        if not step.top_up_on_price_change:
            return await self._start(step.target)
        try:
            return await self._start(step.target)
        except StepFailed as failure:
            if failure.code != "price_changed":
                raise
        topped_up, _ = await self._pay(Pay())
        line = await self._start(step.target)
        return f"re-priced at the start — {topped_up}; then {line}"

    async def _start(self, selector: TargetSelector) -> str:
        world = self.world
        snap = await self._snapshot()
        targets = [b for b in snap.live_bookings if matches(b, selector) and b.status in _STARTABLE]
        if not targets:
            raise StepFailed(f"no startable {selector} booking")
        started, errors = [], []
        for booking in targets:
            result = await world.bookings.start(
                world.trip_id, to_text(identifier_of(booking)), world.organizer_id
            )
            target = (booking.mode or booking.kind).value
            if isinstance(result, Err):
                errors.append((target, _code(result.error)))
            else:
                started.append(target)
        if started:
            await self._wait_for_agents()
        if errors:
            kind, code = errors[0]
            raise StepFailed(f"starting the {kind} booking failed: {code}", code)
        return await self._booking_line(f"started {', '.join(started)}")

    async def _approve(self, step: Approve) -> str:
        world = self.world
        snap = await self._snapshot()
        targets = [
            b
            for b in snap.live_bookings
            if matches(b, step.target) and b.status is BookingStatus.AWAITING_APPROVAL
        ]
        if not targets:
            raise StepFailed(f"no {step.target} booking is awaiting approval")
        for booking in targets:
            result = await world.bookings.approve(
                world.trip_id, to_text(identifier_of(booking)), world.organizer_id, step.approved
            )
            self._raise_on(result, f"{(booking.mode or booking.kind).value}: ")
        await self._wait_for_agents()
        return await self._booking_line("approved" if step.approved else "rejected")

    async def _disrupt(self, step: Disrupt) -> str:
        world = self.world
        result = await world.bookings.simulate_disruption(
            world.trip_id, world.organizer_id, None, step.delay_minutes, step.price_change_percent
        )
        if not isinstance(result, Ok):
            raise StepFailed(_code(result.error), _code(result.error))
        done = result.value
        currency = done.trip.currency
        old = format_money(sum(b.amount_minor for b in done.cancelled), currency)
        new = format_money(sum(b.amount_minor for b in done.replacements), currency)
        before = format_money(done.previous_total_minor, currency)
        after = format_money(sum(s.change.share_minor for s in done.shares), currency)
        titles = ", ".join(f"“{b.title}”" for b in done.cancelled)
        return (
            f"cancelled {len(done.cancelled)} booking(s) {titles} ({old}), "
            f"replacement(s) {new}; total {before} -> {after}"
        )

    async def _leave(self, step: Leave) -> str:
        world = self.world
        leave: Any = getattr(world.trips, "leave")  # noqa: B009 — feature-detected method
        result: Result[Any, Any] = await leave(world.trip_id, world.users[step.member])
        self._raise_on(result)
        return f"{step.member} left"

    async def _complete(self, step: CompleteManually) -> str:
        world = self.world
        snap = await self._snapshot()
        targets = [
            b
            for b in snap.live_bookings
            if matches(b, step.target) and b.status is BookingStatus.HANDOFF
        ]
        if not targets:
            raise StepFailed(f"no {step.target} booking in handoff")
        complete: Any = getattr(world.bookings, "complete_manually")  # noqa: B009
        for booking in targets:
            result: Result[Any, Any] = await complete(
                world.trip_id, world.organizer_id, to_text(identifier_of(booking)), step.ref
            )
            self._raise_on(result)
        await self._wait_for_agents()
        return await self._booking_line(f"completed manually with {step.ref}")

    # ---- expectations -------------------------------------------------------------------

    async def _expect(self, step: Step) -> str:
        snap = await self._snapshot()
        match step:
            case ExpectStatus():
                if snap.trip.status is not step.status:
                    raise StepFailed(f"trip is {snap.trip.status}, expected {step.status}")
                return f"trip is {step.status}"
            case ExpectBookingStatus():
                found = [b for b in snap.live_bookings if matches(b, step.target)]
                wrong = [b for b in found if b.status is not step.status]
                miscounted = step.count is not None and len(found) != step.count
                if not found or wrong or miscounted:
                    seen = ", ".join(b.status.value for b in found) or "none"
                    wanted = f"{step.count} x " if step.count is not None else ""
                    raise StepFailed(
                        f"{step.target} bookings: {seen}, expected {wanted}{step.status}"
                    )
                return f"{len(found)} {step.target} booking(s) {step.status}"
            case ExpectPurchases():
                found = [b for b in snap.live_bookings if matches(b, step.target)]
                sizes = tuple(len(b.passenger_user_ids) for b in found)
                if sizes != step.sizes:
                    raise StepFailed(
                        f"{step.target} purchases carry {sizes}, expected {step.sizes}"
                    )
                supplier = found[0].supplier_id if found else "?"
                return f"{step.target} on {supplier}: purchases of {' + '.join(map(str, sizes))}"
            case ExpectHold():
                return self._expect_hold(step, snap)
            case ExpectAgentRuns():
                ids = {b.id for b in snap.bookings if matches(b, step.target)}
                runs = [r for r in snap.runs if r.booking_id in ids]
                if len(runs) != step.count:
                    raise StepFailed(
                        f"{len(runs)} agent run(s) for {step.target}, expected {step.count}"
                    )
                return f"{len(runs)} agent run(s) for {step.target}"
            case ExpectShares():
                return self._expect_shares(step, snap)
            case ExpectEvent():
                wanted = str(getattr(step.kind, "value", step.kind))
                if not any(e.kind.value == wanted for e in snap.events):
                    raise StepFailed(f"no {wanted} event in the feed")
                return f"{wanted} is in the feed"
            case ExpectWinner():
                return await self._expect_winner(step, snap)
            case ExpectBudget():
                return await self._expect_budget(step, snap)
            case ExpectAgentMessage():
                wanted = step.text.casefold()
                said = [
                    e
                    for e in snap.events
                    if e.actor is EventActor.AGENT and wanted in e.message.casefold()
                ]
                if not said:
                    raise StepFailed(f"the agent never said “{step.text}”")
                return said[-1].message
            case _:
                raise StepFailed(f"unknown step {step!r}")

    def _expect_hold(self, step: ExpectHold, snap: Snapshot) -> str:
        now = self.world.clock.now()
        found = [b for b in snap.live_bookings if matches(b, step.target)]
        if not found:
            raise StepFailed(f"no live {step.target} booking")
        wrong = [b for b in found if hold_is_live(b.hold_expires_at, now) is not step.live]
        if wrong:
            state = ", ".join(f"{b.hold_ref or 'no hold'} until {b.hold_expires_at}" for b in wrong)
            raise StepFailed(f"{step.target}: {state} (now {now:%Y-%m-%d %H:%M})")
        if not step.live:
            return f"{len(found)} {step.target} booking(s) without a live hold"
        until = min(b.hold_expires_at for b in found if b.hold_expires_at is not None)
        return f"{len(found)} {step.target} booking(s) held until {until:%Y-%m-%d %H:%M} UTC"

    async def _expect_winner(self, step: ExpectWinner, snap: Snapshot) -> str:
        proposals = await ProposalRepository().for_trip(self.world.trip_oid)
        if not 0 <= step.index < len(proposals):
            raise StepFailed(f"there is no package #{step.index}")
        expected = proposals[step.index]
        won = next(
            (i for i, p in enumerate(proposals) if p.id == snap.trip.chosen_proposal_id), None
        )
        if won != step.index or snap.trip.total_minor != expected.total_minor:
            raise StepFailed(
                f"package #{won} won with total {snap.trip.total_minor}, expected "
                f"#{step.index} ({expected.total_minor})"
            )
        return f"#{step.index} “{expected.title}” won, total {expected.total_minor}"

    async def _expect_budget(self, step: ExpectBudget, snap: Snapshot) -> str:
        budget = snap.trip.budget_per_person_minor
        if budget is None:
            raise StepFailed("the brief has no budget")
        proposals = await ProposalRepository().for_trip(self.world.trip_oid)
        currency = snap.trip.currency
        within = [p for p in proposals if p.per_person_minor <= budget]
        misflagged = [p.title for p in proposals if p.over_budget != (p.per_person_minor > budget)]
        problems = []
        if len(within) != step.within:
            cheapest = min((p.per_person_minor for p in proposals), default=0)
            problems.append(
                f"{len(within)}/{len(proposals)} packages fit the budget of "
                f"{format_money(budget, currency)} pp, expected {step.within} (cheapest "
                f"{format_money(cheapest, currency)} pp)"
            )
        if misflagged:
            problems.append(f"wrong over_budget flag on {', '.join(misflagged)}")
        if problems:
            raise StepFailed("; ".join(problems))
        flags = ", ".join(
            f"#{i} {format_money(p.per_person_minor, currency)} pp"
            f"{' OVER' if p.over_budget else ''}"
            for i, p in enumerate(proposals)
        )
        return f"{step.within} within {format_money(budget, currency)} pp: {flags}"

    def _expect_shares(self, step: ExpectShares, snap: Snapshot) -> str:
        names = self._names()
        counted = [c for c in snap.contributions if c.amount_minor > 0]
        problems = []
        if step.members is not None and len(counted) != step.members:
            problems.append(f"{len(counted)} non-zero shares, expected {step.members}")
        for contribution in snap.contributions:
            name = names.get(contribution.user_id, "?")
            wanted: ContributionStatus | None = step.per_member.get(name, step.status)
            if wanted is not None and contribution.status is not wanted:
                problems.append(f"{name} is {contribution.status}, expected {wanted}")
            if step.vs_initial and contribution.amount_minor > 0 and name in self.initial_shares:
                trend = _trend(contribution.amount_minor, self.initial_shares[name])
                if trend != step.vs_initial:
                    problems.append(f"{name}'s share is {trend} than at voting close")
        if problems:
            raise StepFailed("; ".join(problems))
        currency = snap.trip.currency
        return ", ".join(
            f"{names.get(c.user_id, '?').split()[0]} {format_money(c.amount_minor, currency)}"
            f"/{format_money(c.paid_minor, currency)} {c.status.value}"
            for c in snap.contributions
        )

    # ---- plumbing -------------------------------------------------------------------------

    def _names(self) -> dict[PydanticObjectId, str]:
        return {
            oid: name
            for name, uid in self.world.users.items()
            if (oid := to_object_id(uid)) is not None
        }

    async def _snapshot(self) -> Snapshot:
        return await load_snapshot(self.world.trip_oid)

    async def _observe(self) -> Snapshot:
        snap = await self._snapshot()
        if not self.trail or self.trail[-1] is not snap.trip.status:
            self.trail.append(snap.trip.status)
        return snap

    async def _wait_for_agents(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.wait_timeout_s
        while True:
            snap = await self._observe()
            busy = [b for b in snap.live_bookings if b.status in _BUSY]
            awaiting = sum(
                1 for b in snap.live_bookings if b.status is BookingStatus.AWAITING_APPROVAL
            )
            monitors = [task for task in running_monitors() if not task.done()]
            if not busy and len(monitors) <= awaiting:
                return
            if loop.time() > deadline:
                state = ", ".join(
                    f"{(b.mode or b.kind).value}={b.status.value}" for b in snap.live_bookings
                )
                raise StepFailed(f"agents did not settle within {self.wait_timeout_s:g}s ({state})")
            await asyncio.sleep(self.world.options.poll_s)

    async def _booking_line(self, prefix: str) -> str:
        snap = await self._snapshot()
        state = ", ".join(
            f"{(b.mode or b.kind).value}={b.status.value}" for b in snap.live_bookings
        )
        return f"{prefix} — {state}"

    @staticmethod
    def _raise_on(result: Result[Any, Any], prefix: str = "") -> None:
        if isinstance(result, Err):
            code = _code(result.error)
            raise StepFailed(f"{prefix}{code}", code)

    async def _release_agents(self) -> None:
        """Rejects every summary still waiting (so a live agent exits), then stops monitors."""
        runs_dir = self.world.bookings.runs_dir
        try:
            snap = await self._snapshot()
        except Exception:
            snap = None
        if snap is not None:
            for booking in snap.live_bookings:
                if booking.status is BookingStatus.AWAITING_APPROVAL and booking.current_run_id:
                    path = runs_dir / booking.current_run_id / "approval.json"
                    path.write_text(json.dumps({"approved": False}), encoding="utf-8")
        if pending := [task for task in running_monitors() if not task.done()]:
            await asyncio.wait(pending, timeout=5.0)
        tasks = running_monitors()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.world.runner.cancel_all()

    # ---- the verdict --------------------------------------------------------------------

    async def _travellers(self, final: Snapshot) -> list[str]:
        """Who was booked, safe to print: the name, which fields exist, a masked document."""
        details = await self.world.travellers.details_for(final.members)
        lines = []
        for member in final.members:
            found = details[member.user_id]
            fields = ", ".join(sorted(f.value for f in found.provided_fields()))
            masked = masked_document_number(found.document_number) or "-"
            lines.append(f"{found.full_name}: {fields}; document {masked}")
        return lines

    def _summarize(self, final: Snapshot, result: ScenarioResult) -> None:
        names = self._names()
        members = {m.user_id for m in final.members}
        result.currency = final.trip.currency
        result.total_minor = final.trip.total_minor
        result.trip_status = final.trip.status.value
        result.money = [
            MoneyRow(
                member=names.get(c.user_id, "?"),
                share_minor=c.amount_minor,
                paid_minor=c.paid_minor,
                status=c.status.value,
                is_member=c.user_id in members,
            )
            for c in final.contributions
        ]
        travellers = len(final.members)
        result.bookings = [
            BookingRecord(
                target=(b.mode or b.kind).value,
                title=b.title,
                supplier_id=b.supplier_id or "-",
                channel=b.channel.value,
                passengers=len(b.passenger_user_ids) or travellers,
                amount_minor=b.amount_minor,
                status=b.status.value,
                hold_expires_at=f"{b.hold_expires_at:%Y-%m-%d %H:%M}" if b.hold_expires_at else "",
                confirmation_ref=b.confirmation_ref or "",
                hold_ref=b.hold_ref or "",
            )
            for b in final.bookings
        ]
        live_runs = set(getattr(self.world.launcher, "live_runs", []))
        for run in final.runs:
            booking: Booking | None = final.booking(run.booking_id)
            seconds = (
                (run.finished_at - run.started_at).total_seconds()
                if run.finished_at and run.started_at
                else 0.0
            )
            result.agent_runs.append(
                AgentRunRecord(
                    run_id=run.run_id,
                    kind=(booking.mode or booking.kind).value if booking else "?",
                    title=booking.title if booking else "?",
                    booking_status=booking.status.value if booking else "?",
                    outcome=run.outcome.value if run.outcome else run.status.value,
                    steps=run.steps,
                    reason=run.reason,
                    confirmation_ref=(booking.confirmation_ref or "") if booking else "",
                    seconds=round(seconds, 1),
                    live=run.run_id in live_runs,
                )
            )

    def _judge(self, result: ScenarioResult) -> None:
        failed = [s for s in result.steps if s.outcome == "failed"]
        pending = [s for s in result.steps if s.outcome == "pending"]
        unknown = [v for v in result.violations if v.known is None]
        known = [v for v in result.violations if v.known is not None]
        problems = [f"step {s.index} {s.label}: {s.detail}" for s in failed] + [
            f"{v.invariant}: {v.message}" for v in unknown
        ]
        if self.scenario.xfail:
            if problems:
                result.outcome, result.reason = "xfail", self.scenario.xfail
            elif pending:
                result.outcome, result.reason = "pending", pending[0].detail
            else:
                result.outcome = "xpass"
                result.reason = f"expected to fail ({self.scenario.xfail}) but passed"
        elif problems:
            result.outcome, result.reason = "fail", problems[0]
        elif pending:
            result.outcome, result.reason = (
                "pending",
                f"step {pending[0].index}: {pending[0].detail}",
            )
        elif known:
            reasons = sorted({f"{v.invariant} ({v.known})" for v in known})
            result.outcome, result.reason = "known", "; ".join(reasons)


def world_suppliers(world: World) -> list[str]:
    return [
        f"{adapter.id} ({adapter.capabilities.channel.value}"
        + (
            f", cap {adapter.capabilities.max_party_per_purchase}"
            if adapter.capabilities.max_party_per_purchase
            else ""
        )
        + (", holds" if adapter.capabilities.supports_hold else "")
        + ")"
        for adapter in world.suppliers
    ]


def _trend(now: int, then: int) -> str:
    return "higher" if now > then else "lower" if now < then else "equal"
