"""Mongo queries for trips, members, proposals, votes, contributions and the feed.

No business rules here. Every method takes an optional `session` so a service can put it
inside a transaction. Every filter is backed by an index declared on the document.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.trips import ContributionStatus, EventActor, EventKind, TripStatus
from app.db.documents import utc_now
from app.models.trips import Contribution, Proposal, Trip, TripEvent, TripMember, Vote
from app.repositories.base import bounded_to_list

# A feed page. The UI polls with `after`, so a page only has to cover a few seconds.
FEED_PAGE_SIZE = 200


class TripRepository:
    async def add(self, trip: Trip, session: AsyncClientSession | None = None) -> Trip:
        return await trip.insert(session=session)

    async def get(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> Trip | None:
        return await Trip.get(trip_id, session=session)

    async def get_by_invite_code(
        self, code: str, session: AsyncClientSession | None = None
    ) -> Trip | None:
        return await Trip.find_one(Trip.invite_code == code, session=session)

    async def get_many(
        self, trip_ids: list[PydanticObjectId], session: AsyncClientSession | None = None
    ) -> list[Trip]:
        query = Trip.find({"_id": {"$in": trip_ids}}, session=session).sort("-_id")
        return await bounded_to_list(query, what="trips by id")

    async def update(
        self, trip: Trip, changes: dict[str, Any], session: AsyncClientSession | None = None
    ) -> Trip:
        await trip.set({**changes, "updated_at": utc_now()}, session=session)
        return trip

    async def set_status(
        self, trip: Trip, status: TripStatus, session: AsyncClientSession | None = None
    ) -> Trip:
        return await self.update(trip, {"status": status}, session=session)

    async def transition_status(
        self,
        trip_id: PydanticObjectId,
        expected: TripStatus,
        target: TripStatus,
        session: AsyncClientSession | None = None,
    ) -> bool:
        """Compare-and-set on the status: `True` only for the ONE caller that moved it.

        Two members paying the last shares at the same moment must not both announce
        "everyone paid" — the filter on the expected status makes the transition happen once.
        """
        result = await Trip.get_pymongo_collection().update_one(
            {"_id": trip_id, "status": expected},
            {"$set": {"status": target, "updated_at": utc_now()}},
            session=session,
        )
        return result.modified_count == 1

    async def touch_if_status(
        self,
        trip_id: PydanticObjectId,
        statuses: Iterable[TripStatus],
        session: AsyncClientSession,
    ) -> bool:
        """Inside a transaction: assert the status AND write the trip document.

        The write is the point. A concurrent transaction that also writes the trip (e.g. closing
        the vote) now conflicts with this one, so one of them retries against fresh data
        instead of both committing on a stale read.
        """
        result = await Trip.get_pymongo_collection().update_one(
            {"_id": trip_id, "status": {"$in": list(statuses)}},
            {"$set": {"updated_at": utc_now()}},
            session=session,
        )
        return result.matched_count == 1


class MemberRepository:
    async def add(
        self, member: TripMember, session: AsyncClientSession | None = None
    ) -> TripMember:
        return await member.insert(session=session)

    async def get(
        self,
        trip_id: PydanticObjectId,
        user_id: PydanticObjectId,
        session: AsyncClientSession | None = None,
    ) -> TripMember | None:
        return await TripMember.find_one(
            TripMember.trip_id == trip_id, TripMember.user_id == user_id, session=session
        )

    async def for_trip(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> list[TripMember]:
        query = TripMember.find(TripMember.trip_id == trip_id, session=session).sort("_id")
        return await bounded_to_list(query, what="trip members")

    async def for_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> list[TripMember]:
        query = TripMember.find(TripMember.user_id == user_id, session=session)
        return await bounded_to_list(query, what="trips of a user")

    async def delete(self, member: TripMember, session: AsyncClientSession | None = None) -> None:
        await member.delete(session=session)

    async def delete_for_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await TripMember.find(TripMember.user_id == user_id, session=session).delete(
            session=session
        )


class ProposalRepository:
    async def add_many(
        self, proposals: list[Proposal], session: AsyncClientSession | None = None
    ) -> list[Proposal]:
        for proposal in proposals:
            await proposal.insert(session=session)
        return proposals

    async def get(
        self, proposal_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> Proposal | None:
        return await Proposal.get(proposal_id, session=session)

    async def for_trip(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> list[Proposal]:
        query = Proposal.find(Proposal.trip_id == trip_id, session=session).sort("_id")
        return await bounded_to_list(query, what="trip proposals")

    async def delete_for_trip(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await Proposal.find(Proposal.trip_id == trip_id, session=session).delete(session=session)


class VoteRepository:
    async def upsert(
        self,
        trip_id: PydanticObjectId,
        user_id: PydanticObjectId,
        proposal_id: PydanticObjectId,
        session: AsyncClientSession | None = None,
    ) -> None:
        """One vote per member per trip — casting again changes it."""
        now = utc_now()
        await Vote.get_pymongo_collection().update_one(
            {"trip_id": trip_id, "user_id": user_id},
            {
                "$set": {"proposal_id": proposal_id, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
            session=session,
        )

    async def for_trip(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> list[Vote]:
        query = Vote.find(Vote.trip_id == trip_id, session=session)
        return await bounded_to_list(query, what="trip votes")

    async def delete_for_trip(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await Vote.find(Vote.trip_id == trip_id, session=session).delete(session=session)

    async def delete_for_member(
        self,
        trip_id: PydanticObjectId,
        user_id: PydanticObjectId,
        session: AsyncClientSession | None = None,
    ) -> None:
        await Vote.find(Vote.trip_id == trip_id, Vote.user_id == user_id, session=session).delete(
            session=session
        )

    async def delete_for_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await Vote.find(Vote.user_id == user_id, session=session).delete(session=session)


class ContributionRepository:
    async def add_many(
        self, contributions: list[Contribution], session: AsyncClientSession | None = None
    ) -> list[Contribution]:
        for contribution in contributions:
            await contribution.insert(session=session)
        return contributions

    async def get(
        self,
        trip_id: PydanticObjectId,
        user_id: PydanticObjectId,
        session: AsyncClientSession | None = None,
    ) -> Contribution | None:
        return await Contribution.find_one(
            Contribution.trip_id == trip_id, Contribution.user_id == user_id, session=session
        )

    async def for_trip(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> list[Contribution]:
        query = Contribution.find(Contribution.trip_id == trip_id, session=session).sort("_id")
        return await bounded_to_list(query, what="trip contributions")

    async def update(
        self,
        contribution: Contribution,
        changes: dict[str, Any],
        session: AsyncClientSession | None = None,
    ) -> Contribution:
        await contribution.set({**changes, "updated_at": utc_now()}, session=session)
        return contribution

    async def mark_paid(
        self,
        contribution: Contribution,
        paid_minor: int,
        provider_ref: str,
        session: AsyncClientSession | None = None,
    ) -> Contribution:
        status = (
            ContributionStatus.PAID
            if paid_minor >= contribution.amount_minor
            else ContributionStatus.PENDING
        )
        return await self.update(
            contribution,
            {
                "paid_minor": paid_minor,
                "status": status,
                "provider_ref": provider_ref,
                "paid_at": utc_now(),
            },
            session=session,
        )

    async def delete(
        self, contribution: Contribution, session: AsyncClientSession | None = None
    ) -> None:
        await contribution.delete(session=session)

    async def delete_for_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await Contribution.find(Contribution.user_id == user_id, session=session).delete(
            session=session
        )


class EventRepository:
    async def add(
        self,
        trip_id: PydanticObjectId,
        kind: EventKind,
        actor: EventActor,
        message: str,
        payload: dict[str, Any] | None = None,
        actor_user_id: PydanticObjectId | None = None,
        session: AsyncClientSession | None = None,
    ) -> TripEvent:
        event = TripEvent(
            trip_id=trip_id,
            kind=kind,
            actor=actor,
            message=message,
            payload=payload or {},
            actor_user_id=actor_user_id,
            created_at=utc_now(),
        )
        return await event.insert(session=session)

    async def feed(
        self,
        trip_id: PydanticObjectId,
        after: datetime | None = None,
        session: AsyncClientSession | None = None,
    ) -> list[TripEvent]:
        """Events in chronological order, optionally only those newer than `after`."""
        query: dict[str, Any] = {"trip_id": trip_id}
        if after is not None:
            query["created_at"] = {"$gt": after}
        cursor = TripEvent.find(query, session=session).sort("created_at").limit(FEED_PAGE_SIZE)
        return await bounded_to_list(cursor, what="trip feed", limit=FEED_PAGE_SIZE)
