"""Mongo queries for the attraction candidates (with their votes) and the day plan."""

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import DuplicateKeyError

from app.db.documents import utc_now
from app.models.itinerary import AttractionCandidate, Itinerary, ItineraryDay, TripAttractions


class AttractionRepository:
    async def get(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> TripAttractions | None:
        return await TripAttractions.find_one(TripAttractions.trip_id == trip_id, session=session)

    async def snapshot(
        self,
        trip_id: PydanticObjectId,
        destination: str,
        candidates: list[AttractionCandidate],
    ) -> TripAttractions:
        """Stores the first snapshot; a concurrent first request keeps the winner's."""
        try:
            return await TripAttractions(
                trip_id=trip_id, destination=destination, candidates=candidates
            ).insert()
        except DuplicateKeyError:
            existing = await self.get(trip_id)
            if existing is None:  # deleted in between: nothing sensible to return but ours
                raise
            return existing

    async def toggle_vote(
        self, trip_id: PydanticObjectId, attraction_id: str, user_id: PydanticObjectId
    ) -> bool | None:
        """Adds the member's vote, or removes it when present. True = now voted, False = vote
        withdrawn, None = no such candidate. Each half is one atomic update."""
        collection = TripAttractions.get_pymongo_collection()
        withdrawn = await collection.update_one(
            {
                "trip_id": trip_id,
                "candidates": {
                    "$elemMatch": {"attraction_id": attraction_id, "voter_ids": user_id}
                },
            },
            {
                "$pull": {"candidates.$.voter_ids": user_id},
                "$set": {"updated_at": utc_now()},
            },
        )
        if withdrawn.modified_count == 1:
            return False
        added = await collection.update_one(
            {"trip_id": trip_id, "candidates.attraction_id": attraction_id},
            {
                "$addToSet": {"candidates.$.voter_ids": user_id},
                "$set": {"updated_at": utc_now()},
            },
        )
        return True if added.matched_count == 1 else None

    async def withdraw_member(
        self,
        trip_id: PydanticObjectId,
        user_id: PydanticObjectId,
        session: AsyncClientSession | None = None,
    ) -> None:
        await TripAttractions.get_pymongo_collection().update_one(
            {"trip_id": trip_id},
            {"$pull": {"candidates.$[].voter_ids": user_id}},
            session=session,
        )

    async def delete_votes_of_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await TripAttractions.get_pymongo_collection().update_many(
            {"candidates.voter_ids": user_id},
            {"$pull": {"candidates.$[].voter_ids": user_id}},
            session=session,
        )


class ItineraryRepository:
    async def get(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> Itinerary | None:
        return await Itinerary.find_one(Itinerary.trip_id == trip_id, session=session)

    async def replace(
        self,
        trip_id: PydanticObjectId,
        days: list[ItineraryDay],
        votes_signature: str,
        session: AsyncClientSession | None = None,
    ) -> Itinerary:
        """One plan per trip: the new one overwrites the old (the organizer's button)."""
        now = utc_now()
        existing = await self.get(trip_id, session)
        if existing is None:
            return await Itinerary(
                trip_id=trip_id, days=days, votes_signature=votes_signature, generated_at=now
            ).insert(session=session)
        existing.days = days
        existing.votes_signature = votes_signature
        existing.generated_at = now
        existing.updated_at = now
        await existing.save(session=session)
        return existing
