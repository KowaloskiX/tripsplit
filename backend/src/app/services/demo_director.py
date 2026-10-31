"""The demo director: a hands-free choreography of a whole group trip, for the stage.

Dev/test only (the route layer answers 404 elsewhere). It plays the seeded friends of a trip —
they join one by one, chat, vote with a believable spread that converges on one package and
pay their shares one by one — strictly through the real services. Nothing here bypasses a
rule: votes go through `ProposalService.vote`, payments through `ContributionService.pay`,
the vote close and the disruption are the organizer's own calls. Booking starts on its own only
when the AUTO_BOOK feature exists (see `DirectorFeatures`); otherwise the director waits for
the presenter to buy.

One run per trip at a time, in-process (`DirectorRegistry`): progress is readable while it
plays and the run can be stopped. A restart forgets it — the trip itself keeps every effect.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from beanie import PydanticObjectId

from app.core.background import BackgroundRunner
from app.core.domain.demo_director import (
    DirectorPace,
    DirectorPhase,
    DirectorScript,
    DirectorState,
)
from app.core.domain.errors import BookingError, TripError
from app.core.domain.packages import format_money
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import BookingKind, BookingStatus, EventKind, MemberRole, TripStatus
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.trips import Proposal, Trip, TripMember
from app.repositories.auth import UserRepository
from app.repositories.bookings import BookingRepository
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    ProposalRepository,
    TripRepository,
    VoteRepository,
)
from app.services.bookings import BookingService
from app.services.contributions import ContributionService
from app.services.demo import DEMO_EMAIL_DOMAIN, DemoService
from app.services.proposals import ProposalService
from app.services.trip_access import load_access, require_organizer
from app.services.trips import JOINABLE_STATUSES, TripService

logger = logging.getLogger(__name__)

type Sleep = Callable[[float], Awaitable[None]]

DISRUPTION_DELAY_MINUTES = 95
# A later train costs a little more: the group tops up on stage.
DISRUPTION_PRICE_CHANGE_PERCENT = 8.0


@dataclass(frozen=True, slots=True)
class DirectorTimings:
    """Delays between actions (a random value in the range) and how long a wait may last."""

    beat_s: tuple[float, float]
    poll_s: float
    research_wait_s: float
    payment_wait_s: float
    booking_wait_s: float

    @classmethod
    def for_pace(cls, pace: DirectorPace) -> "DirectorTimings":
        if pace is DirectorPace.STAGE:
            return cls((1.5, 3.0), 1.0, 180.0, 300.0, 600.0)
        return cls((0.2, 0.6), 0.25, 120.0, 60.0, 120.0)


@dataclass(frozen=True, slots=True)
class DirectorTuning:
    """How the director waits: real `asyncio.sleep` and the pace's timings by default; a test
    passes a fast clock (and may observe every pause, e.g. to check invariants)."""

    sleep: Sleep = asyncio.sleep
    timings: DirectorTimings | None = None


@dataclass(frozen=True, slots=True)
class DirectorFeatures:
    """Features of other workstreams the director adapts to, detected rather than imported:
    AUTO_BOOK (the last payment starts the purchase) and the wallet (a payment method)."""

    auto_book: bool = False
    wallet: bool = False


@dataclass(frozen=True, slots=True)
class DirectorOptions:
    script: DirectorScript
    pace: DirectorPace
    # True: the director pays every friend but leaves the organizer's share to the presenter,
    # so the decisive last payment is made by hand on stage.
    leave_organizer_payment: bool = False
    # FULL only: end with a delayed train (needs a confirmed transport booking).
    with_disruption: bool = True


@dataclass(frozen=True, slots=True)
class DirectorBeat:
    at: datetime
    phase: DirectorPhase
    actor: str  # a member's display name, "Director" or "Agent"
    text: str


@dataclass(slots=True)
class DirectorProgress:
    trip_id: str
    script: DirectorScript
    pace: DirectorPace
    features: DirectorFeatures
    state: DirectorState = DirectorState.RUNNING
    phase: DirectorPhase = DirectorPhase.STARTING
    beats: list[DirectorBeat] = field(default_factory=list)
    error: str | None = None
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DirectorCast:
    """The real services the director acts through."""

    demo: DemoService
    trips: TripService
    proposals: ProposalService
    contributions: ContributionService
    bookings: BookingService


class DirectorAborted(Exception):
    """A step the script cannot continue without failed; the message says which."""


# Short, human group-chat lines. Picked deterministically per trip (seeded random).
JOIN_LINES = ("I'm in!", "Count me in 🙌")
VOTE_LINES = ("This one looks great", "Hmm, I like this one more")
SWITCH_LINE = "Ok, outvoted, switching 🙌"
PAY_LINES = ("paid with BLIK ✅", "paid by card", "done, Apple Pay", "sent!", "paid with BLIK")
WALLET_PAY_LINE = "paid from wallet 💸"
DISRUPTION_LINES = ("Train delayed?! 😱", "Agent's on it 👀")
TOP_UP_LINE = "topped up, all good"


class DemoDirector:
    """One run of one script on one trip, on behalf of its organizer."""

    def __init__(
        self,
        cast: DirectorCast,
        progress: DirectorProgress,
        options: DirectorOptions,
        organizer_id: str,
        *,
        sleep: Sleep = asyncio.sleep,
        timings: DirectorTimings | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.cast = cast
        self.progress = progress
        self.options = options
        self.organizer_id = organizer_id
        self.trip_id = progress.trip_id
        self.sleep = sleep
        self.timings = timings or DirectorTimings.for_pace(options.pace)
        self.rng = rng or random.Random(progress.trip_id)
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.users = UserRepository()
        self.proposals = ProposalRepository()
        self.votes = VoteRepository()
        self.contributions = ContributionRepository()
        self.bookings = BookingRepository()

    # ---- the run --------------------------------------------------------------------------

    async def run(self) -> None:
        """Never raises (it runs in the background): the outcome lands in `progress`."""
        try:
            await self._play()
        except asyncio.CancelledError:
            self._finish(DirectorState.STOPPED)
            raise
        except DirectorAborted as aborted:
            self._finish(DirectorState.FAILED, str(aborted))
        except Exception as error:  # the boundary of a background job: report, never crash
            logger.exception("demo director failed on trip %s", self.trip_id)
            self._finish(DirectorState.FAILED, f"unexpected error: {error}")
        else:
            self._finish(DirectorState.DONE)

    async def _play(self) -> None:
        script = self.options.script
        if script is DirectorScript.FULL:
            await self._join()
            await self._research()
        if script in (DirectorScript.FULL, DirectorScript.VOTE_AND_PAY):
            await self._vote()
            await self._pay(DirectorPhase.PAYING, PAY_LINES)
            await self._booking_handover()
        if script is DirectorScript.DISRUPTION or (
            script is DirectorScript.FULL and self.options.with_disruption
        ):
            await self._disruption()

    def _finish(self, state: DirectorState, error: str | None = None) -> None:
        self.progress.state = state
        self.progress.error = error
        self.progress.phase = DirectorPhase.FINISHED
        self.progress.finished_at = utc_now()

    # ---- helpers --------------------------------------------------------------------------

    def _beat(self, actor: str, text: str) -> None:
        self.progress.beats.append(DirectorBeat(utc_now(), self.progress.phase, actor, text))

    async def _pause(self) -> None:
        low, high = self.timings.beat_s
        await self.sleep(self.rng.uniform(low, high))

    async def _trip(self) -> Trip:
        trip_oid = to_object_id(self.trip_id)
        trip = await self.trips.get(trip_oid) if trip_oid is not None else None
        if trip is None:
            raise DirectorAborted("the trip no longer exists")
        return trip

    async def _wait_for(
        self, done: Callable[[Trip], Awaitable[bool]], seconds: float
    ) -> Trip | None:
        """Polls the trip until `done` holds; None when the wait ran out."""
        polls = max(1, round(seconds / self.timings.poll_s)) if self.timings.poll_s else 1
        for _ in range(polls):
            trip = await self._trip()
            if await done(trip):
                return trip
            await self.sleep(self.timings.poll_s)
        return None

    async def _friends(self, trip: Trip) -> list[TripMember]:
        """The seeded members (reserved `.invalid` email domain), in join order."""
        friends: list[TripMember] = []
        for member in await self.members.for_trip(identifier_of(trip)):
            user = await self.users.get_by_id(member.user_id)
            if user is not None and user.email.endswith(f"@{DEMO_EMAIL_DOMAIN}"):
                friends.append(member)
        return friends

    async def _say(self, member: TripMember, text: str) -> None:
        """A friend's chat line — the real `post_message`. A refused line is not worth
        aborting the show for."""
        result = await self.cast.trips.post_message(self.trip_id, to_text(member.user_id), text)
        if isinstance(result, Ok):
            self._beat(member.display_name, f"💬 {text}")

    # ---- scenes ---------------------------------------------------------------------------

    async def _join(self) -> None:
        self.progress.phase = DirectorPhase.JOINING
        trip = await self._trip()
        if trip.status not in JOINABLE_STATUSES:
            self._beat("Director", "Joining is over for this trip. Skipping the arrivals.")
            return
        present = len(await self.members.for_trip(identifier_of(trip)))
        wanted = trip.group_size - present
        lines = list(JOIN_LINES)
        if trip.destination:  # "Prague in Nov 🍻"
            lines[1] = f"{trip.destination} in {trip.date_from:%b} 🍻"
        for index in range(max(wanted, 0)):
            before = {m.user_id for m in await self.members.for_trip(identifier_of(trip))}
            seeded = await self.cast.demo.seed_members(self.trip_id, self.organizer_id, 1)
            if not isinstance(seeded, Ok) or seeded.value == 0:
                self._beat("Director", "No more demo friends can join.")
                return
            after = await self.members.for_trip(identifier_of(trip))
            newcomer = next(m for m in after if m.user_id not in before)
            self._beat(newcomer.display_name, "joined the trip")
            await self._pause()
            if index < 2:  # a couple of lines, not a wall of chat
                await self._say(newcomer, lines[index % len(lines)])
                await self._pause()

    async def _research(self) -> None:
        self.progress.phase = DirectorPhase.RESEARCHING
        trip = await self._trip()
        if trip.status is TripStatus.COLLECTING:
            started = await self.cast.proposals.generate(self.trip_id, self.organizer_id)
            if not isinstance(started, Ok):
                raise DirectorAborted(f"could not start the research ({started.error})")
            self._beat("Agent", "Researching packages…")

        async def settled(fresh: Trip) -> bool:
            if fresh.status is TripStatus.COLLECTING:
                raise DirectorAborted("the research failed, see the trip feed")
            return fresh.status is not TripStatus.PROPOSING

        if await self._wait_for(settled, self.timings.research_wait_s) is None:
            raise DirectorAborted("the research did not finish in time")
        self._beat("Agent", "Packages are on the table.")
        await self._pause()

    async def _vote(self) -> None:
        self.progress.phase = DirectorPhase.VOTING
        trip = await self._trip()
        if trip.status is not TripStatus.VOTING:
            self._beat("Director", "The vote is already closed. Skipping it.")
            return
        proposals = await self.proposals.for_trip(identifier_of(trip))
        if not proposals:
            raise DirectorAborted("there are no packages to vote on")
        target = await self._target(trip, proposals)
        others = [p for p in proposals if identifier_of(p) != identifier_of(target)]
        friends = await self._friends(trip)
        if not friends:
            raise DirectorAborted("no demo friends on this trip; run the full script")

        # A believable spread: the second and fourth friend fancy another package first.
        dissenters: list[TripMember] = []
        for index, friend in enumerate(friends):
            choice = others[(index // 2) % len(others)] if others and index in (1, 3) else target
            await self._cast_vote(friend, choice)
            if choice is not target:
                dissenters.append(friend)
            if index < len(VOTE_LINES):
                await self._say(friend, VOTE_LINES[index])
            await self._pause()
        # ... and come round once they see the tally.
        for friend in dissenters:
            await self._say(friend, SWITCH_LINE)
            await self._cast_vote(friend, target)
            await self._pause()

        closed = await self.cast.proposals.close_voting(self.trip_id, self.organizer_id)
        if not isinstance(closed, Ok):
            raise DirectorAborted(f"could not close the vote ({closed.error})")
        self._beat("Agent", f"The group picked “{target.title}”.")
        await self._pause()

    async def _target(self, trip: Trip, proposals: Sequence[Proposal]) -> Proposal:
        """The package the friends converge on: the organizer's vote when they cast one (the
        presenter's choice wins), else the agent's first proposal."""
        organizer_vote = next(
            (
                vote
                for vote in await self.votes.for_trip(identifier_of(trip))
                if vote.user_id == trip.organizer_id
            ),
            None,
        )
        if organizer_vote is not None:
            for proposal in proposals:
                if identifier_of(proposal) == organizer_vote.proposal_id:
                    return proposal
        return proposals[0]

    async def _cast_vote(self, friend: TripMember, proposal: Proposal) -> None:
        result = await self.cast.proposals.vote(
            self.trip_id, to_text(friend.user_id), to_text(identifier_of(proposal))
        )
        if not isinstance(result, Ok):
            raise DirectorAborted(f"{friend.display_name} could not vote ({result.error})")
        self._beat(friend.display_name, f"voted for “{proposal.title}”")

    async def _pay(self, phase: DirectorPhase, lines: Sequence[str]) -> None:
        """Every outstanding share, one by one, friends first and the organizer last."""
        self.progress.phase = phase
        trip = await self._trip()
        if trip.status is not TripStatus.PAYING:
            self._beat("Director", "Nobody owes anything right now.")
            return
        members = await self.members.for_trip(identifier_of(trip))
        owing = {
            c.user_id
            for c in await self.contributions.for_trip(identifier_of(trip))
            if c.amount_minor > c.paid_minor
        }
        organizer = next((m for m in members if m.role is MemberRole.ORGANIZER), None)
        friends = [m for m in members if m.role is not MemberRole.ORGANIZER]
        line_pool = list(lines)
        for index, friend in enumerate(f for f in friends if f.user_id in owing):
            await self._pay_for(trip, friend)
            line = line_pool[index % len(line_pool)]
            if self.progress.features.wallet and index == 1:
                line = WALLET_PAY_LINE
            await self._say(friend, line)
            await self._pause()
        if organizer is None or organizer.user_id not in owing:
            return
        if self.options.leave_organizer_payment:
            await self._wait_for_organizer(organizer)
        else:
            await self._pay_for(trip, organizer)
            await self._pause()

    async def _pay_for(self, trip: Trip, member: TripMember) -> None:
        # Seeded members cannot top up by hand: like demo pay-all, the director credits each
        # wallet with exactly the shortfall first (a no-op when payments are not wallet-backed).
        await self.cast.demo.fund(trip, member)
        result = await self.cast.contributions.pay(self.trip_id, to_text(member.user_id))
        if isinstance(result, Err):
            if result.error is TripError.ALREADY_PAID:
                return
            raise DirectorAborted(f"{member.display_name} could not pay ({result.error})")
        self._beat(
            member.display_name, f"paid {format_money(result.value.paid_minor, trip.currency)}"
        )
        if result.value.all_paid:
            self._beat("Agent", "Everyone paid. The agent can book now.")

    async def _wait_for_organizer(self, organizer: TripMember) -> None:
        self.progress.phase = DirectorPhase.WAITING_FOR_ORGANIZER
        self._beat("Director", f"Over to you, {organizer.display_name}: make the last payment.")

        async def paid(fresh: Trip) -> bool:
            return fresh.status is not TripStatus.PAYING

        if await self._wait_for(paid, self.timings.payment_wait_s) is None:
            raise DirectorAborted("the organizer did not pay in time")

    async def _booking_handover(self) -> None:
        self.progress.phase = DirectorPhase.BOOKING
        trip = await self._trip()
        if trip.status not in (TripStatus.BOOKING, TripStatus.REBOOKING, TripStatus.BOOKED):
            return
        if self.progress.features.auto_book:
            self._beat("Agent", "AUTO_BOOK is on, so the agent starts buying.")
        else:
            self._beat("Director", "Everyone paid. Over to you: start the booking.")

    async def _disruption(self) -> None:
        self.progress.phase = DirectorPhase.DISRUPTION
        confirmed = await self._wait_for(self._has_confirmed_transport, self.timings.booking_wait_s)
        if confirmed is None:
            self._beat("Director", "No confirmed transport yet. Skipping the disruption.")
            return
        await self._pause()
        result = await self.cast.bookings.simulate_disruption(
            self.trip_id,
            self.organizer_id,
            booking_id=None,
            delay_minutes=DISRUPTION_DELAY_MINUTES,
            price_change_percent=DISRUPTION_PRICE_CHANGE_PERCENT,
        )
        if isinstance(result, Err):
            if result.error is BookingError.NOTHING_TO_DISRUPT:
                self._beat("Director", "Nothing to disrupt.")
                return
            raise DirectorAborted(f"the disruption failed ({result.error})")
        self._beat("Agent", f"Delay of {DISRUPTION_DELAY_MINUTES} min. Rebooking a later train.")
        friends = await self._friends(confirmed)
        for friend, line in zip(friends, DISRUPTION_LINES, strict=False):
            await self._pause()
            await self._say(friend, line)
        await self._pause()
        await self._pay(DirectorPhase.TOPPING_UP, (TOP_UP_LINE,))

    async def _has_confirmed_transport(self, trip: Trip) -> bool:
        return any(
            booking.kind is BookingKind.TRANSPORT and booking.status is BookingStatus.CONFIRMED
            for booking in await self.bookings.for_trip(identifier_of(trip))
        )


class DirectorRegistry:
    """The runs of this process, one per trip. Lives on the application state."""

    def __init__(self) -> None:
        self._runs: dict[str, tuple[DirectorProgress, asyncio.Task[None]]] = {}

    def get(self, trip_id: str) -> DirectorProgress | None:
        entry = self._runs.get(trip_id)
        return entry[0] if entry is not None else None

    def start(self, director: DemoDirector, runner: BackgroundRunner) -> bool:
        """False when a run is already playing on the trip."""
        current = self.get(director.trip_id)
        if current is not None and current.state is DirectorState.RUNNING:
            return False
        task = runner.spawn(director.run(), name=f"demo-director-{director.trip_id}")
        self._runs[director.trip_id] = (director.progress, task)
        return True

    async def stop(self, trip_id: str) -> DirectorProgress | None:
        entry = self._runs.get(trip_id)
        if entry is None:
            return None
        progress, task = entry
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if progress.state is DirectorState.RUNNING:  # cancelled before its first await
            progress.state = DirectorState.STOPPED
            progress.finished_at = utc_now()
        return progress


class DemoDirectorService:
    """Starts, reads and stops director runs; the organizer only."""

    def __init__(
        self,
        cast: DirectorCast,
        registry: DirectorRegistry,
        runner: BackgroundRunner,
        features: DirectorFeatures,
        tuning: DirectorTuning | None = None,
    ) -> None:
        self.cast = cast
        self.registry = registry
        self.runner = runner
        self.features = features
        self.tuning = tuning or DirectorTuning()
        self.trips = TripRepository()
        self.members = MemberRepository()

    async def _organizer(self, trip_id: str, user_id: str) -> Result[str, TripError]:
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        if (error := require_organizer(access.value)) is not None:
            return Err(error)
        return Ok(to_text(identifier_of(access.value.trip)))

    async def start(
        self, trip_id: str, user_id: str, options: DirectorOptions
    ) -> Result[DirectorProgress, TripError]:
        allowed = await self._organizer(trip_id, user_id)
        if not isinstance(allowed, Ok):
            return allowed
        progress = DirectorProgress(
            trip_id=allowed.value, script=options.script, pace=options.pace, features=self.features
        )
        director = DemoDirector(
            self.cast,
            progress,
            options,
            user_id,
            sleep=self.tuning.sleep,
            timings=self.tuning.timings,
        )
        if not self.registry.start(director, self.runner):
            return Err(TripError.INVALID_STATE)
        return Ok(progress)

    async def progress(self, trip_id: str, user_id: str) -> Result[DirectorProgress, TripError]:
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        found = self.registry.get(to_text(identifier_of(access.value.trip)))
        return Ok(found) if found is not None else Err(TripError.NOT_FOUND)

    async def stop(self, trip_id: str, user_id: str) -> Result[DirectorProgress, TripError]:
        allowed = await self._organizer(trip_id, user_id)
        if not isinstance(allowed, Ok):
            return allowed
        stopped = await self.registry.stop(allowed.value)
        return Ok(stopped) if stopped is not None else Err(TripError.NOT_FOUND)


# ---- the six-phone grid -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhoneView:
    user_id: str
    name: str
    initials: str
    is_organizer: bool
    is_demo: bool
    last_message: str | None
    voted_for_proposal_id: str | None
    voted_for_title: str | None
    paid: bool
    amount_minor: int | None
    paid_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class PhonesView:
    trip_id: str
    status: TripStatus
    phones: tuple[PhoneView, ...]


def initials_of(name: str) -> str:
    parts = [part for part in name.split() if part]
    letters = "".join(part[0] for part in parts[:2]) if parts else "?"
    return letters.upper()


class PhonesService:
    """One compact card per member — what each phone in the grid shows."""

    def __init__(self) -> None:
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.users = UserRepository()
        self.proposals = ProposalRepository()
        self.votes = VoteRepository()
        self.contributions = ContributionRepository()
        self.events = EventRepository()

    async def phones(self, trip_id: str, user_id: str) -> Result[PhonesView, TripError]:
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        trip = access.value.trip
        trip_oid = identifier_of(trip)
        members = await self.members.for_trip(trip_oid)
        titles = {identifier_of(p): p.title for p in await self.proposals.for_trip(trip_oid)}
        votes = {vote.user_id: vote.proposal_id for vote in await self.votes.for_trip(trip_oid)}
        shares = {c.user_id: c for c in await self.contributions.for_trip(trip_oid)}
        last_message: dict[PydanticObjectId, str] = {}
        for event in await self.events.feed(trip_oid):
            if event.kind is EventKind.MESSAGE and event.actor_user_id is not None:
                last_message[event.actor_user_id] = event.message
        phones = []
        for member in members:
            user = await self.users.get_by_id(member.user_id)
            share = shares.get(member.user_id)
            vote = votes.get(member.user_id)
            phones.append(
                PhoneView(
                    user_id=to_text(member.user_id),
                    name=member.display_name,
                    initials=initials_of(member.display_name),
                    is_organizer=member.role is MemberRole.ORGANIZER,
                    is_demo=user is not None and user.email.endswith(f"@{DEMO_EMAIL_DOMAIN}"),
                    last_message=last_message.get(member.user_id),
                    voted_for_proposal_id=to_text(vote) if vote is not None else None,
                    voted_for_title=titles.get(vote) if vote is not None else None,
                    paid=share is not None and share.paid_minor >= share.amount_minor,
                    amount_minor=share.amount_minor if share is not None else None,
                    paid_minor=share.paid_minor if share is not None else 0,
                    currency=trip.currency,
                )
            )
        return Ok(PhonesView(trip_id=to_text(trip_oid), status=trip.status, phones=tuple(phones)))


def detect_features(settings: object) -> DirectorFeatures:
    """Feature-detects AUTO_BOOK and wallet payments (`PAYMENTS=wallet`) from the settings."""
    auto_book = getattr(settings, "auto_book", False)
    return DirectorFeatures(
        auto_book=auto_book is True or str(auto_book).lower() in {"on", "true", "1"},
        wallet=getattr(settings, "payments", "fake") == "wallet",
    )
