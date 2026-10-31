"""Turning one item of the chosen package into the booking(s) that buy it.

How many purchases an item needs comes from its supplier's capabilities, never from its name:
a supplier that caps the passengers of one purchase (`max_party_per_purchase`, e.g. 5 for a
rail carrier) gets several bookings for a bigger party — passengers in even chunks (6 -> 3 + 3),
the price split per passenger so the parts sum EXACTLY to the item price. A supplier without a
cap gets one booking for the whole party. Used at voting close and again when a member leaves
before anything is bought.
"""

from beanie import PydanticObjectId

from app.core.domain.packages import booking_goal
from app.core.domain.suppliers import SupplierCapabilities, purchase_sizes
from app.core.domain.trips import SupplierChannel, split_evenly
from app.db.identifiers import identifier_of
from app.models.bookings import Booking
from app.models.trips import ProposalItem, TransportSegment, Trip
from app.models.trust import stored_links, stored_provenance

TITLE_MAX_LENGTH = 200
GOAL_MAX_LENGTH = 4000


def itinerary(segments: list[TransportSegment]) -> str:
    """ "LO 401 WAW -> BCN 2026-11-20 07:05; LO 402 BCN -> WAW 2026-11-22 16:40"."""
    return "; ".join(
        f"{s.number} {s.origin} -> {s.destination} {s.departs_at:%Y-%m-%d %H:%M}" for s in segments
    )


def bookings_for_item(
    trip: Trip,
    item: ProposalItem,
    item_index: int,
    passengers: list[PydanticObjectId],
    capabilities: SupplierCapabilities | None,
    *,
    amount_minor: int | None = None,
) -> list[Booking]:
    """The bookings for one package item and its party (in vault order).

    `capabilities` are those of the item's supplier; None for an item from outside the registry
    (one purchase, bought by the agent at `supplier_url`). `amount_minor` defaults to the item
    price; pass the current amount when rebuilding bookings whose price was already re-quoted.
    """
    if not passengers:
        raise ValueError("a booking needs at least one passenger")
    total = item.price_minor if amount_minor is None else amount_minor
    sizes = purchase_sizes(len(passengers), capabilities) if capabilities else [len(passengers)]
    channel = capabilities.channel if capabilities else SupplierChannel.AGENT
    per_passenger = split_evenly(total, len(passengers))

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
                mode=item.mode,
                title=title[:TITLE_MAX_LENGTH],
                supplier=item.supplier,
                supplier_url=item.supplier_url,
                amount_minor=sum(per_passenger[start:end]),
                goal=booking_goal(
                    kind=item.kind,
                    title=item.title,
                    details=details,
                    travellers=size,
                    date_from=trip.date_from,
                    date_to=trip.date_to,
                    starts_at=item.starts_at,
                    itinerary=itinerary(item.segments),
                )[:GOAL_MAX_LENGTH],
                passenger_user_ids=passengers[start:end],
                proposal_item_index=item_index,
                supplier_id=item.supplier_id,
                offer_ref=item.offer_ref,
                channel=channel,
                supplier_data=dict(item.supplier_data),
                links=stored_links(item.links),
                images=list(item.images),
                provenance=stored_provenance(item.provenance),
            )
        )
        start = end
    return bookings
