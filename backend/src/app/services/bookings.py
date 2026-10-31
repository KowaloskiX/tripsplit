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
from dataclasses import dataclass
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
    exceeds_tolerance,
    format_delta,
    format_money,
    is_valid_run_id,
    refund_minor,
    repriced_minor,
    run_id_for,
)
from app.core.domain.errors import BookingError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import (
    AgentOutcome,
    AgentRunStatus,
    BookingKind,
    BookingStatus,
    EventActor,
    EventKind,
    MemberRole,
    TripStatus,
)
from app.db.client import Database
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.bookings import AgentRun, Booking
from app.models.trips import Trip, TripMember
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
from app.services.resplit import MemberShare, Resplit, resplit_payload, resplit_shares
from app.suppliers.quotes import QuoteProvider, StaticQuotes

logger = logging.getLogger(__name__)

STATUS_FILE = "status.json"
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
class TripBookings:
    trip: Trip
    is_organizer: bool
    travellers: int
    items: list[BookingWithRun]


@dataclass(frozen=True, slots=True)
class LiveStatus:
    """`status.json` as the runner writes it; every field optional while the run boots."""

    milestone: str | None
    reached: list[str]
    step: int
    reason: str
    outcome: str | None
    cost_usd: float


@dataclass(frozen=True, slots=True)
class RunView:
    run: AgentRun
    live: LiveStatus


@dataclass(frozen=True, slots=True)
class Frame:
    content: bytes
    media_type: str


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


def _live_status(raw: dict[str, Any] | None) -> LiveStatus:
    raw = raw or {}
    reached = raw.get("reached")
    return LiveStatus(
        milestone=raw.get("milestone") if isinstance(raw.get("milestone"), str) else None,
        reached=[item for item in reached if isinstance(item, str)]
        if isinstance(reached, list)
        else [],
        step=int(raw.get("step") or 0),
        reason=str(raw.get("reason") or ""),
        outcome=raw.get("outcome") if isinstance(raw.get("outcome"), str) else None,
        cost_usd=float(raw.get("cost_usd") or 0.0),
    )


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


def _split_name(display_name: str) -> tuple[str, str]:
    first, _, last = display_name.strip().partition(" ")
    return first, last.strip()


def _passengers_of(booking: Booking, members: list[TripMember]) -> list[TripMember]:
    """The members travelling on THIS purchase, in vault order. A booking created before
    passengers were recorded per purchase covers the whole trip."""
    if not booking.passenger_user_ids:
        return members
    by_user = {member.user_id: member for member in members}
    return [by_user[user_id] for user_id in booking.passenger_user_ids if user_id in by_user]


def _party_size(booking: Booking, members: list[TripMember]) -> int:
    return len(_passengers_of(booking, members)) or len(members)


def _what_is_bought(booking: Booking, travellers: int) -> str:
    if booking.kind is BookingKind.TRAIN:
        return f"{travellers} tickets"
    if booking.kind is BookingKind.STAY:
        return f"the stay for {travellers}"
    return booking.title


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
        quotes: QuoteProvider | None = None,
        price_tolerance_percent: float = 0.0,
        payments: PaymentProvider | None = None,
    ) -> None:
        self.db = db
        # Refunds overpayments once the trip is booked (see `_settle_refunds`).
        self.payments: PaymentProvider = payments if payments is not None else FakePayments()
        self.launcher = launcher
        # Asked for the current price right before every launch (see `_requote`).
        self.quotes: QuoteProvider = quotes if quotes is not None else StaticQuotes()
        self.price_tolerance_percent = price_tolerance_percent
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

    async def run_status(self, run_id: str, user_id: str) -> Result[RunView, BookingError]:
        found = await self._run_for_member(run_id, user_id)
        if not isinstance(found, Ok):
            return found
        run, run_dir = found.value
        raw = await asyncio.to_thread(_read_json, run_dir / STATUS_FILE)
        return Ok(RunView(run=run, live=_live_status(raw)))

    async def frame(self, run_id: str, user_id: str) -> Result[Frame, BookingError]:
        found = await self._run_for_member(run_id, user_id)
        if not isinstance(found, Ok):
            return found
        frame = await asyncio.to_thread(_read_frame, found.value[1])
        return Ok(frame) if frame is not None else Err(BookingError.FRAME_NOT_FOUND)

    # ---- start ----------------------------------------------------------------------------

    async def start(
        self, trip_id: str, booking_id: str, user_id: str
    ) -> Result[BookingWithRun, BookingError]:
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
        requoted = await self._requote(trip, booking)
        if requoted is not None:
            return Err(requoted)

        members = await self.members.for_trip(identifier_of(trip))
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
            f"On it — buying {_what_is_bought(booking, party)} on {booking.supplier}.",
            booking,
        )

        spec = LaunchSpec(
            run_id=run_id,
            url=booking.supplier_url,
            goal=self._goal_for(booking, party),
            vault=await self._vault_for(trip, booking, members),
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

    def _goal_for(self, booking: Booking, travellers: int) -> str:
        return (
            f"{booking.goal} Passengers on this purchase: {travellers}. Fill traveller names "
            "and the contact email from the vault. Stop at the final summary, before paying."
        )

    async def _vault_for(
        self, trip: Trip, booking: Booking, members: list[TripMember]
    ) -> dict[str, str]:
        """Values the agent may TYPE — names and contact, never shown to the planner.

        Passengers are THIS booking's only, numbered from 1: the second purchase of a split
        train starts again at `passenger_1`. The contact is always the organizer.
        """
        organizer = await self.users.get_by_id(trip.organizer_id)
        passengers = _passengers_of(booking, members)
        vault: dict[str, str] = {"passengers": str(len(passengers))}
        if organizer is not None:
            vault["email"] = organizer.email
        lead = next((member for member in members if member.role is MemberRole.ORGANIZER), None)
        if lead is not None:
            vault["first_name"], vault["last_name"] = _split_name(lead.display_name)
        for index, member in enumerate(passengers, start=1):
            first, last = _split_name(member.display_name)
            vault[f"passenger_{index}_first_name"] = first
            vault[f"passenger_{index}_last_name"] = last
        return {key: value for key, value in vault.items() if value}

    # ---- re-quote -------------------------------------------------------------------------

    async def _requote(self, trip: Trip, booking: Booking) -> BookingError | None:
        """Asks the supplier for the current price before buying. None = go ahead.

        Sold out -> the booking FAILS (a human may still finish it by hand). A price beyond
        the tolerance -> the booking takes the new amount and the shares are re-split; a rise
        that leaves somebody owing sends the trip back to PAYING (Rule #1) and stops here, a
        drop only marks refunds and the purchase proceeds.
        """
        quoted = await self.quotes.quote(booking)
        if quoted is None:
            if await self.bookings.update_if_status(
                booking, BOOKING_STATUSES_THAT_START, {"status": BookingStatus.FAILED}
            ):
                await self._say(
                    trip,
                    EventKind.BOOKING_FAILED,
                    f"{booking.supplier} no longer offers {booking.title}. Pick another option "
                    "or book it by hand.",
                    booking,
                )
            return BookingError.SOLD_OUT
        previous = booking.amount_minor
        if not exceeds_tolerance(previous, quoted, self.price_tolerance_percent):
            return None

        async def write(session: AsyncClientSession) -> Resplit | None:
            # Conditioned on the amount and status read before the quote: of two concurrent
            # starts only one applies the new price.
            moved = await self.bookings.update_if(
                booking,
                {"amount_minor": previous, "status": {"$in": list(BOOKING_STATUSES_THAT_START)}},
                {"amount_minor": quoted},
                session,
            )
            if not moved:
                return None
            bookings = await self.bookings.for_trip(identifier_of(trip), session)
            total = sum(b.amount_minor for b in bookings if b.status is not BookingStatus.CANCELLED)
            plan = await resplit_shares(trip, total, session, announce=False)
            if plan.owes:
                await self.trips.set_status(trip, TripStatus.PAYING, session)
            await self._say_price_changed(trip, booking, previous, plan, session)
            return plan

        plan = await self.db.in_transaction(write)
        if plan is None:
            return BookingError.BOOKING_NOT_STARTABLE
        return BookingError.PRICE_CHANGED if plan.owes else None

    async def _say_price_changed(
        self,
        trip: Trip,
        booking: Booking,
        previous_minor: int,
        plan: Resplit,
        session: AsyncClientSession,
    ) -> None:
        current = booking.amount_minor
        money = trip.currency
        rose = current > previous_minor
        verb = "raised" if rose else "lowered"
        message = (
            f"{booking.supplier} {verb} the price of {booking.title} from "
            f"{format_money(previous_minor, money).removesuffix(' ' + money)} to "
            f"{format_money(current, money)}"
        )
        if plan.shares:
            each = max(abs(share.change.delta_minor) for share in plan.shares)
            message += f" — {format_money(each, money)} {'more' if rose else 'less'} each."
        else:
            message += "."
        if plan.owes:
            message += " Top up and I will buy it."
        elif plan.refunds:
            message += " The difference will be refunded — buying it now."
        else:
            message += " Buying it now."
        payload = {
            **resplit_payload(plan),
            "booking_id": to_text(identifier_of(booking)),
            "previous_amount_minor": previous_minor,
            "amount_minor": current,
        }
        await self.events.add(
            identifier_of(trip),
            EventKind.PRICE_CHANGED,
            EventActor.AGENT,
            message[:4000],
            payload=payload,
            session=session,
        )

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
            return
        status = booking_status_after(outcome)
        if status is BookingStatus.CONFIRMED and booking.status is not BookingStatus.APPROVED:
            # Defence in depth: the runner pays only after `approval.json` says so, and the
            # approval marks the booking APPROVED first. A purchase reported without it is
            # not trusted blindly — a human checks it on the supplier site.
            status = BookingStatus.HANDOFF
            reason = f"The agent reported a purchase nobody approved — check it. {reason}"
        confirmation = str((raw or {}).get("confirmation_ref") or "") or None
        changes: dict[str, Any] = {"status": status}
        if status is BookingStatus.CONFIRMED:
            changes["confirmation_ref"] = confirmation
        await self.bookings.update(booking, changes)
        await self._announce_finish(trip, booking, status, reason, run_id)

    async def _announce_finish(
        self, trip: Trip, booking: Booking, status: BookingStatus, reason: str, run_id: str
    ) -> None:
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
        payload: dict[str, Any] = dict(extra)
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
        run = await self._current_run(booking)
        if booking.status is not BookingStatus.AWAITING_APPROVAL or run is None:
            return Err(BookingError.NOT_AWAITING_APPROVAL)
        if approved and not await self._may_buy(trip):
            return Err(BookingError.TRIP_NOT_READY)
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
        await self._maybe_trip_booked(trip)
        return Ok(BookingWithRun(booking=booking, run=await self._current_run(booking)))

    # ---- disruption -----------------------------------------------------------------------

    async def simulate_disruption(
        self,
        trip_id: str,
        user_id: str,
        booking_id: str | None,
        delay_minutes: int,
        price_change_percent: float,
    ) -> Result[Disruption, BookingError]:
        """A delay hits a bought train: EVERY confirmed purchase of that train (a party above
        the supplier's cap is several bookings of one package item) is cancelled and replaced
        by a PENDING booking for the same passengers, each repriced on its own to whole grosze,
        followed by ONE re-split of the new total."""
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, _ = access.value
        # BOOKING too: a demo books the train first, and a delay can hit it before the rest
        # is bought. Without a CONFIRMED booking there is nothing to disrupt either way.
        if trip.status not in (TripStatus.BOOKING, TripStatus.BOOKED):
            return Err(BookingError.NOTHING_TO_DISRUPT)
        bookings = await self.bookings.for_trip(identifier_of(trip))
        targets = self._disrupted_bookings(bookings, booking_id)
        if not targets:
            return Err(BookingError.NOTHING_TO_DISRUPT)

        new_amounts = [repriced_minor(t.amount_minor, price_change_percent) for t in targets]
        target_ids = {target.id for target in targets}
        new_total = sum(new_amounts) + sum(
            booking.amount_minor
            for booking in bookings
            if booking.status is not BookingStatus.CANCELLED and booking.id not in target_ids
        )
        previous_total = trip.total_minor
        old_amount = sum(target.amount_minor for target in targets)
        new_amount = sum(new_amounts)
        lead = targets[0]

        async def write(session: AsyncClientSession) -> tuple[list[Booking], Resplit]:
            replacements: list[Booking] = []
            for target, amount in zip(targets, new_amounts, strict=True):
                await self.bookings.update(target, {"status": BookingStatus.CANCELLED}, session)
                replacements.append(
                    await self.bookings.add(
                        self._replacement_for(target, amount, delay_minutes), session
                    )
                )
            await self.trips.set_status(trip, TripStatus.DISRUPTED, session)
            parts = f" ({len(targets)} purchases)" if len(targets) > 1 else ""
            await self._say(
                trip,
                EventKind.DISRUPTION,
                f"{lead.supplier} reports a {delay_minutes} min delay on {lead.title}{parts}. "
                f"I found a later train for "
                f"{format_money(new_amount, trip.currency)} "
                f"({format_delta(new_amount - old_amount, trip.currency)}) "
                f"and cancelled the old booking{'s' if len(targets) > 1 else ''}.",
                replacements[0],
                session,
                replaces_booking_id=to_text(identifier_of(lead)),
                booking_ids=[to_text(identifier_of(r)) for r in replacements],
                replaces_booking_ids=[to_text(identifier_of(t)) for t in targets],
            )
            plan = await resplit_shares(trip, new_total, session)
            final_status = TripStatus.PAYING if plan.owes else TripStatus.REBOOKING
            await self.trips.set_status(trip, final_status, session)
            return replacements, plan

        replacements, plan = await self.db.in_transaction(write)
        return Ok(
            Disruption(
                cancelled=targets,
                replacements=replacements,
                trip=trip,
                previous_total_minor=previous_total,
                shares=plan.shares,
            )
        )

    @staticmethod
    def _replacement_for(target: Booking, amount_minor: int, delay_minutes: int) -> Booking:
        return Booking(
            trip_id=target.trip_id,
            kind=target.kind,
            title=f"{target.title} (rebooked)"[:200],
            supplier=target.supplier,
            supplier_url=target.supplier_url,
            goal=(
                f"{target.goal} REBOOKING: the original train is delayed by "
                f"{delay_minutes} min — choose the next later departure on the same "
                "route and date."
            )[:4000],
            amount_minor=amount_minor,
            replaces_booking_id=identifier_of(target),
            passenger_user_ids=target.passenger_user_ids,
            proposal_item_index=target.proposal_item_index,
            train_query=target.train_query,
        )

    @staticmethod
    def _disrupted_bookings(bookings: list[Booking], booking_id: str | None) -> list[Booking]:
        """The confirmed purchases of the disrupted item: the given booking's item, or the
        first confirmed train's. Parts of one item share `proposal_item_index`; a booking
        without one (created before items were recorded) stands alone."""
        confirmed = [booking for booking in bookings if booking.status is BookingStatus.CONFIRMED]
        if booking_id is not None:
            wanted = to_object_id(booking_id)
            first = next((booking for booking in confirmed if booking.id == wanted), None)
        else:
            first = next((b for b in confirmed if b.kind is BookingKind.TRAIN), None)
        if first is None:
            return []
        if first.proposal_item_index is None:
            return [first]
        return [
            booking
            for booking in confirmed
            if booking.kind is first.kind
            and booking.proposal_item_index == first.proposal_item_index
        ]
