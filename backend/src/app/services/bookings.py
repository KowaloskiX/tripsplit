"""Booking orchestration: start the agent, watch its run directory, take the human's approval
of the final pay click, and handle a disruption (rebooking + re-split). No HTTP here.

The agent runs as a subprocess (see `app.agent.launcher`). A background monitor per run polls
`runs/<run_id>/status.json` into the `AgentRun` document and, when the process exits, turns
`result.json` into the booking's final state and a message in the trip feed.
"""

import asyncio
import json
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import DuplicateKeyError

from app.agent.launcher import AgentLauncher, LaunchSpec, PidHandle, RunHandle, live_pid
from app.core.domain.bookings import (
    BOOKING_STATUSES_THAT_START,
    TRIP_STATUSES_THAT_BUY,
    all_confirmed,
    booking_status_after,
    contribution_status,
    format_delta,
    format_money,
    is_valid_run_id,
    refund_minor,
    repriced_minor,
    run_id_for,
)
from app.core.domain.errors import BookingError
from app.core.domain.packages import expected_total_clause
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import mode_noun, price_is_guaranteed, purchase_noun
from app.core.domain.travellers import describe_missing, split_name
from app.core.domain.trips import (
    AgentOutcome,
    AgentRunStatus,
    BookingKind,
    BookingStatus,
    EventActor,
    EventKind,
    MemberRole,
    RunStepSource,
    RunStepStatus,
    SupplierChannel,
    TripStatus,
)
from app.db.client import Database
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.bookings import AgentRun, Booking
from app.models.trips import Trip, TripMember
from app.models.trust import stored_images, stored_links, stored_provenance
from app.payments.fake import FakePayments
from app.payments.ports import PaymentProvider
from app.repositories.auth import UserRepository
from app.repositories.bookings import AgentRunRepository, BookingRepository
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    TripRepository,
)
from app.services.escrow import EscrowService, card_vault
from app.services.resplit import MemberShare, resplit_shares
from app.services.supplier_prices import Clock, SupplierPrices, offer_of, passengers_of
from app.services.travellers import TravellerService
from app.suppliers.call_log import CALL_LOG, CallLog, SupplierCall, recorded_for_trip
from app.suppliers.ports import BookingRef, DisruptionKind, DisruptionNotice, Offer, OfferRef
from app.suppliers.registry import SupplierRegistry

logger = logging.getLogger(__name__)

STATUS_FILE = "status.json"
GRAPH_FILE = "flow_graph.json"
RESULT_FILE = "result.json"
APPROVAL_FILE = "approval.json"  # read by `app.agent.runner` (`--await-approval`)
LIVE_FRAME = "live.jpg"
AWAITING_APPROVAL_OUTCOME = "awaiting_approval"

# Strong references to the monitors: the event loop keeps only weak ones, so an unreferenced
# task can be garbage-collected mid-run.
_MONITORS: set[asyncio.Task[None]] = set()
# Run ids watched by THIS process. After a backend restart it is empty, which is how an
# orphaned run (its monitor died with the old process) is recognised.
_WATCHED: set[str] = set()
# Bookings whose agent run may still need a monitor.
_IN_FLIGHT = frozenset(
    {BookingStatus.RUNNING, BookingStatus.AWAITING_APPROVAL, BookingStatus.APPROVED}
)
LAUNCH_FAILED_REASON = "The agent could not be started."
LOST_REASON = "agent process lost (backend restarted)"
_SETTLED = frozenset({BookingStatus.CANCELLED, BookingStatus.CONFIRMED})
# A handoff or a failure can be finished by a human on the supplier site.
COMPLETABLE_BY_HAND = frozenset({BookingStatus.HANDOFF, BookingStatus.FAILED})


# The record routes map onto a response — named here so `app.routes` need not import models.
type AgentRunRecord = AgentRun


def running_monitors() -> set[asyncio.Task[None]]:
    return set(_MONITORS)


@dataclass(frozen=True, slots=True)
class BookingWithRun:
    booking: Booking
    run: AgentRun | None


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One booking of a "book everything" / "approve the basket" click: what it became, or
    why it was refused (the other bookings of the batch still went ahead)."""

    booking: Booking
    run: AgentRun | None
    error: BookingError | None


@dataclass(frozen=True, slots=True)
class Batch:
    trip: Trip  # read after the batch: a price rise may have sent it back to PAYING
    items: list[BatchItem]


@dataclass(frozen=True, slots=True)
class TripBookings:
    trip: Trip
    is_organizer: bool
    travellers: int
    items: list[BookingWithRun]


@dataclass(frozen=True, slots=True)
class RunStep:
    index: int
    node_id: str | None
    kind: str  # the agent's action ("goto", "click", "fill_form", ...) — an open set
    status: RunStepStatus
    duration_ms: int | None
    source: RunStepSource
    iteration: int | None = None


@dataclass(frozen=True, slots=True)
class LiveStatus:
    """`status.json` as the runner writes it; every field optional while the run boots."""

    milestone: str | None
    reached: list[str]
    step: int
    reason: str
    outcome: str | None
    cost_usd: float
    steps: list[RunStep] = field(default_factory=list)
    # The engine's counters: replayed flow steps, rule steps, planner (LLM) calls, tokens.
    flow_steps: int = 0
    rule_steps: int = 0
    llm_calls: int = 0
    tokens: int = 0


@dataclass(frozen=True, slots=True)
class FlowNode:
    id: str
    type: str  # open_url | fill | choose | click | loop | verify | approve — grows with the agent
    label: str
    stage: str | None
    inputs: list[str]  # variable names (`vault.passenger_{i}_first_name`), never values
    outputs: list[str]


@dataclass(frozen=True, slots=True)
class FlowGraph:
    nodes: list[FlowNode]
    edges: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class RunView:
    run: AgentRun
    live: LiveStatus


@dataclass(frozen=True, slots=True)
class Frame:
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class SupplierActivity:
    call: SupplierCall
    supplier: str  # display name


DEFAULT_ACTIVITY_LIMIT = 50


@dataclass(frozen=True, slots=True)
class Disruption:
    # Every confirmed purchase of the disrupted item and its replacement, in the same order.
    cancelled: list[Booking]
    replacements: list[Booking]
    trip: Trip
    previous_total_minor: int
    shares: list[MemberShare]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _whole(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


# The runner's "plan" source is a follow-up action of an earlier LLM macro plan.
_SOURCE_ALIASES = {"plan": RunStepSource.LLM.value}


def _run_step(raw: object) -> RunStep | None:
    """One `status.json` step, or None when it is not one (the runner writes, we only read)."""
    if not isinstance(raw, dict):
        return None
    index = _whole(raw.get("index"))
    source = str(raw.get("source") or "")
    try:
        status = RunStepStatus(str(raw.get("status")))
        origin = RunStepSource(_SOURCE_ALIASES.get(source, source))
    except ValueError:
        return None
    if index is None or index < 0:
        return None
    node_id = raw.get("node_id")
    duration = _whole(raw.get("duration_ms"))
    iteration = _whole(raw.get("iteration"))
    return RunStep(
        index=index,
        node_id=node_id if isinstance(node_id, str) else None,
        kind=str(raw.get("kind") or "other"),
        status=status,
        duration_ms=max(duration, 0) if duration is not None else None,
        source=origin,
        iteration=iteration if iteration is not None and iteration >= 0 else None,
    )


def _live_status(raw: dict[str, Any] | None) -> LiveStatus:
    raw = raw or {}
    steps = raw.get("steps")
    return LiveStatus(
        milestone=raw.get("milestone") if isinstance(raw.get("milestone"), str) else None,
        reached=_strings(raw.get("reached")),
        step=int(raw.get("step") or 0),
        reason=str(raw.get("reason") or ""),
        outcome=raw.get("outcome") if isinstance(raw.get("outcome"), str) else None,
        cost_usd=float(raw.get("cost_usd") or 0.0),
        steps=[
            step
            for step in (_run_step(item) for item in (steps if isinstance(steps, list) else []))
            if step is not None
        ],
        flow_steps=_whole(raw.get("flow_steps")) or 0,
        rule_steps=_whole(raw.get("rule_steps")) or 0,
        llm_calls=_whole(raw.get("llm_calls")) or 0,
        tokens=_whole(raw.get("tokens")) or 0,
    )


def _flow_graph(raw: dict[str, Any] | None) -> FlowGraph | None:
    """`flow_graph.json` as the runner writes it; None while it does not exist yet."""
    if raw is None or not isinstance(raw.get("nodes"), list):
        return None
    nodes = [
        FlowNode(
            id=str(node["id"]),
            type=str(node.get("type") or "other"),
            label=str(node.get("label") or ""),
            stage=node.get("stage") if isinstance(node.get("stage"), str) else None,
            inputs=_strings(node.get("inputs")),
            outputs=_strings(node.get("outputs")),
        )
        for node in raw["nodes"]
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"]
    ]
    listed = raw.get("edges")
    edges = [
        (edge["from"], edge["to"])
        for edge in (listed if isinstance(listed, list) else [])
        if isinstance(edge, dict)
        and isinstance(edge.get("from"), str)
        and isinstance(edge.get("to"), str)
    ]
    return FlowGraph(nodes=nodes, edges=edges)


def _outcome_of(raw: dict[str, Any] | None) -> AgentOutcome:
    value = (raw or {}).get("outcome")
    try:
        return AgentOutcome(value) if isinstance(value, str) else AgentOutcome.ERROR
    except ValueError:
        return AgentOutcome.UNKNOWN


def _newest_frame(run_dir: Path) -> Path | None:
    candidates = [*run_dir.glob("*.png"), run_dir / LIVE_FRAME]
    existing = [path for path in candidates if path.is_file()]
    return max(existing, key=lambda path: path.stat().st_mtime, default=None)


def _read_frame(run_dir: Path) -> Frame | None:
    path = _newest_frame(run_dir)
    if path is None:
        return None
    try:
        content = path.read_bytes()
    except OSError:  # replaced between the listing and the read — the next poll gets it
        return None
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Frame(content=content, media_type=media_type)


def _write_approval(run_dir: Path, approved: bool) -> None:
    """Atomic: the runner polls this file and must never read half of it."""
    run_dir.mkdir(parents=True, exist_ok=True)
    temporary = run_dir / f"{APPROVAL_FILE}.tmp"
    temporary.write_text(json.dumps({"approved": approved}), encoding="utf-8")
    os.replace(temporary, run_dir / APPROVAL_FILE)


def _party_size(booking: Booking, members: list[TripMember]) -> int:
    return len(passengers_of(booking, members)) or len(members)


def _what_is_bought(booking: Booking, travellers: int) -> str:
    if booking.kind is BookingKind.ACTIVITY:
        return booking.title
    return purchase_noun(booking.kind, booking.mode, travellers)


_CHANNEL_WORDS = {
    SupplierChannel.AGENT: "the agent drives the site",
    SupplierChannel.API: "booked directly",
    SupplierChannel.MANUAL: "booked by hand",
}


class BookingService:
    def __init__(
        self,
        db: Database,
        launcher: AgentLauncher,
        runs_dir: Path,
        *,
        max_steps: int = 40,
        headful: bool = False,
        poll_s: float = 1.0,
        suppliers: SupplierRegistry | None = None,
        price_tolerance_percent: float = 0.0,
        payments: PaymentProvider | None = None,
        clock: Clock = utc_now,
        holds: bool = False,
        call_log: CallLog = CALL_LOG,
        escrow: EscrowService | None = None,
    ) -> None:
        self.db = db
        # The supplier API calls, for the trip's live terminal (`activity`).
        self.call_log = call_log
        # The trip escrow at the payment partner (PAYMENTS=wallet): payouts to API suppliers,
        # single-use virtual cards for the agent. None = no money moves on a purchase.
        self.escrow = escrow
        # Refunds overpayments once the trip is booked (see `_settle_refunds`).
        self.payments: PaymentProvider = payments if payments is not None else FakePayments()
        self.launcher = launcher
        # The supplier plugins: capabilities decide how each booking is bought.
        self.suppliers = suppliers if suppliers is not None else SupplierRegistry()
        self.clock = clock
        # Holds and re-quotes right before every purchase (see `start`).
        self.prices = SupplierPrices(
            db,
            self.suppliers,
            clock=clock,
            price_tolerance_percent=price_tolerance_percent,
            holds=holds,
        )
        self.travellers = TravellerService()
        self.runs_dir = runs_dir.resolve()
        self.max_steps = max_steps
        self.headful = headful
        self.poll_s = poll_s
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.contributions = ContributionRepository()
        self.events = EventRepository()
        self.bookings = BookingRepository()
        self.runs = AgentRunRepository()
        self.users = UserRepository()

    # ---- access ---------------------------------------------------------------------------

    async def _membership(
        self, trip_id: str, user_id: str
    ) -> Result[tuple[Trip, TripMember], BookingError]:
        trip_oid, user_oid = to_object_id(trip_id), to_object_id(user_id)
        if trip_oid is None or user_oid is None:
            return Err(BookingError.TRIP_NOT_FOUND)
        trip = await self.trips.get(trip_oid)
        member = await self.members.get(trip_oid, user_oid) if trip is not None else None
        if trip is None or member is None:
            return Err(BookingError.TRIP_NOT_FOUND)
        return Ok((trip, member))

    async def _organizer(
        self, trip_id: str, user_id: str
    ) -> Result[tuple[Trip, TripMember], BookingError]:
        access = await self._membership(trip_id, user_id)
        if isinstance(access, Ok) and access.value[1].role is not MemberRole.ORGANIZER:
            return Err(BookingError.NOT_ORGANIZER)
        return access

    async def _booking_of(self, trip: Trip, booking_id: str) -> Booking | None:
        booking_oid = to_object_id(booking_id)
        booking = await self.bookings.get(booking_oid) if booking_oid is not None else None
        if booking is None or booking.trip_id != identifier_of(trip):
            return None
        return booking

    async def _current_run(self, booking: Booking) -> AgentRun | None:
        if booking.current_run_id is None:
            return None
        return await self.runs.get_by_run_id(booking.current_run_id)

    async def _run_for_member(
        self, run_id: str, user_id: str
    ) -> Result[tuple[AgentRun, Path], BookingError]:
        if not is_valid_run_id(run_id):
            return Err(BookingError.RUN_NOT_FOUND)
        run = await self.runs.get_by_run_id(run_id)
        if run is None:
            return Err(BookingError.RUN_NOT_FOUND)
        access = await self._membership(to_text(run.trip_id), user_id)
        if not isinstance(access, Ok):
            return Err(BookingError.RUN_NOT_FOUND)
        run_dir = (self.runs_dir / run_id).resolve()
        # Defence in depth on top of the identifier pattern: never serve outside runs/.
        if run_dir.parent != self.runs_dir:
            return Err(BookingError.RUN_NOT_FOUND)
        return Ok((run, run_dir))

    # ---- reads ----------------------------------------------------------------------------

    async def list_for_trip(self, trip_id: str, user_id: str) -> Result[TripBookings, BookingError]:
        access = await self._membership(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, member = access.value
        await self._reconcile_orphans(identifier_of(trip))
        items = [
            BookingWithRun(booking=booking, run=await self._current_run(booking))
            for booking in await self.bookings.for_trip(identifier_of(trip))
        ]
        travellers = len(await self.members.for_trip(identifier_of(trip)))
        return Ok(
            TripBookings(
                trip=trip,
                is_organizer=member.role is MemberRole.ORGANIZER,
                travellers=travellers,
                items=items,
            )
        )

    async def activity(
        self, trip_id: str, user_id: str, limit: int = DEFAULT_ACTIVITY_LIMIT
    ) -> Result[list[SupplierActivity], BookingError]:
        """The trip's recent supplier API calls (members only): no ids, no bodies, no PII."""
        access = await self._membership(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        return Ok(
            [
                SupplierActivity(call=call, supplier=self._supplier_name(call.supplier_id))
                for call in self.call_log.for_trip(trip_id, limit)
            ]
        )

    def _supplier_name(self, supplier_id: str) -> str:
        adapter = self.suppliers.get(supplier_id)
        return adapter.display_name if adapter is not None else supplier_id

    async def run_status(self, run_id: str, user_id: str) -> Result[RunView, BookingError]:
        found = await self._run_for_member(run_id, user_id)
        if not isinstance(found, Ok):
            return found
        run, run_dir = found.value
        raw = await asyncio.to_thread(_read_json, run_dir / STATUS_FILE)
        return Ok(RunView(run=run, live=_live_status(raw)))

    async def graph(self, run_id: str, user_id: str) -> Result[FlowGraph, BookingError]:
        """The run's plan (`flow_graph.json`) — same access rule as its status."""
        found = await self._run_for_member(run_id, user_id)
        if not isinstance(found, Ok):
            return found
        raw = await asyncio.to_thread(_read_json, found.value[1] / GRAPH_FILE)
        graph = _flow_graph(raw)
        return Ok(graph) if graph is not None else Err(BookingError.GRAPH_NOT_FOUND)

    async def frame(self, run_id: str, user_id: str) -> Result[Frame, BookingError]:
        found = await self._run_for_member(run_id, user_id)
        if not isinstance(found, Ok):
            return found
        frame = await asyncio.to_thread(_read_frame, found.value[1])
        return Ok(frame) if frame is not None else Err(BookingError.FRAME_NOT_FOUND)

    # ---- start ----------------------------------------------------------------------------

    @recorded_for_trip
    async def start(
        self, trip_id: str, booking_id: str, user_id: str
    ) -> Result[BookingWithRun, BookingError]:
        """Starts the purchase of one booking, the way its supplier's channel buys it.

        Rule #1 first (everyone paid), then the supplier's required traveller details, then a
        binding price (a live hold or a fresh re-quote). After that: `agent` launches the
        browser agent, `api` goes straight to the human approval (the purchase API is called
        when it is approved), `manual` hands it to a human with instructions.
        """
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, _ = access.value
        booking = await self._booking_of(trip, booking_id)
        if booking is None:
            return Err(BookingError.BOOKING_NOT_FOUND)
        # Rule #1 of the product, enforced here and not in the UI: no buying before every
        # share is paid (stream A moves the trip to BOOKING only then).
        if trip.status not in TRIP_STATUSES_THAT_BUY:
            return Err(BookingError.TRIP_NOT_READY)
        if booking.status not in BOOKING_STATUSES_THAT_START:
            return Err(BookingError.BOOKING_NOT_STARTABLE)
        members = await self.members.for_trip(identifier_of(trip))
        if await self._details_missing(trip, booking, members):
            return Err(BookingError.TRAVELLER_DETAILS_MISSING)
        refused = await self.prices.refresh_split(trip, await self._parts_of(booking))
        if refused is not None:
            return Err(refused)
        booking = await self.bookings.get(identifier_of(booking)) or booking
        refused = await self.prices.refresh(trip, booking)
        if refused is not None:
            return Err(refused)
        booking = await self.bookings.get(identifier_of(booking)) or booking
        match booking.channel:
            case SupplierChannel.API:
                return await self._await_direct_approval(trip, booking, members)
            case SupplierChannel.MANUAL:
                return await self._hand_over(trip, booking)
            case SupplierChannel.AGENT:
                return await self._launch(trip, booking, members)

    @recorded_for_trip
    async def start_all(self, trip_id: str, user_id: str) -> Result[Batch, BookingError]:
        """ "Book everything": starts every startable booking of the trip, one after another,
        each exactly like `start` (Rule #1, traveller details, a binding price). A refusal
        stops nothing but itself — except a price change that sends the trip back to PAYING,
        after which nothing more may start (the rest are reported `trip_not_ready`)."""
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, _ = access.value
        if trip.status not in TRIP_STATUSES_THAT_BUY:
            return Err(BookingError.TRIP_NOT_READY)
        items: list[BatchItem] = []
        for booking in await self.bookings.for_trip(identifier_of(trip)):
            if booking.status not in BOOKING_STATUSES_THAT_START:
                continue
            started = await self.start(trip_id, to_text(identifier_of(booking)), user_id)
            fresh = await self.bookings.get(identifier_of(booking)) or booking
            if isinstance(started, Ok):
                items.append(BatchItem(fresh, started.value.run, None))
            else:
                items.append(BatchItem(fresh, None, started.error))
        return Ok(Batch(trip=await self.trips.get(identifier_of(trip)) or trip, items=items))

    async def _parts_of(self, booking: Booking) -> list[Booking]:
        """Every purchase of the same package item (several when the supplier caps the party),
        this one included; just this one for a booking without an item index."""
        if booking.proposal_item_index is None:
            return [booking]
        return [
            part
            for part in await self.bookings.for_trip(booking.trip_id)
            if part.proposal_item_index == booking.proposal_item_index
            and part.status is not BookingStatus.CANCELLED
        ]

    async def _details_missing(
        self, trip: Trip, booking: Booking, members: list[TripMember]
    ) -> bool:
        """The supplier needs traveller details somebody on THIS purchase has not entered. The
        feed names who and which fields — never a value."""
        capabilities = self.prices.capabilities_of(booking)
        if capabilities is None:
            return False
        passengers = passengers_of(booking, members)
        missing = await self.travellers.missing(passengers, capabilities.required_traveller_fields)
        if not missing:
            return False
        names = {member.user_id: member.display_name for member in passengers}
        described = describe_missing({names[user]: fields for user, fields in missing.items()})
        await self._say(
            trip,
            EventKind.TRAVELLER_DETAILS_MISSING,
            f"Before I can buy {booking.title} on {booking.supplier}, these travellers need to "
            f"add their details: {described}.",
            booking,
            user_ids=[to_text(user) for user in missing],
            fields=sorted({field.value for fields in missing.values() for field in fields}),
        )
        return True

    async def _await_direct_approval(
        self, trip: Trip, booking: Booking, members: list[TripMember]
    ) -> Result[BookingWithRun, BookingError]:
        """channel=api: no agent run — the summary is the supplier's own price, and the human
        approval triggers the purchase API (see `approve`)."""
        moved = await self.bookings.update_if_status(
            booking, BOOKING_STATUSES_THAT_START, {"status": BookingStatus.AWAITING_APPROVAL}
        )
        if not moved:
            return Err(BookingError.BOOKING_NOT_STARTABLE)
        party = _party_size(booking, members)
        money = format_money(booking.amount_minor, trip.currency)
        await self._say(
            trip,
            EventKind.BOOKING_STARTED,
            f"Buying {_what_is_bought(booking, party)} on {booking.supplier} directly.",
            booking,
        )
        await self._say(
            trip,
            EventKind.BOOKING_AWAITING_APPROVAL,
            f"Summary ready: {money} for {party} people on {booking.supplier}. Approve to pay.",
            booking,
        )
        return Ok(BookingWithRun(booking=booking, run=None))

    async def _hand_over(
        self, trip: Trip, booking: Booking
    ) -> Result[BookingWithRun, BookingError]:
        """channel=manual: nothing can be bought for the group — a human does it and enters
        the reference (`complete_manually`)."""
        moved = await self.bookings.update_if_status(
            booking, BOOKING_STATUSES_THAT_START, {"status": BookingStatus.HANDOFF}
        )
        if not moved:
            return Err(BookingError.BOOKING_NOT_STARTABLE)
        await self._say(
            trip,
            EventKind.MESSAGE,
            f"{booking.supplier} is booked by hand: open {booking.supplier_url}, buy "
            f"{booking.title} for {format_money(booking.amount_minor, trip.currency)} and enter "
            "the booking reference here.",
            booking,
            outcome=AgentOutcome.HANDOFF.value,
        )
        return Ok(BookingWithRun(booking=booking, run=None))

    async def _launch(
        self, trip: Trip, booking: Booking, members: list[TripMember]
    ) -> Result[BookingWithRun, BookingError]:
        party = _party_size(booking, members)
        attempt = len(await self.runs.for_booking(identifier_of(booking))) + 1
        run_id = run_id_for(to_text(identifier_of(booking)), attempt)
        # Claimed before the run exists, so a listing meanwhile does not take it for an orphan.
        _WATCHED.add(run_id)
        try:
            run = await self.runs.add(
                AgentRun(
                    run_id=run_id,
                    booking_id=identifier_of(booking),
                    trip_id=identifier_of(trip),
                    status=AgentRunStatus.RUNNING,
                    started_at=utc_now(),
                )
            )
        except DuplicateKeyError:  # a concurrent start for the same booking won the race
            # The claim stays: it belongs to the winner's run (same id) now.
            return Err(BookingError.BOOKING_NOT_STARTABLE)
        await self.bookings.update(
            booking, {"status": BookingStatus.RUNNING, "current_run_id": run_id}
        )
        await self._say(
            trip,
            EventKind.BOOKING_STARTED,
            f"Buying {_what_is_bought(booking, party)} on {booking.supplier}.",
            booking,
        )

        vault = await self._vault_for(trip, booking, members)
        if self.escrow is not None:
            issued = await self.escrow.issue_card(trip, booking, run_id)
            if isinstance(issued, Err):
                await self._finish(
                    run_id,
                    None,
                    failure_reason=f"Razor Trip Pay could not issue a card ({issued.error}).",
                )
                _WATCHED.discard(run_id)
                return Ok(BookingWithRun(booking=booking, run=run))
            # Single-use, limited to exactly this purchase, unfunded until the approval.
            vault.update(card_vault(issued.value.secrets))
        spec = LaunchSpec(
            run_id=run_id,
            url=booking.supplier_url,
            goal=self._goal_for(booking, party, trip.currency),
            vault=vault,
            max_steps=self.max_steps,
            headful=self.headful,
        )
        try:
            handle = await self.launcher.start(spec)
        except Exception:
            logger.exception("could not launch the agent for run %s", run_id)
            await self._finish(run_id, None, failure_reason=LAUNCH_FAILED_REASON)
            _WATCHED.discard(run_id)
            return Ok(BookingWithRun(booking=booking, run=run))
        self._monitor(run_id, handle)
        return Ok(BookingWithRun(booking=booking, run=run))

    def _monitor(self, run_id: str, handle: RunHandle) -> None:
        _WATCHED.add(run_id)
        task = asyncio.create_task(self._watch(run_id, handle), name=f"agent-run-{run_id}")
        _MONITORS.add(task)
        task.add_done_callback(_MONITORS.discard)
        task.add_done_callback(lambda _: _WATCHED.discard(run_id))

    def _goal_for(self, booking: Booking, travellers: int, currency: str) -> str:
        expected = expected_total_clause(
            booking.amount_minor, currency, self.prices.price_tolerance_percent
        )
        return (
            f"{booking.goal} Passengers on this purchase: {travellers}. {expected} Fill "
            "traveller names and the contact email from the vault. Stop at the final summary, "
            "before paying."
        )

    async def _vault_for(
        self, trip: Trip, booking: Booking, members: list[TripMember]
    ) -> dict[str, str]:
        """Values the agent may TYPE — names, contact and the traveller details the supplier
        asks for — never shown to the planner (it sees key placeholders only).

        Passengers are THIS booking's only, numbered from 1: the second purchase of a split
        train starts again at `passenger_1`. The contact is always the organizer.
        """
        organizer = await self.users.get_by_id(trip.organizer_id)
        passengers = passengers_of(booking, members)
        details = await self.travellers.details_for(passengers)
        vault: dict[str, str] = {"passengers": str(len(passengers))}
        if organizer is not None:
            vault["email"] = organizer.email
        lead = next((member for member in members if member.role is MemberRole.ORGANIZER), None)
        if lead is not None:
            vault["first_name"], vault["last_name"] = split_name(lead.display_name)
        for index, member in enumerate(passengers, start=1):
            traveller = details[member.user_id]
            key = f"passenger_{index}"
            vault[f"{key}_first_name"], vault[f"{key}_last_name"] = split_name(traveller.full_name)
            if traveller.date_of_birth is not None:
                vault[f"{key}_date_of_birth"] = traveller.date_of_birth.isoformat()
            if traveller.nationality:
                vault[f"{key}_nationality"] = traveller.nationality
            if traveller.document_number:
                vault[f"{key}_document_number"] = traveller.document_number
            if traveller.document_expiry is not None:
                vault[f"{key}_document_expiry"] = traveller.document_expiry.isoformat()
        return {key: value for key, value in vault.items() if value}

    # ---- monitor --------------------------------------------------------------------------

    async def _watch(self, run_id: str, handle: RunHandle) -> None:
        try:
            waiter = asyncio.ensure_future(handle.wait())
            while True:
                done, _ = await asyncio.wait({waiter}, timeout=self.poll_s)
                await self._sync(run_id)
                if done:
                    break
            await self._finish(run_id, waiter.result())
        except Exception:
            logger.exception("monitor of agent run %s crashed", run_id)
            await self._finish(run_id, None, failure_reason="The agent monitor crashed.")

    async def _reconcile_orphans(self, trip_id: PydanticObjectId) -> None:
        """Runs whose monitor died with a previous backend process must not stay stuck.

        A result on disk is applied as the monitor would have; a still-alive agent gets a new
        monitor; anything else is over — the run ends in ERROR and the booking FAILED.
        """
        for booking in await self.bookings.for_trip(trip_id):
            run_id = booking.current_run_id
            if booking.status not in _IN_FLIGHT or run_id is None or run_id in _WATCHED:
                continue
            run = await self.runs.get_by_run_id(run_id)
            if run is None or run.status is AgentRunStatus.FINISHED or run_id in _WATCHED:
                continue
            # Claimed with no await since the check, so a concurrent listing skips this run.
            _WATCHED.add(run_id)
            await self._adopt(run_id)

    async def _adopt(self, run_id: str) -> None:
        run_dir = self.runs_dir / run_id
        try:
            if await asyncio.to_thread(live_pid, run_dir) is not None:
                logger.warning("re-attaching a monitor to orphaned agent run %s", run_id)
                self._monitor(run_id, PidHandle(run_dir, self.poll_s))
                return
            if await asyncio.to_thread((run_dir / RESULT_FILE).is_file):
                logger.warning("applying the result of orphaned agent run %s", run_id)
                await self._finish(run_id, None)
            else:
                logger.warning("agent run %s was lost with a previous backend", run_id)
                await self._finish(run_id, None, failure_reason=LOST_REASON)
        except BaseException:
            _WATCHED.discard(run_id)
            raise
        _WATCHED.discard(run_id)

    async def _sync(self, run_id: str) -> None:
        """status.json -> AgentRun; the summary being ready -> AWAITING_APPROVAL + feed."""
        run = await self.runs.get_by_run_id(run_id)
        if run is None or run.status is AgentRunStatus.FINISHED:
            return
        live = _live_status(
            await asyncio.to_thread(_read_json, self.runs_dir / run_id / STATUS_FILE)
        )
        changes: dict[str, Any] = {}
        if live.milestone != run.milestone:
            changes["milestone"] = live.milestone
        if live.step != run.steps:
            changes["steps"] = live.step
        if live.reason and live.reason != run.reason:
            changes["reason"] = live.reason[:4000]
        if live.cost_usd != run.cost_usd:
            changes["cost_usd"] = live.cost_usd
        if changes:
            await self.runs.update(run, changes)
        if live.outcome != AWAITING_APPROVAL_OUTCOME:
            return
        booking = await self.bookings.get(run.booking_id)
        trip = await self.trips.get(run.trip_id)
        # Only from RUNNING: an approval that already arrived must not be overwritten.
        if booking is None or trip is None or booking.status is not BookingStatus.RUNNING:
            return
        await self.bookings.update(booking, {"status": BookingStatus.AWAITING_APPROVAL})
        travellers = _party_size(booking, await self.members.for_trip(run.trip_id))
        money = format_money(booking.amount_minor, trip.currency)
        await self._say(
            trip,
            EventKind.BOOKING_AWAITING_APPROVAL,
            f"Summary ready: {money} for {travellers} people. Approve to pay.",
            booking,
            run_id=run_id,
        )

    async def _finish(
        self, run_id: str, exit_code: int | None, failure_reason: str | None = None
    ) -> None:
        run = await self.runs.get_by_run_id(run_id)
        if run is None or run.status is AgentRunStatus.FINISHED:
            return
        raw = (
            None
            if failure_reason is not None
            else await asyncio.to_thread(_read_json, self.runs_dir / run_id / RESULT_FILE)
        )
        outcome = _outcome_of(raw) if raw is not None else AgentOutcome.ERROR
        reason = str((raw or {}).get("reason") or "")
        if raw is None:
            reason = failure_reason or f"The agent exited (code {exit_code}) without a result."
        await self.runs.update(
            run,
            {
                "status": AgentRunStatus.FINISHED,
                "outcome": outcome,
                "reason": reason[:4000],
                "steps": int((raw or {}).get("steps") or run.steps),
                "cost_usd": float((raw or {}).get("cost_usd") or run.cost_usd),
                "finished_at": utc_now(),
            },
        )
        booking = await self.bookings.get(run.booking_id)
        trip = await self.trips.get(run.trip_id)
        # Cancelled (rebooked) or already finished by hand: the run's outcome changes nothing.
        if booking is None or trip is None or booking.status in _SETTLED:
            if booking is not None and self.escrow is not None:
                await self.escrow.close_card(booking)
            return
        status = booking_status_after(outcome)
        if status is BookingStatus.CONFIRMED and booking.status is not BookingStatus.APPROVED:
            # Defence in depth: the runner pays only after `approval.json` says so, and the
            # approval marks the booking APPROVED first. A purchase reported without it is
            # not trusted blindly — a human checks it on the supplier site.
            status = BookingStatus.HANDOFF
            reason = f"The agent reported a purchase nobody approved. Please check it. {reason}"
        if self.escrow is not None:
            status, reason = await self._settle_card(trip, booking, status, reason)
        confirmation = str((raw or {}).get("confirmation_ref") or "") or None
        changes: dict[str, Any] = {"status": status}
        if status is BookingStatus.CONFIRMED:
            changes["confirmation_ref"] = confirmation
        await self.bookings.update(booking, changes)
        await self._announce_finish(trip, booking, status, reason, run_id)

    async def _settle_card(
        self, trip: Trip, booking: Booking, status: BookingStatus, reason: str
    ) -> tuple[BookingStatus, str]:
        """After an agent run: a confirmed purchase must have been paid by its virtual card —
        a run that only simulated the final click is charged by the site's checkout here. A
        declined card is not a purchase: a human takes over. Then the card closes (single
        use) and anything unspent returns to the escrow."""
        assert self.escrow is not None
        if status is BookingStatus.CONFIRMED:
            settled = await self.escrow.settle_site_checkout(trip, booking)
            if isinstance(settled, Err):
                status = BookingStatus.HANDOFF
                reason = (
                    f"{booking.supplier}'s checkout declined the trip's virtual card "
                    f"({settled.error}) — it is limited to exactly "
                    f"{format_money(booking.amount_minor, trip.currency)}. Check the price on "
                    "the site and finish by hand."
                )
        await self.escrow.close_card(booking)
        if status is BookingStatus.CONFIRMED:
            await self.escrow.announce_card_spend(trip, booking)
        return status, reason

    async def _announce_finish(
        self, trip: Trip, booking: Booking, status: BookingStatus, reason: str, run_id: str
    ) -> None:
        """`run_id` is empty for a purchase made without the agent (channel=api)."""
        if status is BookingStatus.CONFIRMED:
            ref = (
                f" Booking number: {booking.confirmation_ref}." if booking.confirmation_ref else ""
            )
            await self._say(
                trip,
                EventKind.BOOKING_CONFIRMED,
                f"Booked {booking.title} on {booking.supplier}.{ref}",
                booking,
                run_id=run_id,
            )
            await self._maybe_trip_booked(trip)
        elif status is BookingStatus.HANDOFF:
            await self._say(
                trip,
                EventKind.MESSAGE,
                f"I need a human to finish {booking.title} on {booking.supplier}: {reason}",
                booking,
                run_id=run_id,
                outcome=AgentOutcome.HANDOFF.value,
            )
        else:
            await self._say(
                trip,
                EventKind.BOOKING_FAILED,
                f"I could not book {booking.title} on {booking.supplier}: {reason}",
                booking,
                run_id=run_id,
            )

    async def _maybe_trip_booked(self, trip: Trip) -> None:
        bookings = await self.bookings.for_trip(identifier_of(trip))
        if not all_confirmed([booking.status for booking in bookings]):
            return
        fresh = await self.trips.get(identifier_of(trip))
        if fresh is None or fresh.status not in TRIP_STATUSES_THAT_BUY:
            return
        # Compare-and-set: of two purchases confirmed at once, exactly one books the trip and
        # pays the refunds out.
        if not await self.trips.transition_status(
            identifier_of(fresh), fresh.status, TripStatus.BOOKED
        ):
            return
        await self._say(
            fresh,
            EventKind.MESSAGE,
            "Everything is booked. I will keep an eye on delays until you are home.",
            None,
        )
        await self._settle_refunds(fresh)
        if self.escrow is not None:
            await self.escrow.return_leftover(fresh)

    async def _settle_refunds(self, trip: Trip) -> None:
        """Pays every overpayment back once the trip is fully bought — not earlier, because a
        later price change or rebooking could still need the money. Each refund goes through
        the payment provider (outside any transaction: a refund is not replayable), then the
        contribution is reduced to its share (PAID) and the feed says so."""
        trip_oid = identifier_of(trip)
        names = {m.user_id: m.display_name for m in await self.members.for_trip(trip_oid)}
        for contribution in await self.contributions.for_trip(trip_oid):
            due = refund_minor(contribution.amount_minor, contribution.paid_minor)
            if due <= 0:
                continue
            receipt = await self.payments.refund(
                to_text(trip_oid), to_text(contribution.user_id), due, trip.currency
            )
            await self.contributions.update(
                contribution,
                {
                    "paid_minor": contribution.paid_minor - receipt.refunded_minor,
                    "status": contribution_status(
                        contribution.amount_minor,
                        contribution.paid_minor - receipt.refunded_minor,
                    ),
                },
            )
            name = names.get(contribution.user_id, "A former member")
            await self.events.add(
                trip_oid,
                EventKind.REFUND_ISSUED,
                EventActor.AGENT,
                f"Refunded {format_money(receipt.refunded_minor, trip.currency)} to {name}.",
                payload={
                    "user_id": to_text(contribution.user_id),
                    "amount_minor": receipt.refunded_minor,
                    "provider_ref": receipt.provider_ref,
                },
            )

    async def _say(
        self,
        trip: Trip,
        kind: EventKind,
        message: str,
        booking: Booking | None,
        session: AsyncClientSession | None = None,
        **extra: str | list[str],
    ) -> None:
        # An empty value (e.g. no run id for an API purchase) is left out of the payload.
        payload: dict[str, Any] = {key: value for key, value in extra.items() if value != ""}
        if booking is not None:
            payload["booking_id"] = to_text(identifier_of(booking))
        await self.events.add(
            identifier_of(trip),
            kind,
            EventActor.AGENT,
            message[:4000],
            payload=payload,
            session=session,
        )

    # ---- approval -------------------------------------------------------------------------

    @recorded_for_trip
    async def approve(
        self, trip_id: str, booking_id: str, user_id: str, approved: bool
    ) -> Result[BookingWithRun, BookingError]:
        """The organizer's decision on a summary. Approving is the pay click, so Rule #1 holds
        here too: refused (`trip_not_ready`) unless the trip is buying and every current share
        is paid — the run keeps waiting and can be approved after the top-ups. Rejecting
        spends nothing and is always allowed."""
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, member = access.value
        booking = await self._booking_of(trip, booking_id)
        if booking is None:
            return Err(BookingError.BOOKING_NOT_FOUND)
        if booking.status is not BookingStatus.AWAITING_APPROVAL:
            return Err(BookingError.NOT_AWAITING_APPROVAL)
        if approved and not await self._may_buy(trip):
            return Err(BookingError.TRIP_NOT_READY)
        if booking.channel is SupplierChannel.API:
            return await self._decide_direct(trip, member, booking, approved)
        run = await self._current_run(booking)
        if run is None:
            return Err(BookingError.NOT_AWAITING_APPROVAL)
        if self.escrow is not None and booking.payment_kind is not None:
            if approved:
                # The pay click: fund the agent's card with exactly this purchase's amount.
                activated = await self.escrow.activate_card(trip, booking)
                if isinstance(activated, Err):
                    await self._say(
                        trip,
                        EventKind.MESSAGE,
                        f"Razor Trip Pay could not fund the card for {booking.title} "
                        f"({activated.error}). Nothing was paid.",
                        booking,
                    )
                    return Err(BookingError.PAYMENT_FAILED)
            else:
                await self.escrow.close_card(booking)
        status = BookingStatus.APPROVED if approved else BookingStatus.HANDOFF
        # Status first (compare-and-set), the runner's file second: the monitor never sees a
        # finished purchase on a booking that is not APPROVED yet.
        moved = await self.bookings.update_if_status(
            booking, frozenset({BookingStatus.AWAITING_APPROVAL}), {"status": status}
        )
        if not moved:
            return Err(BookingError.NOT_AWAITING_APPROVAL)
        await asyncio.to_thread(_write_approval, self.runs_dir / run.run_id, approved)
        verb = "approved the payment" if approved else "rejected the summary"
        await self.events.add(
            identifier_of(trip),
            EventKind.MESSAGE,
            EventActor.MEMBER,
            f"{member.display_name} {verb} for {booking.title}.",
            payload={"booking_id": to_text(identifier_of(booking)), "approved": approved},
            actor_user_id=member.user_id,
        )
        return Ok(BookingWithRun(booking=booking, run=run))

    @recorded_for_trip
    async def approve_all(self, trip_id: str, user_id: str) -> Result[Batch, BookingError]:
        """ "Approve the basket": approves every summary awaiting approval in one click —
        each exactly like `approve`, so refused as a whole (`trip_not_ready`) unless the trip
        is buying and every current share is paid. An API purchase that fails, or a quote
        that went stale, is reported for its booking; the others are still approved."""
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, _ = access.value
        waiting = [
            booking
            for booking in await self.bookings.for_trip(identifier_of(trip))
            if booking.status is BookingStatus.AWAITING_APPROVAL
        ]
        if not waiting:
            return Err(BookingError.NOT_AWAITING_APPROVAL)
        if not await self._may_buy(trip):
            return Err(BookingError.TRIP_NOT_READY)
        items: list[BatchItem] = []
        for booking in waiting:
            booking_id = to_text(identifier_of(booking))
            approved = await self.approve(trip_id, booking_id, user_id, approved=True)
            fresh = await self.bookings.get(identifier_of(booking)) or booking
            if isinstance(approved, Ok):
                items.append(BatchItem(fresh, approved.value.run, None))
            else:
                items.append(BatchItem(fresh, None, approved.error))
        return Ok(Batch(trip=await self.trips.get(identifier_of(trip)) or trip, items=items))

    async def _decide_direct(
        self, trip: Trip, member: TripMember, booking: Booking, approved: bool
    ) -> Result[BookingWithRun, BookingError]:
        """channel=api: approving calls the supplier's purchase API — at the held price, or at
        a quote still within its TTL. A stale price is never paid: the booking goes back to
        PENDING and must be started (re-quoted) again."""
        adapter = self.prices.adapter_of(booking)
        if adapter is None:
            return Err(BookingError.SUPPLIER_UNKNOWN)
        if not approved:
            moved = await self.bookings.update_if_status(
                booking,
                frozenset({BookingStatus.AWAITING_APPROVAL}),
                {"status": BookingStatus.HANDOFF},
            )
            if not moved:
                return Err(BookingError.NOT_AWAITING_APPROVAL)
            await self._say_decision(trip, member, booking, approved=False)
            return Ok(BookingWithRun(booking=booking, run=None))
        guaranteed = price_is_guaranteed(
            adapter.capabilities,
            hold_expires_at=booking.hold_expires_at,
            quoted_at=booking.quoted_at,
            now=self.clock(),
        )
        if not guaranteed:
            await self.bookings.update_if_status(
                booking,
                frozenset({BookingStatus.AWAITING_APPROVAL}),
                {"status": BookingStatus.PENDING},
            )
            return Err(BookingError.QUOTE_EXPIRED)
        moved = await self.bookings.update_if_status(
            booking,
            frozenset({BookingStatus.AWAITING_APPROVAL}),
            {"status": BookingStatus.APPROVED},
        )
        if not moved:
            return Err(BookingError.NOT_AWAITING_APPROVAL)
        await self._say_decision(trip, member, booking, approved=True)
        if self.escrow is not None:
            await self.escrow.sync_target(identifier_of(trip))
            paid = await self.escrow.pay_supplier(trip, booking)
            if isinstance(paid, Err):
                await self.bookings.update(booking, {"status": BookingStatus.FAILED})
                await self._announce_finish(
                    trip,
                    booking,
                    BookingStatus.FAILED,
                    f"Razor Trip Pay refused the payout ({paid.error}); nothing was bought.",
                    "",
                )
                return Ok(BookingWithRun(booking=booking, run=None))
        members = await self.members.for_trip(identifier_of(trip))
        passengers = passengers_of(booking, members)
        details = await self.travellers.details_for(passengers)
        bought = await adapter.purchase(
            offer_of(booking),
            [details[passenger.user_id] for passenger in passengers],
            price_minor=booking.amount_minor,
            hold_ref=booking.hold_ref,
        )
        if isinstance(bought, Ok):
            await self.bookings.update(
                booking, {"status": BookingStatus.CONFIRMED, "confirmation_ref": bought.value}
            )
            await self._announce_finish(trip, booking, BookingStatus.CONFIRMED, "", "")
        else:
            await self.bookings.update(booking, {"status": BookingStatus.FAILED})
            if self.escrow is not None:
                # The supplier did not deliver: it sends the payout back to the escrow.
                await self.escrow.reverse_payout(
                    await self.bookings.get(identifier_of(booking)) or booking
                )
            await self._announce_finish(trip, booking, BookingStatus.FAILED, bought.error, "")
        return Ok(BookingWithRun(booking=booking, run=None))

    async def _say_decision(
        self, trip: Trip, member: TripMember, booking: Booking, *, approved: bool
    ) -> None:
        verb = "approved the payment" if approved else "rejected the summary"
        await self.events.add(
            identifier_of(trip),
            EventKind.MESSAGE,
            EventActor.MEMBER,
            f"{member.display_name} {verb} for {booking.title}.",
            payload={"booking_id": to_text(identifier_of(booking)), "approved": approved},
            actor_user_id=member.user_id,
        )

    async def _may_buy(self, trip: Trip) -> bool:
        """Rule #1 on fresh data: the trip is buying and no current share is unpaid."""
        trip_oid = identifier_of(trip)
        fresh = await self.trips.get(trip_oid)
        if fresh is None or fresh.status not in TRIP_STATUSES_THAT_BUY:
            return False
        current = {member.user_id for member in await self.members.for_trip(trip_oid)}
        return all(
            contribution.paid_minor >= contribution.amount_minor
            for contribution in await self.contributions.for_trip(trip_oid)
            if contribution.user_id in current
        )

    # ---- manual completion ----------------------------------------------------------------

    async def complete_manually(
        self, trip_id: str, user_id: str, booking_id: str, confirmation_ref: str
    ) -> Result[BookingWithRun, BookingError]:
        """The organizer finished a handed-off (or failed) purchase on the supplier site."""
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, member = access.value
        booking = await self._booking_of(trip, booking_id)
        if booking is None:
            return Err(BookingError.BOOKING_NOT_FOUND)
        if booking.status not in COMPLETABLE_BY_HAND:
            return Err(BookingError.NOT_COMPLETABLE)
        # Rule #1 holds for a human too: nothing is bought while somebody still owes.
        if trip.status not in TRIP_STATUSES_THAT_BUY:
            return Err(BookingError.TRIP_NOT_READY)
        completed = await self.bookings.update_if_status(
            booking,
            COMPLETABLE_BY_HAND,
            {"status": BookingStatus.CONFIRMED, "confirmation_ref": confirmation_ref},
        )
        if not completed:
            return Err(BookingError.NOT_COMPLETABLE)
        await self.events.add(
            identifier_of(trip),
            EventKind.BOOKING_CONFIRMED,
            EventActor.MEMBER,
            f"{member.display_name} finished {booking.title} by hand: ref {confirmation_ref}.",
            payload={
                "booking_id": to_text(identifier_of(booking)),
                "confirmation_ref": confirmation_ref,
                "manual": True,
            },
            actor_user_id=member.user_id,
        )
        if self.escrow is not None:
            await self._pay_manual_purchase(trip, booking)
        await self._maybe_trip_booked(trip)
        return Ok(BookingWithRun(booking=booking, run=await self._current_run(booking)))

    async def _pay_manual_purchase(self, trip: Trip, booking: Booking) -> None:
        """A purchase finished by hand is settled from the escrow as a payout to the supplier
        (the partner pays the supplier's invoice) — unless its virtual card already paid."""
        assert self.escrow is not None
        fresh = await self.bookings.get(identifier_of(booking)) or booking
        card = await self.escrow.card_of(fresh)
        if card is not None and card.spent_minor > 0:
            return
        paid = await self.escrow.pay_supplier(trip, fresh)
        if isinstance(paid, Err):
            await self._say(
                trip,
                EventKind.MESSAGE,
                f"Razor Trip Pay could not pay {booking.supplier} for {booking.title} "
                f"({paid.error}) — settle it with the supplier.",
                booking,
            )

    # ---- disruption -----------------------------------------------------------------------

    @recorded_for_trip
    async def simulate_disruption(
        self,
        trip_id: str,
        user_id: str,
        booking_id: str | None,
        delay_minutes: int,
        price_change_percent: float,
    ) -> Result[Disruption, BookingError]:
        """The demo trigger: a delay hits a bought transport (or the given booking). EVERY
        confirmed purchase of that package item (a party above the supplier's cap is several
        bookings) is cancelled and replaced by a PENDING booking for the same passengers, each
        repriced on its own to whole grosze, followed by ONE re-split of the new total."""
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, _ = access.value
        targets = await self._disruptable(trip, booking_id)
        if not targets:
            return Err(BookingError.NOTHING_TO_DISRUPT)
        lead = targets[0]
        noun = mode_noun(lead.mode) if lead.kind is BookingKind.TRANSPORT else "option"
        replacements = [
            self._replacement_for(
                target,
                repriced_minor(target.amount_minor, price_change_percent),
                note=(
                    f"REBOOKING: the original {noun} is delayed by {delay_minutes} min. Choose "
                    "the next later departure on the same route and date."
                ),
            )
            for target in targets
        ]
        headline = f"{lead.supplier} reports a {delay_minutes} min delay on {lead.title}"
        return Ok(await self._rebook(trip, targets, replacements, headline, f"a later {noun}"))

    @recorded_for_trip
    async def check_disruptions(
        self, trip_id: str, user_id: str
    ) -> Result[list[Disruption], BookingError]:
        """Asks every supplier that reports disruptions about the trip's bought bookings. A
        notice with a replacement offer rebooks the whole item onto it: each purchase is
        re-quoted for its own party, the old ones are cancelled, and ONE re-split follows."""
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, _ = access.value
        done: list[Disruption] = []
        members = await self.members.for_trip(identifier_of(trip))
        for booking in await self.bookings.for_trip(identifier_of(trip)):
            adapter = self.prices.adapter_of(booking)
            if (
                adapter is None
                or not adapter.capabilities.reports_disruptions
                or booking.status is not BookingStatus.CONFIRMED
            ):
                continue
            notice = await adapter.status(
                BookingRef(
                    offer=offer_of(booking),
                    confirmation_ref=booking.confirmation_ref,
                    party_size=_party_size(booking, members),
                    hold_ref=booking.hold_ref,
                )
            )
            if notice is None:
                continue
            fresh = await self.trips.get(identifier_of(trip)) or trip
            rebooked = await self._rebook_onto(fresh, booking, notice, members)
            if rebooked is not None:
                done.append(rebooked)
        return Ok(done)

    async def _rebook_onto(
        self, trip: Trip, booking: Booking, notice: DisruptionNotice, members: list[TripMember]
    ) -> Disruption | None:
        targets = await self._disruptable(trip, to_text(identifier_of(booking)))
        adapter = self.prices.adapter_of(booking)
        offer = notice.replacement
        if not targets or adapter is None or offer is None:
            await self._say(
                trip,
                EventKind.DISRUPTION,
                f"{booking.supplier}: {notice.message} I could not find a replacement. Please "
                "rebook it by hand.",
                booking,
            )
            return None
        replacements = []
        for target in targets:
            quote = await adapter.quote(
                OfferRef(offer.supplier_id, offer.offer_ref, offer.supplier_data),
                _party_size(target, members),
            )
            if quote is None:
                return None
            replacements.append(
                self._replacement_for(
                    target,
                    quote.price_minor,
                    offer=offer,
                    note=f"REBOOKING after a {notice.kind.value}: book {offer.title} instead.",
                )
            )
        verb = "cancelled" if notice.kind is DisruptionKind.CANCELLATION else "delayed"
        headline = f"{booking.supplier} {verb} {booking.title}: {notice.message}"
        return await self._rebook(trip, targets, replacements, headline, offer.title)

    async def _disruptable(self, trip: Trip, booking_id: str | None) -> list[Booking]:
        # BOOKING too: a demo books the transport first, and a delay can hit it before the rest
        # is bought. Without a CONFIRMED booking there is nothing to disrupt either way.
        if trip.status not in (TripStatus.BOOKING, TripStatus.BOOKED):
            return []
        bookings = await self.bookings.for_trip(identifier_of(trip))
        return self._disrupted_bookings(bookings, booking_id)

    async def _rebook(
        self,
        trip: Trip,
        targets: list[Booking],
        replacements: list[Booking],
        headline: str,
        found: str,
    ) -> Disruption:
        """Cancels `targets`, adds `replacements` (same order), re-splits ONCE — one
        transaction. A dearer replacement sends the trip to PAYING, otherwise REBOOKING."""
        bookings = await self.bookings.for_trip(identifier_of(trip))
        target_ids = {target.id for target in targets}
        new_amount = sum(replacement.amount_minor for replacement in replacements)
        new_total = new_amount + sum(
            booking.amount_minor
            for booking in bookings
            if booking.status is not BookingStatus.CANCELLED and booking.id not in target_ids
        )
        previous_total = trip.total_minor
        old_amount = sum(target.amount_minor for target in targets)
        lead = targets[0]

        async def write(session: AsyncClientSession) -> tuple[list[Booking], list[MemberShare]]:
            added: list[Booking] = []
            for target, replacement in zip(targets, replacements, strict=True):
                await self.bookings.update(target, {"status": BookingStatus.CANCELLED}, session)
                added.append(await self.bookings.add(replacement.model_copy(), session))
            await self.trips.set_status(trip, TripStatus.DISRUPTED, session)
            parts = f" ({len(targets)} purchases)" if len(targets) > 1 else ""
            await self._say(
                trip,
                EventKind.DISRUPTION,
                f"{headline}{parts}. I found {found} for "
                f"{format_money(new_amount, trip.currency)} "
                f"({format_delta(new_amount - old_amount, trip.currency)}) "
                f"and cancelled the old booking{'s' if len(targets) > 1 else ''}.",
                added[0],
                session,
                replaces_booking_id=to_text(identifier_of(lead)),
                booking_ids=[to_text(identifier_of(r)) for r in added],
                replaces_booking_ids=[to_text(identifier_of(t)) for t in targets],
            )
            plan = await resplit_shares(trip, new_total, session)
            final_status = TripStatus.PAYING if plan.owes else TripStatus.REBOOKING
            await self.trips.set_status(trip, final_status, session)
            return added, plan.shares

        added, shares = await self.db.in_transaction(write)
        if self.escrow is not None:
            # The supplier cancelled: what it was paid comes back into the escrow, and the
            # escrow's release target follows the re-split.
            for target in targets:
                await self.escrow.return_supplier_funds(target)
            await self.escrow.sync_target(identifier_of(trip))
        return Disruption(
            cancelled=targets,
            replacements=added,
            trip=trip,
            previous_total_minor=previous_total,
            shares=shares,
        )

    def _replacement_for(
        self, target: Booking, amount_minor: int, *, note: str, offer: Offer | None = None
    ) -> Booking:
        """A PENDING booking for the same passengers: the same offer (a delay) or the
        supplier's replacement offer (a cancellation)."""
        title = offer.title if offer is not None else target.title
        return Booking(
            trip_id=target.trip_id,
            kind=target.kind,
            mode=target.mode,
            # "Rebooked" is shown from `replaces_booking_id` (a badge), not baked into the title.
            title=title[:200],
            supplier=offer.seller if offer is not None else target.supplier,
            supplier_url=(offer.purchase_url if offer is not None else "") or target.supplier_url,
            goal=f"{target.goal} {note}"[:4000],
            amount_minor=amount_minor,
            replaces_booking_id=identifier_of(target),
            passenger_user_ids=target.passenger_user_ids,
            proposal_item_index=target.proposal_item_index,
            supplier_id=target.supplier_id,
            offer_ref=offer.offer_ref if offer is not None else target.offer_ref,
            channel=target.channel,
            supplier_data=dict(offer.supplier_data) if offer is not None else target.supplier_data,
            # The replacement's price was just given (by the supplier's notice and quote, or
            # by the disruption itself) — binding for the supplier's quote TTL.
            quoted_at=self.clock(),
            links=stored_links(offer.links) if offer is not None else target.links,
            images=stored_images(offer.images) if offer is not None else target.images,
            provenance=stored_provenance(offer.provenance or target.provenance)
            if offer is not None
            else target.provenance,
        )

    @staticmethod
    def _disrupted_bookings(bookings: list[Booking], booking_id: str | None) -> list[Booking]:
        """The confirmed purchases of the disrupted item: the given booking's item, or the
        first confirmed transport's. Parts of one item share `proposal_item_index`; a booking
        without one (created before items were recorded) stands alone."""
        confirmed = [booking for booking in bookings if booking.status is BookingStatus.CONFIRMED]
        if booking_id is not None:
            wanted = to_object_id(booking_id)
            first = next((booking for booking in confirmed if booking.id == wanted), None)
        else:
            first = next((b for b in confirmed if b.kind is BookingKind.TRANSPORT), None)
        if first is None:
            return []
        if first.proposal_item_index is None:
            return [first]
        return [
            booking
            for booking in confirmed
            if booking.kind is first.kind
            and booking.mode is first.mode
            and booking.proposal_item_index == first.proposal_item_index
        ]
