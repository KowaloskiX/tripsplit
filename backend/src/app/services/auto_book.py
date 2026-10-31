"""AUTO_BOOK: the moment the last share is paid, every purchase starts on its own.

Rule #1 still holds — the hook fires only after the trip moved to BOOKING / REBOOKING because
every share is covered — and so does the human in the loop: the organizer approves the basket
once (`approve-all`). The purchases run in the background, after the payment that triggered
them has been recorded, exactly as if the organizer had clicked "Book everything".
"""

import logging

from app.core.background import BackgroundRunner
from app.core.domain.result import Err
from app.core.domain.trips import EventActor, EventKind
from app.db.identifiers import identifier_of, to_text
from app.models.trips import Trip
from app.repositories.trips import EventRepository
from app.services.bookings import BookingService

logger = logging.getLogger(__name__)


class AutoBooker:
    def __init__(self, bookings: BookingService, runner: BackgroundRunner) -> None:
        self.bookings = bookings
        self.runner = runner
        self.events = EventRepository()

    async def __call__(self, trip: Trip) -> None:
        """The `ContributionService.on_fully_paid` hook: schedules "book everything"."""
        trip_id = to_text(identifier_of(trip))
        self.runner.spawn(self.book(trip), name=f"auto-book-{trip_id}")

    async def book(self, trip: Trip) -> None:
        trip_id = to_text(identifier_of(trip))
        await self.events.add(
            identifier_of(trip),
            EventKind.MESSAGE,
            EventActor.AGENT,
            "Everyone paid. Booking everything now. The organizer approves the basket once.",
            payload={"auto_book": True},
        )
        started = await self.bookings.start_all(trip_id, to_text(trip.organizer_id))
        if isinstance(started, Err):
            logger.warning("auto-book of trip %s refused: %s", trip_id, started.error)
