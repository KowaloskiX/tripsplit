"""Packages: research in the background, voting, and closing the vote into shares + bookings.

No HTTP here. Research runs on the application's `BackgroundRunner`, so the request that
started it returns immediately while the agent works.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.ai.research import (
    PackagePlan,
    PackageResearcher,
    SearchOutcome,
    SupplierProgress,
    TripBrief,
    research_progress,
)
from app.core.background import BackgroundRunner
from app.core.domain.errors import TripError
from app.core.domain.packages import format_money, is_over_budget, per_person, pick_winner
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import SupplierCapabilities
from app.core.domain.trips import EventActor, EventKind, TripStatus, split_evenly
from app.db.client import Database
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.trips import Contribution, Proposal, ProposalItem, TransportSegment, Trip
from app.repositories.bookings import BookingRepository
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    ProposalRepository,
    TripRepository,
    VoteRepository,
)
from app.services.booking_plans import bookings_for_item
from app.services.supplier_prices import SupplierPrices
from app.services.trip_access import TripAccess, load_access, require_organizer, require_status
from app.services.trip_views import TripStatusView
from app.suppliers.registry import SupplierRegistry

logger = logging.getLogger(__name__)

# Statuses from which a (re-)research may start: before the first vote and during voting.
RESEARCHABLE_STATUSES = (TripStatus.COLLECTING, TripStatus.VOTING)


class _StatusChanged(Exception):
    """Raised inside a transaction to abort it when another request moved the trip first."""


class ProposalService:
    def __init__(
        self,
        db: Database,
        researcher: PackageResearcher,
        runner: BackgroundRunner,
        *,
        suppliers: SupplierRegistry | None = None,
        prices: SupplierPrices | None = None,
        progress_events: bool = False,
    ) -> None:
        self.db = db
        # A feed message per finished supplier search while researching.
        self.progress_events = progress_events
        # The supplier plugins: their capabilities split each item into purchases.
        self.suppliers = suppliers if suppliers is not None else SupplierRegistry()
        # Places the holds when the vote closes (suppliers that support them).
        self.prices = prices if prices is not None else SupplierPrices(db, self.suppliers)
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
            destination=trip.destination,
            transport_mode=trip.transport_mode,
        )
        await self.events.add(
            trip_oid,
            EventKind.MESSAGE,
            EventActor.AGENT,
            f"Researching packages for {brief.travellers} people from {trip.origin} — getting "
            "there, a place to stay and something fun. This can take a few minutes.",
        )
        self.runner.spawn(self.research(trip_oid, previous, brief), name=f"research-{trip_id}")
        return Ok(TripStatusView(trip_id=trip_id, status=TripStatus.PROPOSING))

    async def research(
        self, trip_id: PydanticObjectId, previous: TripStatus, brief: TripBrief
    ) -> None:
        """The background half of `generate`. Never raises: a failure is reported in the feed
        and the trip returns to the status it had before."""
        if self.progress_events:
            research_progress.set(self._progress_sink(trip_id))
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

    def _progress_sink(
        self, trip_id: PydanticObjectId
    ) -> Callable[[SupplierProgress], Awaitable[None]]:
        async def report(progress: SupplierProgress) -> None:
            await self.events.add(
                trip_id,
                EventKind.MESSAGE,
                EventActor.AGENT,
                progress_message(progress),
                payload={
                    "supplier_progress": {
                        "supplier_id": progress.supplier_id,
                        "supplier": progress.supplier,
                        "kind": progress.kind.value,
                        "outcome": progress.outcome.value,
                        "offers": progress.offers,
                        "seconds": progress.seconds,
                    }
                },
            )

        return report

    async def _store(
        self, trip_id: PydanticObjectId, brief: TripBrief, plans: list[PackagePlan]
    ) -> None:
        proposals = [_proposal(trip_id, plan, brief) for plan in plans]

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
            message = (
                f"{len(proposals)} packages are ready — from "
                f"{format_money(cheapest, brief.currency)} per person. Vote for your favourite!"
            )
            budget = brief.budget_per_person_minor
            if budget is not None and all(proposal.over_budget for proposal in proposals):
                message += (
                    f" Heads-up: none fits the budget of {format_money(budget, brief.currency)} "
                    "per person — these are the cheapest options I found."
                )
            await self.events.add(
                trip_id,
                EventKind.PROPOSALS_READY,
                EventActor.AGENT,
                message,
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
        """Picks the winner, splits it into one share per CURRENT member and queues the bookings
        of every package item (several where the supplier caps one purchase — see
        `bookings_for_item`). All of it in one transaction: half a split is worse than none.
        Then, outside it, every supplier that supports holds is asked to hold the price while
        the group pays."""
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

        async def write(session: AsyncClientSession) -> None:
            moved = await self.trips.transition_status(
                trip_oid, TripStatus.VOTING, TripStatus.PAYING, session=session
            )
            if not moved:
                raise _StatusChanged
            # Counted inside the transaction, after the status write: a concurrent join writes
            # the trip document too (see TripService.join), so either it committed first and is
            # counted here, or it conflicts, retries and is turned away.
            members = await self.members.for_trip(trip_oid, session=session)
            shares = split_evenly(winner.total_minor, len(members))
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
            passengers = [member.user_id for member in members]
            for index, item in enumerate(winner.items):
                for booking in bookings_for_item(
                    trip, item, index, passengers, self._capabilities(item)
                ):
                    await self.bookings.add(booking, session=session)
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
            if winner.over_budget and trip.budget_per_person_minor is not None:
                await self.events.add(
                    trip_oid,
                    EventKind.MESSAGE,
                    EventActor.AGENT,
                    f"Heads-up: “{winner.title}” is over your budget — "
                    f"{format_money(winner.per_person_minor, trip.currency)} per person against "
                    f"{format_money(trip.budget_per_person_minor, trip.currency)} planned.",
                    payload={
                        "over_budget": True,
                        "proposal_id": to_text(winner_id),
                        "per_person_minor": winner.per_person_minor,
                        "budget_per_person_minor": trip.budget_per_person_minor,
                    },
                    session=session,
                )

        try:
            await self.db.in_transaction(write)
        except _StatusChanged:
            return Err(TripError.INVALID_STATE)
        fresh = await self.trips.get(trip_oid)
        if fresh is not None:
            await self.prices.place_holds(fresh)
        return Ok(TripStatusView(trip_id=trip_id, status=TripStatus.PAYING))

    def _capabilities(self, item: ProposalItem) -> SupplierCapabilities | None:
        adapter = self.suppliers.get(item.supplier_id) if item.supplier_id else None
        return adapter.capabilities if adapter is not None else None

    async def _proposal_of(self, trip: Trip, proposal_id: str) -> Proposal | None:
        proposal_oid = to_object_id(proposal_id)
        if proposal_oid is None:
            return None
        proposal = await self.proposals.get(proposal_oid)
        if proposal is None or proposal.trip_id != identifier_of(trip):
            return None
        return proposal


def _proposal(trip_id: PydanticObjectId, plan: PackagePlan, brief: TripBrief) -> Proposal:
    share = per_person(plan.total_minor, brief.travellers)
    return Proposal(
        trip_id=trip_id,
        title=plan.title,
        summary=plan.summary,
        items=[
            ProposalItem(
                kind=item.kind,
                mode=item.mode,
                title=item.title,
                supplier=item.supplier,
                supplier_url=item.supplier_url,
                price_minor=item.price_minor,
                details=item.details,
                starts_at=item.starts_at,
                supplier_id=item.supplier_id,
                offer_ref=item.offer_ref,
                segments=[
                    TransportSegment(
                        carrier=segment.carrier,
                        number=segment.number,
                        origin=segment.origin,
                        destination=segment.destination,
                        departs_at=segment.departs_at,
                        arrives_at=segment.arrives_at,
                    )
                    for segment in item.segments
                ],
                refundable=item.refundable,
                supplier_data=dict(item.supplier_data),
            )
            for item in plan.items
        ],
        total_minor=plan.total_minor,
        per_person_minor=share,
        over_budget=is_over_budget(share, brief.budget_per_person_minor),
    )


def progress_message(progress: SupplierProgress) -> str:
    """ "PKP Intercity ✓ 2 offers · 2.9 s", "Duffel ✗ too slow (15.0 s)"."""
    name = progress.supplier
    match progress.outcome:
        case SearchOutcome.OK | SearchOutcome.CACHED:
            noun = "offer" if progress.offers == 1 else "offers"
            took = (
                "cached"
                if progress.outcome is SearchOutcome.CACHED
                else f"{progress.seconds:.1f} s"
            )
            return f"{name} ✓ {progress.offers} {noun} · {took}"
        case SearchOutcome.EMPTY:
            return f"{name} · nothing for these dates · {progress.seconds:.1f} s"
        case SearchOutcome.TIMEOUT:
            return f"{name} ✗ too slow ({progress.seconds:.1f} s) — going on without it"
        case SearchOutcome.FAILED:
            return f"{name} ✗ unavailable right now"
