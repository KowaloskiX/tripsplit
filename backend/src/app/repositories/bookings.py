"""Mongo queries for bookings and agent runs. No business rules."""

from collections.abc import Iterable
from typing import Any

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.trips import BookingStatus
from app.db.documents import utc_now
from app.models.bookings import AgentRun, Booking
from app.repositories.base import bounded_to_list


class BookingRepository:
    async def add(self, booking: Booking, session: AsyncClientSession | None = None) -> Booking:
        return await booking.insert(session=session)

    async def get(
        self, booking_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> Booking | None:
        return await Booking.get(booking_id, session=session)

    async def for_trip(
        self, trip_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> list[Booking]:
        query = Booking.find(Booking.trip_id == trip_id, session=session).sort("_id")
        return await bounded_to_list(query, what="trip bookings")

    async def update(
        self, booking: Booking, changes: dict[str, Any], session: AsyncClientSession | None = None
    ) -> Booking:
        await booking.set({**changes, "updated_at": utc_now()}, session=session)
        return booking

    async def update_if(
        self,
        booking: Booking,
        expected: dict[str, Any],
        changes: dict[str, Any],
        session: AsyncClientSession | None = None,
    ) -> bool:
        """Compare-and-set: writes `changes` only while the stored fields still equal
        `expected` (e.g. the status). `True` for the ONE caller that wrote; the in-memory
        document is updated only then."""
        values = {**changes, "updated_at": utc_now()}
        result = await Booking.get_pymongo_collection().update_one(
            {"_id": booking.id, **expected}, {"$set": values}, session=session
        )
        if result.modified_count != 1:
            return False
        for field, value in values.items():
            setattr(booking, field, value)
        return True

    async def update_if_status(
        self,
        booking: Booking,
        statuses: Iterable[BookingStatus],
        changes: dict[str, Any],
        session: AsyncClientSession | None = None,
    ) -> bool:
        return await self.update_if(
            booking, {"status": {"$in": list(statuses)}}, changes, session=session
        )

    async def delete_many(
        self, bookings: list[Booking], session: AsyncClientSession | None = None
    ) -> None:
        for booking in bookings:
            await booking.delete(session=session)


class AgentRunRepository:
    async def add(self, run: AgentRun, session: AsyncClientSession | None = None) -> AgentRun:
        return await run.insert(session=session)

    async def get_by_run_id(
        self, run_id: str, session: AsyncClientSession | None = None
    ) -> AgentRun | None:
        return await AgentRun.find_one(AgentRun.run_id == run_id, session=session)

    async def for_booking(
        self, booking_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> list[AgentRun]:
        query = AgentRun.find(AgentRun.booking_id == booking_id, session=session).sort("_id")
        return await bounded_to_list(query, what="booking runs")

    async def update(
        self, run: AgentRun, changes: dict[str, Any], session: AsyncClientSession | None = None
    ) -> AgentRun:
        await run.set({**changes, "updated_at": utc_now()}, session=session)
        return run
