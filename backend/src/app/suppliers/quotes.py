"""Re-quoting a booking right before the agent buys it.

Prices on a supplier listing are indicative: only the final summary is binding, and a PKP fare
quote carries its own expiry. So the booking service asks for the CURRENT price of the
booking's whole party before launching the agent, and re-splits the group's shares when it moved.

`QuoteProvider` is the port. `StaticQuotes` (the default) trusts the stored amount — exactly
the behaviour before re-quoting existed. `IntercityQuotes` asks PKP Intercity again.
"""

import logging
from typing import Protocol

from app.core.config import Settings
from app.core.domain.bookings import PKP_INTERCITY
from app.models.bookings import Booking
from app.suppliers.intercity import HttpTransport, IntercityClient, Transport

logger = logging.getLogger(__name__)


class QuoteProvider(Protocol):
    async def quote(self, booking: Booking) -> int | None:
        """The current price in grosze for the booking's whole party; None = no longer
        available (sold out, train gone)."""
        ...


class StaticQuotes:
    """The stored amount is the price — no supplier is asked."""

    async def quote(self, booking: Booking) -> int | None:
        return booking.amount_minor


class IntercityQuotes:
    """Re-queries PKP Intercity for bookings that carry a `train_query`.

    Limits, deliberately simple:
    - Only bookings of supplier "PKP Intercity" WITH a `train_query` and a known party
      (`passenger_user_ids`) are re-quoted; anything else answers its stored amount.
    - One direction: the train identified by its first leg on the query's date. A booking
      priced as a return journey must not carry a one-way `train_query`.
    - A party above the purchase cap is quoted as the split PKP needs (`group_quote`).
    - A transport failure (Akamai reset, timeout) falls back to the stored amount: the human
      still approves the binding summary before the agent pays.
    """

    def __init__(self, transport: Transport) -> None:
        self.client = IntercityClient(transport)

    async def quote(self, booking: Booking) -> int | None:
        query = booking.train_query
        if (
            booking.supplier.strip().casefold() != PKP_INTERCITY.casefold()
            or query is None
            or not booking.passenger_user_ids
        ):
            return booking.amount_minor
        try:
            connections = await self.client.connections(
                query.from_code, query.to_code, query.departs_at.date()
            )
            connection = next(
                (
                    candidate
                    for candidate in connections
                    if candidate.legs[0].number == query.train_number
                    and candidate.legs[0].departs_at == query.departs_at.replace(tzinfo=None)
                ),
                None,
            )
            if connection is None:
                return None
            group = await self.client.group_quote(
                connection,
                query.from_code,
                query.to_code,
                len(booking.passenger_user_ids),
                travel_class=query.travel_class,
                refundable=query.refundable,
            )
        except Exception:
            # The boundary to an unofficial supplier API: any failure means "could not ask",
            # never "sold out" — keep the stored price and let the summary be the judge.
            logger.exception("PKP Intercity re-quote failed for booking %s", booking.id)
            return booking.amount_minor
        return group.total_minor if group is not None else None


def build_quote_provider(settings: Settings) -> QuoteProvider:
    match settings.quotes:
        case "static":
            return StaticQuotes()
        case "intercity":
            return IntercityQuotes(HttpTransport())
