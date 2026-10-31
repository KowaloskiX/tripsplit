"""Turning one item of the chosen package into the booking(s) the agent will buy.

A supplier that caps the passengers of one online purchase (PKP Intercity: 5) gets several
bookings for a bigger party: passengers in even chunks (6 -> 3 + 3), the price split per
passenger so the parts sum EXACTLY to the item price. Every other item is one booking for the
whole party. Used at voting close and again when a member leaves before anything is bought.
"""

from beanie import PydanticObjectId

from app.core.domain.bookings import purchase_cap, split_party
from app.core.domain.packages import booking_goal
from app.core.domain.trips import BookingKind, split_evenly
from app.db.identifiers import identifier_of
from app.models.bookings import Booking
from app.models.trips import ProposalItem, Trip

TITLE_MAX_LENGTH = 200
GOAL_MAX_LENGTH = 4000


def bookings_for_item(
    trip: Trip,
    item: ProposalItem,
    item_index: int,
    passengers: list[PydanticObjectId],
    *,
    amount_minor: int | None = None,
    train_supplier_url: str | None = None,
) -> list[Booking]:
    """The bookings for one package item and its party (in vault order).

    `amount_minor` defaults to the item price; pass the current amount when rebuilding
    bookings whose price was already re-quoted. `train_supplier_url` is the demo seam: train
    bookings then point at the fake rail supplier, every part of a split included.
    """
    if not passengers:
        raise ValueError("a booking needs at least one passenger")
    total = item.price_minor if amount_minor is None else amount_minor
    cap = purchase_cap(item.supplier) if item.kind is BookingKind.TRAIN else None
    sizes = split_party(len(passengers), cap)
    per_passenger = split_evenly(total, len(passengers))
    supplier_url = (
        train_supplier_url
        if item.kind is BookingKind.TRAIN and train_supplier_url
        else item.supplier_url
    )

    bookings: list[Booking] = []
    start = 0
    for part, size in enumerate(sizes, start=1):
        end = start + size
        details = item.details
        title = item.title
        if len(sizes) > 1:
            title = f"{item.title} (passengers {start + 1}-{end})"
            details = (
                f"{details} This is purchase {part} of {len(sizes)}: passengers "
                f"{start + 1}-{end} of the group of {len(passengers)}, exactly {size} "
                f"passengers. The vault passengers passenger_1..passenger_{size} are the "
                "travellers of THIS purchase."
            ).strip()
        bookings.append(
            Booking(
                trip_id=identifier_of(trip),
                kind=item.kind,
                title=title[:TITLE_MAX_LENGTH],
                supplier=item.supplier,
                supplier_url=supplier_url,
                amount_minor=sum(per_passenger[start:end]),
                goal=booking_goal(
                    kind=item.kind,
                    title=item.title,
                    details=details,
                    travellers=size,
                    date_from=trip.date_from,
                    date_to=trip.date_to,
                    starts_at=item.starts_at,
                )[:GOAL_MAX_LENGTH],
                passenger_user_ids=passengers[start:end],
                proposal_item_index=item_index,
            )
        )
        start = end
    return bookings
