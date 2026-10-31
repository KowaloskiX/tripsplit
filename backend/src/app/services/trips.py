"""Trips: creation, invites, the room state and the group feed. No HTTP here."""

import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import EventActor, EventKind, MemberRole, TripStatus
from app.db.client import Database
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.trips import Trip, TripMember
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    ProposalRepository,
    TripRepository,
    VoteRepository,
)
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
    def __init__(self, db: Database) -> None:
        self.db = db
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.proposals = ProposalRepository()
        self.votes = VoteRepository()
        self.contributions = ContributionRepository()
        self.events = EventRepository()

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
                paid_count=sum(1 for view in contribution_views if view.outstanding_minor == 0),
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

        await self.db.in_transaction(write)
        return Ok(result)

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
