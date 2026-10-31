"""The supplier port: every rail carrier, airline, bus line, hotel and activity seller is a
plugin behind `SupplierAdapter`.

The trip flow only knows this module and `SupplierCapabilities`. An adapter owns everything
supplier-specific: how to search, how its offers are identified (`offer_ref` plus the opaque
`supplier_data` it gets back on every later call), how to quote, hold, buy and report a
disruption. Plain dataclasses on both sides — no Beanie, no HTTP framework.

Which optional methods are called is decided by the capabilities, never by `isinstance`:
`hold` only when `supports_hold`, `purchase` only for `channel=api`, `status` only when
`reports_disruptions`. An adapter that lacks one answers None (or `Err`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol

from app.core.domain.result import Result
from app.core.domain.suppliers import SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import NO_PREFERENCES, TransportMode, TravelPreferences


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """One search. For a stay the dates are check-in / check-out; for an activity the first
    is the day. `return_date=None` asks a transport supplier for one-way offers."""

    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    party_size: int
    mode: TransportMode | None = None
    budget_per_person_minor: int | None = None
    currency: str = "PLN"
    # Departure-hour and transfer limits; transport adapters filter by them where they can.
    preferences: TravelPreferences = NO_PREFERENCES


@dataclass(frozen=True, slots=True)
class Segment:
    """One leg: a flight, a train, a bus ride."""

    carrier: str  # "LOT Polish Airlines", "PKP Intercity", "FlixBus"
    number: str  # "LO 401", "EC 131", "N 1070"
    origin: str  # "WAW", "Warszawa Centralna"
    destination: str
    departs_at: datetime
    arrives_at: datetime

    def describe(self) -> str:
        return (
            f"{self.number} {self.origin} -> {self.destination} "
            f"{self.departs_at:%Y-%m-%d %H:%M}-{self.arrives_at:%H:%M}"
        )


@dataclass(frozen=True, slots=True)
class Offer:
    supplier_id: str
    offer_ref: str  # opaque to everyone but the adapter
    title: str
    price_minor: int  # for the WHOLE party of the search
    currency: str
    seller: str  # who the group buys from, for the feed ("Ryanair", "Booking.com")
    segments: tuple[Segment, ...] = ()
    refundable: bool = False
    expires_at: datetime | None = None
    # Where the agent starts (channel=agent) or a human books (channel=manual).
    purchase_url: str = ""
    details: str = ""
    starts_at: datetime | None = None
    # Adapter-owned data handed back on quote/hold/purchase/status. Never from a client.
    supplier_data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OfferRef:
    supplier_id: str
    offer_ref: str
    supplier_data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Quote:
    price_minor: int  # for the party asked about
    currency: str
    quoted_at: datetime
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Hold:
    ref: str
    expires_at: datetime
    price_minor: int


@dataclass(frozen=True, slots=True)
class BookingRef:
    offer: OfferRef
    confirmation_ref: str | None
    party_size: int
    # The supplier's own id of the held/bought booking (`Hold.ref`), when it differs from the
    # confirmation ref (an airline order id vs its PNR). None = no hold was placed.
    hold_ref: str | None = None


class DisruptionKind(StrEnum):
    DELAY = "delay"
    CANCELLATION = "cancellation"


@dataclass(frozen=True, slots=True)
class DisruptionNotice:
    kind: DisruptionKind
    message: str
    delay_minutes: int = 0
    # The supplier's own re-accommodation, priced for the booking's party; None = find one.
    replacement: Offer | None = None


class SupplierUnavailableError(Exception):
    """The supplier could not be asked (network, bot wall, outage) — NOT "sold out"."""


class SupplierAdapter(Protocol):
    id: str
    display_name: str
    capabilities: SupplierCapabilities

    async def search(self, request: SearchRequest) -> list[Offer]: ...

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        """The current price for `party_size`; None = no longer offered (sold out, gone)."""
        ...

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        """Locks the price for the party (supports_hold only); None = cannot be held."""
        ...

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        """Buys it (channel=api only): Ok(confirmation ref) or Err(reason)."""
        ...

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        """A delay / cancellation of a bought booking (reports_disruptions only)."""
        ...
