"""The ONE re-split of a trip's shares, used wherever the amount the group pays changes:
a disruption rebooking, a supplier re-quote before a purchase, and a member leaving.

It splits a new total evenly over the CURRENT members' contributions (a former member's
contribution is left alone — it is settled separately), writes every share and its status
(PAID / PENDING / REFUND_DUE), the trip total, and — unless the caller announces it in its own
words — a RESPLIT event. Moving the trip between statuses stays with the caller: each flow
has its own next step.
"""

from dataclasses import dataclass
from typing import Any

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.bookings import (
    ShareChange,
    format_delta,
    format_money,
    refund_minor,
    resplit,
    resume_status,
)
from app.core.domain.trips import ContributionStatus, EventActor, EventKind, TripStatus
from app.db.identifiers import identifier_of, to_text
from app.models.trips import Trip
from app.repositories.bookings import BookingRepository
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    TripRepository,
)


@dataclass(frozen=True, slots=True)
class MemberShare:
    user_id: PydanticObjectId
    display_name: str
    change: ShareChange


@dataclass(frozen=True, slots=True)
class Resplit:
    previous_total_minor: int
    total_minor: int
    shares: list[MemberShare]

    @property
    def owes(self) -> bool:
        """Somebody has to top up before anything more is bought."""
        return any(share.change.status is ContributionStatus.PENDING for share in self.shares)

    @property
    def refunds(self) -> bool:
        return any(share.change.status is ContributionStatus.REFUND_DUE for share in self.shares)


async def resplit_shares(
    trip: Trip,
    total_minor: int,
    session: AsyncClientSession,
    *,
    announce: bool = True,
) -> Resplit:
    """Re-splits `total_minor` over the trip's current members, inside the caller's
    transaction. Without contributions (before the vote closed) only the total is written."""
    trip_oid = identifier_of(trip)
    members = await MemberRepository().for_trip(trip_oid, session=session)
    names = {member.user_id: member.display_name for member in members}
    contributions_repo = ContributionRepository()
    contributions = [
        contribution
        for contribution in await contributions_repo.for_trip(trip_oid, session=session)
        if contribution.user_id in names
    ]
    changes = (
        resplit(
            total_minor,
            [contribution.amount_minor for contribution in contributions],
            [contribution.paid_minor for contribution in contributions],
        )
        if contributions
        else []
    )
    shares = [
        MemberShare(
            user_id=contribution.user_id,
            display_name=names[contribution.user_id],
            change=change,
        )
        for contribution, change in zip(contributions, changes, strict=True)
    ]
    plan = Resplit(previous_total_minor=trip.total_minor, total_minor=total_minor, shares=shares)

    for contribution, change in zip(contributions, changes, strict=True):
        await contributions_repo.update(
            contribution,
            {"amount_minor": change.share_minor, "status": change.status},
            session,
        )
    await TripRepository().update(trip, {"total_minor": total_minor}, session)
    if announce and shares:
        await EventRepository().add(
            trip_oid,
            EventKind.RESPLIT,
            EventActor.AGENT,
            resplit_message(plan, trip.currency),
            payload=resplit_payload(plan),
            session=session,
        )
    return plan


async def status_once_paid(
    trip_id: PydanticObjectId, session: AsyncClientSession | None = None
) -> TripStatus:
    """Where a PAYING trip goes when the last share is covered: back to REBOOKING when the
    top-ups paid for a replacement of a disrupted booking, otherwise BOOKING."""
    bookings = await BookingRepository().for_trip(trip_id, session)
    return resume_status(
        [booking.status for booking in bookings if booking.replaces_booking_id is not None]
    )


def resplit_message(plan: Resplit, currency: str) -> str:
    first = plan.shares[0].change
    message = (
        f"New share: {format_money(first.share_minor, currency)} each "
        f"({format_delta(first.delta_minor, currency)})."
    )
    if plan.owes:
        message += " Please top up the difference. I will buy once everyone has paid."
    elif plan.refunds:
        message += " The difference will be refunded."
    return message


def resplit_payload(plan: Resplit) -> dict[str, Any]:
    return {
        "total_minor": plan.total_minor,
        "previous_total_minor": plan.previous_total_minor,
        "members": [
            {
                "user_id": to_text(share.user_id),
                "display_name": share.display_name,
                "previous_minor": share.change.previous_minor,
                "share_minor": share.change.share_minor,
                "delta_minor": share.change.delta_minor,
                "paid_minor": share.change.paid_minor,
                "refund_minor": refund_minor(share.change.share_minor, share.change.paid_minor),
                "status": share.change.status.value,
            }
            for share in plan.shares
        ],
    }
