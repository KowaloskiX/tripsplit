"""Shares and payments. Rule #1 of the product lives here: the trip moves to BOOKING (or back
to REBOOKING after top-ups for a disruption) only when every share is covered — not in the UI,
and not in the booking agent.
"""

from dataclasses import dataclass

from app.core.domain.errors import TripError
from app.core.domain.packages import format_money
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import EventActor, EventKind, TripStatus, is_fully_paid
from app.db.identifiers import identifier_of, to_text
from app.models.trips import Trip, TripMember
from app.payments.ports import PaymentProvider
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    TripRepository,
)
from app.services.resplit import status_once_paid
from app.services.trip_access import load_access


@dataclass(frozen=True, slots=True)
class PaymentView:
    trip_id: str
    status: TripStatus
    paid_minor: int
    all_paid: bool


class ContributionService:
    def __init__(self, payments: PaymentProvider) -> None:
        self.payments = payments
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.contributions = ContributionRepository()
        self.events = EventRepository()

    async def pay(self, trip_id: str, user_id: str) -> Result[PaymentView, TripError]:
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        return await self.pay_for(access.value.trip, access.value.member)

    async def pay_for(self, trip: Trip, member: TripMember) -> Result[PaymentView, TripError]:
        """Charges `member`'s outstanding share. Callers have already checked membership."""
        if trip.status is not TripStatus.PAYING:
            return Err(TripError.INVALID_STATE)
        trip_oid = identifier_of(trip)
        contribution = await self.contributions.get(trip_oid, member.user_id)
        if contribution is None:
            # Joined after the split — there is no share to pay.
            return Err(TripError.INVALID_STATE)
        outstanding = contribution.amount_minor - contribution.paid_minor
        if outstanding <= 0:
            return Err(TripError.ALREADY_PAID)

        # Outside any transaction on purpose: a charge is not replayable.
        receipt = await self.payments.charge(
            to_text(trip_oid), to_text(member.user_id), outstanding, trip.currency
        )
        await self.contributions.mark_paid(
            contribution, contribution.paid_minor + receipt.paid_minor, receipt.provider_ref
        )
        await self.events.add(
            trip_oid,
            EventKind.CONTRIBUTION_PAID,
            EventActor.MEMBER,
            f"{member.display_name} paid their share "
            f"({format_money(receipt.paid_minor, trip.currency)}).",
            payload={"amount_minor": receipt.paid_minor},
            actor_user_id=member.user_id,
        )
        resumed = await self._start_booking_if_fully_paid(trip)
        all_paid = resumed is not None
        return Ok(
            PaymentView(
                trip_id=to_text(trip_oid),
                status=resumed or TripStatus.PAYING,
                paid_minor=receipt.paid_minor,
                all_paid=all_paid,
            )
        )

    async def _start_booking_if_fully_paid(self, trip: Trip) -> TripStatus | None:
        """The status the trip moved to once every share is covered; None while somebody owes."""
        trip_oid = identifier_of(trip)
        contributions = await self.contributions.for_trip(trip_oid)
        fully_paid = bool(contributions) and is_fully_paid(
            [c.amount_minor for c in contributions], [c.paid_minor for c in contributions]
        )
        if not fully_paid:
            return None
        target = await status_once_paid(trip_oid)
        # Compare-and-set: of two simultaneous final payments, exactly one announces it.
        if await self.trips.transition_status(trip_oid, TripStatus.PAYING, target):
            await self.events.add(
                trip_oid,
                EventKind.ALL_PAID,
                EventActor.AGENT,
                "Everyone paid — the agent can book now.",
                payload={"total_minor": sum(c.paid_minor for c in contributions)},
            )
        return target
