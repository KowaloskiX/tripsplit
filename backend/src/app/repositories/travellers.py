"""Mongo queries for traveller profiles. No business rules."""

from collections.abc import Sequence
from typing import Any

from beanie import PydanticObjectId
from beanie.operators import In
from pymongo.asynchronous.client_session import AsyncClientSession

from app.db.documents import utc_now
from app.models.travellers import TravellerProfile
from app.repositories.base import bounded_to_list


class TravellerProfileRepository:
    async def get(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> TravellerProfile | None:
        return await TravellerProfile.find_one(TravellerProfile.user_id == user_id, session=session)

    async def for_users(
        self, user_ids: Sequence[PydanticObjectId], session: AsyncClientSession | None = None
    ) -> dict[PydanticObjectId, TravellerProfile]:
        if not user_ids:
            return {}
        query = TravellerProfile.find(In(TravellerProfile.user_id, list(user_ids)), session=session)
        profiles = await bounded_to_list(query, what="traveller profiles")
        return {profile.user_id: profile for profile in profiles}

    async def upsert(
        self,
        user_id: PydanticObjectId,
        changes: dict[str, Any],
        session: AsyncClientSession | None = None,
    ) -> TravellerProfile:
        """Writes the given fields of the user's profile, creating it on first use (the unique
        index on `user_id` turns a concurrent first write into a retryable conflict)."""
        profile = await self.get(user_id, session)
        if profile is None:
            return await TravellerProfile(user_id=user_id, **changes).insert(session=session)
        await profile.set({**changes, "updated_at": utc_now()}, session=session)
        return profile

    async def delete_for_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await TravellerProfile.find(TravellerProfile.user_id == user_id, session=session).delete(
            session=session
        )
