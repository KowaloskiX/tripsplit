"""Packages: research in the background, voting, and closing the vote into shares + bookings.

No HTTP here. Research runs on the application's `BackgroundRunner`, so the request that
started it returns immediately while the agent works.
"""

import asyncio
import logging

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.ai.research import PackagePlan, PackageResearcher, TripBrief
from app.core.background import BackgroundRunner
from app.core.domain.errors import TripError
from app.core.domain.packages import booking_goal, format_money, per_person, pick_winner
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import EventActor, EventKind, TripStatus, split_evenly
from app.db.client import Database
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.bookings import Booking
from app.models.trips import Contribution, Proposal, ProposalItem, Trip
from app.repositories.bookings import BookingRepository
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    ProposalRepository,
    TripRepository,
    VoteRepository,
)
from app.services.trip_access import TripAccess, load_access, require_organizer, require_status
from app.services.trip_views import TripStatusView

logger = logging.getLogger(__name__)

# Statuses from which a (re-)research may start: before the first vote and during voting.
RESEARCHABLE_STATUSES = (TripStatus.COLLECTING, TripStatus.VOTING)


class _StatusChanged(Exception):
    """Raised inside a transaction to abort it when another request moved the trip first."""


class ProposalService:
    def __init__(
        self, db: Database, researcher: PackageResearcher, runner: BackgroundRunner
    ) -> None:
        self.db = db
        self.researcher = researcher
        self.runner = runner
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.proposals = ProposalRepository()
        self.votes = VoteRepository()
        self.contributions = ContributionRepository()
        self.events = EventRepository()
        self.bookings = BookingRepository()

    async def _access(self, trip_id: str, user_id: str) -> Result[TripAccess, TripError]:
        return await load_access(trip_id, user_id, trips=self.trips, members=self.members)

    async def generate(self, trip_id: str, user_id: str) -> Result[TripStatusView, TripError]:
        """Moves the trip to PROPOSING and starts the research in the background."""
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip = access.value.trip
        error = require_organizer(access.value) or require_status(
            access.value, *RESEARCHABLE_STATUSES
        )
        if error is not None:
            return Err(error)
        trip_oid, previous = identifier_of(trip), trip.status
        if not await self.trips.transition_status(trip_oid, previous, TripStatus.PROPOSING):
            return Err(TripError.INVALID_STATE)

        members = await self.members.for_trip(trip_oid)
        brief = TripBrief(
            title=trip.title,
            origin=trip.origin,
            brief=trip.brief,
            date_from=trip.date_from,
            date_to=trip.date_to,
            travellers=max(trip.group_size, len(members)),
            budget_per_person_minor=trip.budget_per_person_minor,
            currency=trip.currency,
        )
        await self.events.add(
            trip_oid,
            EventKind.MESSAGE,
            EventActor.AGENT,
            f"Researching packages for {brief.travellers} people from {trip.origin} — trains, "
            "stays and something fun. This can take a few minutes.",
        )
        self.runner.spawn(self.research(trip_oid, previous, brief), name=f"research-{trip_id}")
        return Ok(TripStatusView(trip_id=trip_id, status=TripStatus.PROPOSING))

    async def research(
        self, trip_id: PydanticObjectId, previous: TripStatus, brief: TripBrief
    ) -> None:
        """The background half of `generate`. Never raises: a failure is reported in the feed
        and the trip returns to the status it had before."""
        try:
            plans = await self.researcher.research(brief)
            if not plans:
                raise ValueError("the researcher returned no packages")
        except asyncio.CancelledError:
            raise
        except Exception:
            # The boundary of a background job: nobody awaits it, so the failure must become
            # state (the feed + the previous status) rather than a lost exception.
            logger.exception("package research failed for trip %s", trip_id)
            await self.trips.transition_status(trip_id, TripStatus.PROPOSING, previous)
            await self.events.add(
                trip_id,
                EventKind.MESSAGE,
                EventActor.AGENT,
                "I could not put packages together this time. Try again in a moment.",
            )
            return
        await self._store(trip_id, brief, plans)

    async def _store(
        self, trip_id: PydanticObjectId, brief: TripBrief, plans: list[PackagePlan]
    ) -> None:
        proposals = [_proposal(trip_id, plan, brief.travellers) for plan in plans]

        async def write(session: AsyncClientSession) -> None:
            await self.votes.delete_for_trip(trip_id, session=session)
            await self.proposals.delete_for_trip(trip_id, session=session)
            await self.proposals.add_many(proposals, session=session)
            moved = await self.trips.transition_status(
                trip_id, TripStatus.PROPOSING, TripStatus.VOTING, session=session
            )
            if not moved:
                raise _StatusChanged
            cheapest = min(proposal.per_person_minor for proposal in proposals)
            await self.events.add(
                trip_id,
                EventKind.PROPOSALS_READY,
                EventActor.AGENT,
                f"{len(proposals)} packages are ready — from "
                f"{format_money(cheapest, brief.currency)} per person. Vote for your favourite!",
                payload={"proposal_ids": [to_text(identifier_of(p)) for p in proposals]},
                session=session,
            )

        try:
            await self.db.in_transaction(write)
        except _StatusChanged:
            logger.warning("trip %s left PROPOSING during research; packages dropped", trip_id)

    async def vote(
        self, trip_id: str, user_id: str, proposal_id: str
    ) -> Result[TripStatusView, TripError]:
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        if (error := require_status(access.value, TripStatus.VOTING)) is not None:
            return Err(error)
        trip, member = access.value.trip, access.value.member
        proposal = await self._proposal_of(trip, proposal_id)
        if proposal is None:
            return Err(TripError.PROPOSAL_NOT_FOUND)
        await self.votes.upsert(identifier_of(trip), member.user_id, identifier_of(proposal))
        await self.events.add(
            identifier_of(trip),
            EventKind.VOTE_CAST,
            EventActor.MEMBER,
            f"{member.display_name} voted for “{proposal.title}”.",
            payload={"proposal_id": to_text(identifier_of(proposal))},
            actor_user_id=member.user_id,
        )
        return Ok(TripStatusView(trip_id=trip_id, status=trip.status))

    async def close_voting(self, trip_id: str, user_id: str) -> Result[TripStatusView, TripError]:
        """Picks the winner, splits it into one share per CURRENT member and queues one booking
        per package item. All of it in one transaction: half a split is worse than none."""
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        error = require_organizer(access.value) or require_status(access.value, TripStatus.VOTING)
        if error is not None:
            return Err(error)
        trip = access.value.trip
        trip_oid = identifier_of(trip)
        proposals = await self.proposals.for_trip(trip_oid)
        if not proposals:
            return Err(TripError.NO_PROPOSALS)
        votes = await self.votes.for_trip(trip_oid)
        winner_id = pick_winner(
            [identifier_of(proposal) for proposal in proposals],
            [vote.proposal_id for vote in votes],
        )
        winner = next(proposal for proposal in proposals if identifier_of(proposal) == winner_id)
        members = await self.members.for_trip(trip_oid)
        shares = split_evenly(winner.total_minor, len(members))

        async def write(session: AsyncClientSession) -> None:
            moved = await self.trips.transition_status(
                trip_oid, TripStatus.VOTING, TripStatus.PAYING, session=session
            )
            if not moved:
                raise _StatusChanged
            await self.trips.update(
                trip,
                {
                    "status": TripStatus.PAYING,
                    "chosen_proposal_id": winner_id,
                    "total_minor": winner.total_minor,
                },
                session=session,
            )
            await self.contributions.add_many(
                [
                    Contribution(trip_id=trip_oid, user_id=member.user_id, amount_minor=share)
                    for member, share in zip(members, shares, strict=True)
                ],
                session=session,
            )
            for item in winner.items:
                await self.bookings.add(_booking(trip, item, len(members)), session=session)
            await self.events.add(
                trip_oid,
                EventKind.PROPOSAL_CHOSEN,
                EventActor.AGENT,
                f"The group picked “{winner.title}”.",
                payload={"proposal_id": to_text(winner_id)},
                session=session,
            )
            await self.events.add(
                trip_oid,
                EventKind.MESSAGE,
                EventActor.AGENT,
                f"Total {format_money(winner.total_minor, trip.currency)} split between "
                f"{len(members)} people: {format_money(max(shares), trip.currency)} per person. "
                "I will book as soon as everyone has paid their share.",
                session=session,
            )

        try:
            await self.db.in_transaction(write)
        except _StatusChanged:
            return Err(TripError.INVALID_STATE)
        return Ok(TripStatusView(trip_id=trip_id, status=TripStatus.PAYING))

    async def _proposal_of(self, trip: Trip, proposal_id: str) -> Proposal | None:
        proposal_oid = to_object_id(proposal_id)
        if proposal_oid is None:
            return None
        proposal = await self.proposals.get(proposal_oid)
        if proposal is None or proposal.trip_id != identifier_of(trip):
            return None
        return proposal


def _proposal(trip_id: PydanticObjectId, plan: PackagePlan, travellers: int) -> Proposal:
    return Proposal(
        trip_id=trip_id,
        title=plan.title,
        summary=plan.summary,
        items=[
            ProposalItem(
                kind=item.kind,
                title=item.title,
                supplier=item.supplier,
                supplier_url=item.supplier_url,
                price_minor=item.price_minor,
                details=item.details,
                starts_at=item.starts_at,
            )
            for item in plan.items
        ],
        total_minor=plan.total_minor,
        per_person_minor=per_person(plan.total_minor, travellers),
    )


def _booking(trip: Trip, item: ProposalItem, travellers: int) -> Booking:
    return Booking(
        trip_id=identifier_of(trip),
        kind=item.kind,
        title=item.title,
        supplier=item.supplier,
        supplier_url=item.supplier_url,
        amount_minor=item.price_minor,
        goal=booking_goal(
            kind=item.kind,
            title=item.title,
            details=item.details,
            travellers=travellers,
            date_from=trip.date_from,
            date_to=trip.date_to,
            starts_at=item.starts_at,
        ),
    )
