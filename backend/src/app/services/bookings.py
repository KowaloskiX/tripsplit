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

from app.agent.launcher import AgentLauncher, LaunchSpec, RunHandle
from app.core.domain.bookings import (
    BOOKING_STATUSES_THAT_START,
    TRIP_STATUSES_THAT_BUY,
    ShareChange,
    all_confirmed,
    booking_status_after,
    format_delta,
    format_money,
    is_valid_run_id,
    repriced_minor,
    resplit,
    run_id_for,
)
from app.core.domain.errors import BookingError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import (
    AgentOutcome,
    AgentRunStatus,
    BookingKind,
    BookingStatus,
    ContributionStatus,
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
from app.repositories.auth import UserRepository
from app.repositories.bookings import AgentRunRepository, BookingRepository
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    TripRepository,
)

logger = logging.getLogger(__name__)

STATUS_FILE = "status.json"
RESULT_FILE = "result.json"
APPROVAL_FILE = "approval.json"  # read by `app.agent.runner` (`--await-approval`)
LIVE_FRAME = "live.jpg"
AWAITING_APPROVAL_OUTCOME = "awaiting_approval"

# Strong references to the monitors: the event loop keeps only weak ones, so an unreferenced
# task can be garbage-collected mid-run.
_MONITORS: set[asyncio.Task[None]] = set()


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
class MemberShare:
    user_id: PydanticObjectId
    display_name: str
    change: ShareChange


@dataclass(frozen=True, slots=True)
class Disruption:
    cancelled: Booking
    replacement: Booking
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
    ) -> None:
        self.db = db
        self.launcher = launcher
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

        members = await self.members.for_trip(identifier_of(trip))
        attempt = len(await self.runs.for_booking(identifier_of(booking))) + 1
        run_id = run_id_for(to_text(identifier_of(booking)), attempt)
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
            return Err(BookingError.BOOKING_NOT_STARTABLE)
        await self.bookings.update(
            booking, {"status": BookingStatus.RUNNING, "current_run_id": run_id}
        )
        await self._say(
            trip,
            EventKind.BOOKING_STARTED,
            f"On it — buying {_what_is_bought(booking, len(members))} on {booking.supplier}.",
            booking,
        )

        spec = LaunchSpec(
            run_id=run_id,
            url=booking.supplier_url,
            goal=self._goal_for(booking, len(members)),
            vault=await self._vault_for(trip, members),
            max_steps=self.max_steps,
            headful=self.headful,
        )
        try:
            handle = await self.launcher.start(spec)
        except Exception:
            logger.exception("could not launch the agent for run %s", run_id)
            await self._finish(run_id, None, launch_failed=True)
            return Ok(BookingWithRun(booking=booking, run=run))
        task = asyncio.create_task(self._watch(run_id, handle), name=f"agent-run-{run_id}")
        _MONITORS.add(task)
        task.add_done_callback(_MONITORS.discard)
        return Ok(BookingWithRun(booking=booking, run=run))

    def _goal_for(self, booking: Booking, travellers: int) -> str:
        return (
            f"{booking.goal} Group size: {travellers} travellers. Fill traveller names and the "
            "contact email from the vault. Stop at the final summary, before paying."
        )

    async def _vault_for(self, trip: Trip, members: list[TripMember]) -> dict[str, str]:
        """Values the agent may TYPE — names and contact, never shown to the planner."""
        organizer = await self.users.get_by_id(trip.organizer_id)
        vault: dict[str, str] = {"passengers": str(len(members))}
        if organizer is not None:
            vault["email"] = organizer.email
        for index, member in enumerate(members, start=1):
            first, last = _split_name(member.display_name)
            vault[f"passenger_{index}_first_name"] = first
            vault[f"passenger_{index}_last_name"] = last
            if member.role is MemberRole.ORGANIZER:
                vault["first_name"], vault["last_name"] = first, last
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
            await self._finish(run_id, None, launch_failed=True)

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
        travellers = len(await self.members.for_trip(run.trip_id))
        money = format_money(booking.amount_minor, trip.currency)
        await self._say(
            trip,
            EventKind.BOOKING_AWAITING_APPROVAL,
            f"Summary ready: {money} for {travellers} people. Approve to pay.",
            booking,
            run_id=run_id,
        )

    async def _finish(
        self, run_id: str, exit_code: int | None, launch_failed: bool = False
    ) -> None:
        run = await self.runs.get_by_run_id(run_id)
        if run is None:
            return
        raw = (
            None
            if launch_failed
            else await asyncio.to_thread(_read_json, self.runs_dir / run_id / RESULT_FILE)
        )
        outcome = _outcome_of(raw) if raw is not None else AgentOutcome.ERROR
        reason = str((raw or {}).get("reason") or "")
        if raw is None:
            reason = (
                "The agent could not be started."
                if launch_failed
                else f"The agent exited (code {exit_code}) without a result."
            )
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
        if booking is None or trip is None or booking.status is BookingStatus.CANCELLED:
            return
        status = booking_status_after(outcome)
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
        if fresh is None or fresh.status is TripStatus.BOOKED:
            return
        await self.trips.set_status(fresh, TripStatus.BOOKED)
        await self._say(
            fresh,
            EventKind.MESSAGE,
            "Everything is booked. I will keep an eye on delays until you are home.",
            None,
        )

    async def _say(
        self,
        trip: Trip,
        kind: EventKind,
        message: str,
        booking: Booking | None,
        session: AsyncClientSession | None = None,
        **extra: str,
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
        await asyncio.to_thread(_write_approval, self.runs_dir / run.run_id, approved)
        status = BookingStatus.APPROVED if approved else BookingStatus.HANDOFF
        await self.bookings.update(booking, {"status": status})
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

    # ---- disruption -----------------------------------------------------------------------

    async def simulate_disruption(
        self,
        trip_id: str,
        user_id: str,
        booking_id: str | None,
        delay_minutes: int,
        price_change_percent: float,
    ) -> Result[Disruption, BookingError]:
        access = await self._organizer(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, _ = access.value
        if trip.status is not TripStatus.BOOKED:
            return Err(BookingError.NOTHING_TO_DISRUPT)
        bookings = await self.bookings.for_trip(identifier_of(trip))
        target = self._disrupted_booking(bookings, booking_id)
        if target is None:
            return Err(BookingError.NOTHING_TO_DISRUPT)

        new_amount = repriced_minor(target.amount_minor, price_change_percent)
        new_total = new_amount + sum(
            booking.amount_minor
            for booking in bookings
            if booking.status is not BookingStatus.CANCELLED and booking.id != target.id
        )
        contributions = await self.contributions.for_trip(identifier_of(trip))
        names = {
            member.user_id: member.display_name
            for member in await self.members.for_trip(identifier_of(trip))
        }
        changes = (
            resplit(
                new_total,
                [contribution.amount_minor for contribution in contributions],
                [contribution.paid_minor for contribution in contributions],
            )
            if contributions
            else []
        )
        owes = any(change.status is ContributionStatus.PENDING for change in changes)
        final_status = TripStatus.PAYING if owes else TripStatus.REBOOKING
        previous_total = trip.total_minor
        shares = [
            MemberShare(
                user_id=contribution.user_id,
                display_name=names.get(contribution.user_id, ""),
                change=change,
            )
            for contribution, change in zip(contributions, changes, strict=True)
        ]

        async def write(session: AsyncClientSession) -> Booking:
            await self.bookings.update(target, {"status": BookingStatus.CANCELLED}, session)
            replacement = await self.bookings.add(
                Booking(
                    trip_id=identifier_of(trip),
                    kind=target.kind,
                    title=f"{target.title} (rebooked)"[:200],
                    supplier=target.supplier,
                    supplier_url=target.supplier_url,
                    goal=(
                        f"{target.goal} REBOOKING: the original train is delayed by "
                        f"{delay_minutes} min — choose the next later departure on the same "
                        "route and date."
                    )[:4000],
                    amount_minor=new_amount,
                    replaces_booking_id=identifier_of(target),
                ),
                session,
            )
            await self.trips.set_status(trip, TripStatus.DISRUPTED, session)
            await self._say(
                trip,
                EventKind.DISRUPTION,
                f"{target.supplier} reports a {delay_minutes} min delay on {target.title}. "
                f"I found a later train for "
                f"{format_money(new_amount, trip.currency)} "
                f"({format_delta(new_amount - target.amount_minor, trip.currency)}) "
                "and cancelled the old booking.",
                replacement,
                session,
                replaces_booking_id=to_text(identifier_of(target)),
            )
            await self.trips.update(
                trip, {"status": final_status, "total_minor": new_total}, session
            )
            for contribution, share in zip(contributions, shares, strict=True):
                await self.contributions.update(
                    contribution,
                    {"amount_minor": share.change.share_minor, "status": share.change.status},
                    session,
                )
            if shares:
                await self.events.add(
                    identifier_of(trip),
                    EventKind.RESPLIT,
                    EventActor.AGENT,
                    self._resplit_message(shares, trip.currency, owes),
                    payload=self._resplit_payload(shares, new_total, previous_total),
                    session=session,
                )
            return replacement

        replacement = await self.db.in_transaction(write)
        return Ok(
            Disruption(
                cancelled=target,
                replacement=replacement,
                trip=trip,
                previous_total_minor=previous_total,
                shares=shares,
            )
        )

    @staticmethod
    def _disrupted_booking(bookings: list[Booking], booking_id: str | None) -> Booking | None:
        confirmed = [booking for booking in bookings if booking.status is BookingStatus.CONFIRMED]
        if booking_id is not None:
            wanted = to_object_id(booking_id)
            return next((booking for booking in confirmed if booking.id == wanted), None)
        return next((booking for booking in confirmed if booking.kind is BookingKind.TRAIN), None)

    @staticmethod
    def _resplit_message(shares: list[MemberShare], currency: str, owes: bool) -> str:
        first = shares[0].change
        message = (
            f"New share: {format_money(first.share_minor, currency)} each "
            f"({format_delta(first.delta_minor, currency)})."
        )
        if owes:
            message += " Please top up the difference — I rebook once everyone has paid."
        elif any(share.change.status is ContributionStatus.REFUND_DUE for share in shares):
            message += " The difference will be refunded."
        return message

    @staticmethod
    def _resplit_payload(
        shares: list[MemberShare], total_minor: int, previous_total_minor: int
    ) -> dict[str, Any]:
        return {
            "total_minor": total_minor,
            "previous_total_minor": previous_total_minor,
            "members": [
                {
                    "user_id": to_text(share.user_id),
                    "display_name": share.display_name,
                    "previous_minor": share.change.previous_minor,
                    "share_minor": share.change.share_minor,
                    "delta_minor": share.change.delta_minor,
                    "paid_minor": share.change.paid_minor,
                    "status": share.change.status.value,
                }
                for share in shares
            ],
        }
