"""Trips: creation, invites, the room state and the group feed. No HTTP here."""

import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.bookings import format_money
from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import (
    BookingStatus,
    ContributionStatus,
    EventActor,
    EventKind,
    MemberRole,
    TripStatus,
    is_fully_paid,
)
from app.db.client import Database
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.bookings import Booking
from app.models.trips import Proposal, Trip, TripMember
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
from app.services.resplit import resplit_shares, status_once_paid
from app.services.trip_access import load_access
from app.services.trip_views import (
    EventView,
    RoomView,
    TripStatusView,
    TripSummaryView,
    contribution_view,
    event_view,
    member_view,
    proposal_view,
    trip_view,
)

# Joining after a package won would leave the newcomer without a share in the split.
JOINABLE_STATUSES = frozenset({TripStatus.COLLECTING, TripStatus.PROPOSING, TripStatus.VOTING})
# Leaving is possible until the agent starts buying: up to and including BOOKING (everyone has
# paid but nothing is bought yet), and only while every booking is still PENDING — no agent
# running, nothing awaiting approval or bought (checked separately, inside the transaction).
LEAVABLE_STATUSES = frozenset({*JOINABLE_STATUSES, TripStatus.PAYING, TripStatus.BOOKING})


class NotJoinableError(Exception):
    """Raised inside a join transaction to abort it when the trip left the joinable stages."""


class LeaveRefusedError(Exception):
    """Raised inside a leave transaction to abort it; carries the reason."""

    def __init__(self, error: TripError) -> None:
        super().__init__(error.value)
        self.error = error


@dataclass(frozen=True, slots=True)
class NewTrip:
    title: str
    origin: str
    brief: str
    date_from: date
    date_to: date
    group_size: int
    budget_per_person_minor: int | None
    display_name: str


def new_invite_code() -> str:
    return secrets.token_urlsafe(8)


class TripService:
    def __init__(self, db: Database, *, train_supplier_url: str | None = None) -> None:
        self.db = db
        # Demo seam, as in `ProposalService`: rebuilt train bookings keep pointing at it.
        self.train_supplier_url = train_supplier_url
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.proposals = ProposalRepository()
        self.votes = VoteRepository()
        self.contributions = ContributionRepository()
        self.events = EventRepository()
        self.bookings = BookingRepository()

    async def create(self, user_id: str, data: NewTrip) -> Result[TripStatusView, TripError]:
        organizer_id = to_object_id(user_id)
        if organizer_id is None:
            return Err(TripError.NOT_FOUND)
        invite_code = new_invite_code()

        async def write(session: AsyncClientSession) -> Trip:
            trip = await self.trips.add(
                Trip(
                    title=data.title,
                    origin=data.origin,
                    brief=data.brief,
                    date_from=data.date_from,
                    date_to=data.date_to,
                    group_size=data.group_size,
                    budget_per_person_minor=data.budget_per_person_minor,
                    organizer_id=organizer_id,
                    invite_code=invite_code,
                ),
                session=session,
            )
            await self.members.add(
                TripMember(
                    trip_id=identifier_of(trip),
                    user_id=organizer_id,
                    display_name=data.display_name,
                    role=MemberRole.ORGANIZER,
                ),
                session=session,
            )
            await self.events.add(
                identifier_of(trip),
                EventKind.TRIP_CREATED,
                EventActor.MEMBER,
                f"{data.display_name} created the trip “{data.title}”.",
                actor_user_id=organizer_id,
                session=session,
            )
            return trip

        trip = await self.db.in_transaction(write)
        return Ok(TripStatusView(trip_id=to_text(identifier_of(trip)), status=trip.status))

    async def list_mine(self, user_id: str) -> list[TripSummaryView]:
        user_oid = to_object_id(user_id)
        if user_oid is None:
            return []
        memberships = await self.members.for_user(user_oid)
        role_by_trip = {member.trip_id: member.role for member in memberships}
        trips = await self.trips.get_many(list(role_by_trip))
        return [
            TripSummaryView(trip=trip_view(trip), my_role=role_by_trip[identifier_of(trip)])
            for trip in trips
        ]

    async def room(self, trip_id: str, user_id: str) -> Result[RoomView, TripError]:
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        trip, me = access.value.trip, access.value.member
        trip_oid = identifier_of(trip)

        members = await self.members.for_trip(trip_oid)
        proposals = await self.proposals.for_trip(trip_oid)
        votes = await self.votes.for_trip(trip_oid)
        contributions = await self.contributions.for_trip(trip_oid)

        names = {member.user_id: member.display_name for member in members}
        tally = Counter(vote.proposal_id for vote in votes)
        my_vote = next((vote.proposal_id for vote in votes if vote.user_id == me.user_id), None)
        contribution_views = tuple(
            contribution_view(contribution, names.get(contribution.user_id, "Former member"))
            for contribution in contributions
        )
        my_contribution = next(
            (view for view in contribution_views if view.user_id == to_text(me.user_id)), None
        )

        return Ok(
            RoomView(
                trip=trip_view(trip),
                invite_code=trip.invite_code,
                my_user_id=to_text(me.user_id),
                my_role=me.role,
                members=tuple(member_view(member) for member in members),
                proposals=tuple(
                    proposal_view(
                        proposal,
                        votes=tally[identifier_of(proposal)],
                        voted_by_me=my_vote == identifier_of(proposal),
                        chosen=trip.chosen_proposal_id == identifier_of(proposal),
                    )
                    for proposal in proposals
                ),
                my_vote_proposal_id=to_text(my_vote) if my_vote is not None else None,
                contributions=contribution_views,
                my_contribution=my_contribution,
                # Current members only: a former member's settled share is not "paid by" anyone.
                paid_count=sum(
                    1
                    for view, contribution in zip(contribution_views, contributions, strict=True)
                    if view.outstanding_minor == 0 and contribution.user_id in names
                ),
            )
        )

    async def join(
        self, invite_code: str, user_id: str, display_name: str
    ) -> Result[TripStatusView, TripError]:
        user_oid = to_object_id(user_id)
        trip = await self.trips.get_by_invite_code(invite_code)
        if trip is None or user_oid is None:
            return Err(TripError.NOT_FOUND)
        trip_oid = identifier_of(trip)
        result = TripStatusView(trip_id=to_text(trip_oid), status=trip.status)
        if await self.members.get(trip_oid, user_oid) is not None:
            return Ok(result)  # idempotent: opening the invite link twice is not an error
        if trip.status not in JOINABLE_STATUSES:
            return Err(TripError.INVALID_STATE)

        async def write(session: AsyncClientSession) -> None:
            # Re-checked inside the transaction: closing the vote may have moved the trip since
            # the read above, and a member added after the split would get no share.
            if not await self.trips.touch_if_status(trip_oid, JOINABLE_STATUSES, session):
                raise NotJoinableError
            await self.members.add(
                TripMember(trip_id=trip_oid, user_id=user_oid, display_name=display_name),
                session=session,
            )
            await self.events.add(
                trip_oid,
                EventKind.MEMBER_JOINED,
                EventActor.MEMBER,
                f"{display_name} joined the trip.",
                actor_user_id=user_oid,
                session=session,
            )

        try:
            await self.db.in_transaction(write)
        except NotJoinableError:
            return Err(TripError.INVALID_STATE)
        return Ok(result)

    async def leave(self, trip_id: str, user_id: str) -> Result[TripStatusView, TripError]:
        """A member drops out before anything is bought.

        Their membership and vote go. Once shares exist, theirs drops to zero (REFUND_DUE when
        they had paid, otherwise it is deleted) and the same total is re-split among the rest;
        whoever now owes more sends the trip (back) to PAYING — from BOOKING too, when everyone
        had already paid; otherwise a BOOKING trip stays BOOKING. The PENDING bookings of the
        chosen package are rebuilt for the new party — the simplest way to keep each purchase
        under its supplier's passenger cap — with every item keeping its current amount.
        """
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        trip, member = access.value.trip, access.value.member
        if member.role is MemberRole.ORGANIZER:
            return Err(TripError.ORGANIZER_CANNOT_LEAVE)
        if trip.status not in LEAVABLE_STATUSES:
            return Err(TripError.INVALID_STATE)
        trip_oid = identifier_of(trip)
        chosen = (
            await self.proposals.get(trip.chosen_proposal_id)
            if trip.chosen_proposal_id is not None
            else None
        )

        async def write(session: AsyncClientSession) -> TripStatus:
            # Same guard as a join: a concurrent vote close or final payment also writes the
            # trip, so one of the two transactions retries against fresh data.
            if not await self.trips.touch_if_status(trip_oid, LEAVABLE_STATUSES, session):
                raise LeaveRefusedError(TripError.INVALID_STATE)
            fresh = await self.trips.get(trip_oid, session)
            if fresh is None:
                raise LeaveRefusedError(TripError.NOT_FOUND)
            bookings = await self.bookings.for_trip(trip_oid, session)
            if any(booking.status is not BookingStatus.PENDING for booking in bookings):
                raise LeaveRefusedError(TripError.BOOKING_STARTED)
            await self.members.delete(member, session)
            await self.votes.delete_for_member(trip_oid, member.user_id, session)
            refund = await self._settle_leaver_share(trip_oid, member.user_id, session)
            message = f"{member.display_name} left the trip."
            if refund:
                message += f" {format_money(refund, fresh.currency)} will be refunded to them."
            await self.events.add(
                trip_oid,
                EventKind.MEMBER_LEFT,
                EventActor.MEMBER,
                message,
                payload={"user_id": to_text(member.user_id), "refund_minor": refund},
                actor_user_id=member.user_id,
                session=session,
            )
            if refund is not None:
                plan = await resplit_shares(fresh, fresh.total_minor, session)
                if plan.owes and fresh.status is TripStatus.BOOKING:
                    await self.trips.set_status(fresh, TripStatus.PAYING, session)
                elif not plan.owes and plan.shares:
                    await self._start_booking_if_fully_paid(fresh, session)
            if bookings:
                await self._rebuild_bookings(fresh, bookings, chosen, member.user_id, session)
            return fresh.status

        try:
            status = await self.db.in_transaction(write)
        except LeaveRefusedError as refused:
            return Err(refused.error)
        return Ok(TripStatusView(trip_id=to_text(trip_oid), status=status))

    async def _settle_leaver_share(
        self, trip_id: PydanticObjectId, user_id: PydanticObjectId, session: AsyncClientSession
    ) -> int | None:
        """The leaver's share drops to zero. Returns what they get back (0 when they had paid
        nothing), or None when shares do not exist yet."""
        contribution = await self.contributions.get(trip_id, user_id, session)
        if contribution is None:
            return None
        if contribution.paid_minor == 0:
            await self.contributions.delete(contribution, session)
            return 0
        await self.contributions.update(
            contribution,
            {"amount_minor": 0, "status": ContributionStatus.REFUND_DUE},
            session,
        )
        return contribution.paid_minor

    async def _start_booking_if_fully_paid(self, trip: Trip, session: AsyncClientSession) -> None:
        """Nobody owes after the re-split (the leaver was the last one unpaid): the trip
        moves on exactly as after a final payment."""
        contributions = [
            contribution
            for contribution in await self.contributions.for_trip(identifier_of(trip), session)
            if contribution.amount_minor > 0
        ]
        fully_paid = is_fully_paid(
            [c.amount_minor for c in contributions], [c.paid_minor for c in contributions]
        )
        if trip.status is not TripStatus.PAYING or not fully_paid:
            return
        await self.trips.set_status(
            trip, await status_once_paid(identifier_of(trip), session), session
        )
        await self.events.add(
            identifier_of(trip),
            EventKind.ALL_PAID,
            EventActor.AGENT,
            "Everyone paid — the agent can book now.",
            payload={"total_minor": trip.total_minor},
            session=session,
        )

    async def _rebuild_bookings(
        self,
        trip: Trip,
        bookings: list[Booking],
        chosen: Proposal | None,
        leaver_id: PydanticObjectId,
        session: AsyncClientSession,
    ) -> None:
        """Recreates the (all PENDING) bookings for the remaining party, item by item.

        Each item keeps the sum of its parts' amounts — a re-quote already applied stays
        applied. A booking that cannot be traced to an item of the chosen package (created
        before bookings recorded their item) just drops the leaver from its passengers.
        """
        remaining = [
            member.user_id for member in await self.members.for_trip(identifier_of(trip), session)
        ]
        parts_by_item: dict[int, list[Booking]] = {}
        for booking in bookings:
            index = booking.proposal_item_index
            if chosen is not None and index is not None and 0 <= index < len(chosen.items):
                parts_by_item.setdefault(index, []).append(booking)
                continue
            passengers = [uid for uid in booking.passenger_user_ids if uid != leaver_id]
            await self.bookings.update(booking, {"passenger_user_ids": passengers}, session)
        if chosen is None:
            return
        for index, parts in parts_by_item.items():
            await self.bookings.delete_many(parts, session)
            for booking in bookings_for_item(
                trip,
                chosen.items[index],
                index,
                remaining,
                amount_minor=sum(part.amount_minor for part in parts),
                train_supplier_url=self.train_supplier_url,
            ):
                booking.train_query = parts[0].train_query
                await self.bookings.add(booking, session)

    async def feed(
        self, trip_id: str, user_id: str, after: datetime | None
    ) -> Result[list[EventView], TripError]:
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        trip_oid = identifier_of(access.value.trip)
        names = await self._names(trip_oid)
        events = await self.events.feed(trip_oid, after=after)
        return Ok([event_view(event, names) for event in events])

    async def post_message(
        self, trip_id: str, user_id: str, text: str
    ) -> Result[EventView, TripError]:
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        member = access.value.member
        event = await self.events.add(
            member.trip_id,
            EventKind.MESSAGE,
            EventActor.MEMBER,
            text,
            actor_user_id=member.user_id,
        )
        return Ok(event_view(event, {member.user_id: member.display_name}))

    async def _names(self, trip_id: PydanticObjectId) -> dict[PydanticObjectId, str]:
        members = await self.members.for_trip(trip_id)
        return {member.user_id: member.display_name for member in members}
