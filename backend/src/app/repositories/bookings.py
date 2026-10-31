"""Mongo queries for bookings and agent runs. No business rules."""

from typing import Any

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

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
