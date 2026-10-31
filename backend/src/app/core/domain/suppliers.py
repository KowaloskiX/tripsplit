"""What a supplier can do, and the rules the trip flow derives from it. Pure Python.

The core never asks "is this PKP Intercity?". Every supplier — a rail carrier, an airline API,
a bus site, a hotel prebook — declares its `SupplierCapabilities`, and the booking flow reads
behaviour off them: how a party is split into purchases, whether a price can be held while the
group pays, which traveller details must exist before buying, how long a quote stays good.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.core.domain.bookings import split_party
from app.core.domain.trips import BookingKind, SupplierChannel, TransportMode


class TravellerField(StrEnum):
    """A piece of traveller data a supplier may require per passenger."""

    FULL_NAME = "full_name"
    DATE_OF_BIRTH = "date_of_birth"
    NATIONALITY = "nationality"
    DOCUMENT_NUMBER = "document_number"
    DOCUMENT_EXPIRY = "document_expiry"
    GENDER = "gender"


DEFAULT_QUOTE_TTL = timedelta(minutes=30)
NAME_ONLY: frozenset[TravellerField] = frozenset({TravellerField.FULL_NAME})


@dataclass(frozen=True, slots=True)
class SupplierCapabilities:
    kind: BookingKind
    mode: TransportMode | None
    channel: SupplierChannel
    # Passengers one purchase may carry (PKP Intercity online: 5); None = no known limit.
    max_party_per_purchase: int | None
    supports_hold: bool = False
    hold_ttl: timedelta | None = None
    # How long a quoted price may be used for a purchase before it must be asked again.
    quote_ttl: timedelta = DEFAULT_QUOTE_TTL
    required_traveller_fields: frozenset[TravellerField] = NAME_ONLY
    refund_policy_known: bool = False
    reports_disruptions: bool = False
    # A hold is a named booking at the supplier (an airline hold order needs every
    # passenger's name, birth date, ...): it is placed only once the passengers' required
    # traveller details are complete — at voting close if they are, else when the purchase
    # starts. False = a hold needs nothing but the party size.
    hold_needs_traveller_details: bool = False

    def __post_init__(self) -> None:
        if (self.kind is BookingKind.TRANSPORT) != (self.mode is not None):
            raise ValueError("a transport supplier needs a mode, and only a transport one")
        if self.max_party_per_purchase is not None and self.max_party_per_purchase <= 0:
            raise ValueError("a purchase cap must be positive")
        if self.supports_hold != (self.hold_ttl is not None):
            raise ValueError("a hold TTL is declared exactly when holds are supported")
        if self.quote_ttl <= timedelta(0):
            raise ValueError("a quote must stay valid for some time")


def purchase_sizes(travellers: int, capabilities: SupplierCapabilities) -> list[int]:
    """How a party is split into purchases at this supplier: 6 at a cap of 5 -> [3, 3]."""
    return split_party(travellers, capabilities.max_party_per_purchase)


def missing_traveller_fields[K](
    required: frozenset[TravellerField], provided: Mapping[K, frozenset[TravellerField]]
) -> dict[K, frozenset[TravellerField]]:
    """Who still lacks which required fields; travellers with everything are left out."""
    missing = {key: required - fields for key, fields in provided.items()}
    return {key: fields for key, fields in missing.items() if fields}


def as_utc(moment: datetime) -> datetime:
    """A naive datetime is taken as UTC (that is what Mongo stores)."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def hold_is_live(expires_at: datetime | None, now: datetime) -> bool:
    return expires_at is not None and as_utc(now) < as_utc(expires_at)


def quote_is_fresh(quoted_at: datetime | None, ttl: timedelta, now: datetime) -> bool:
    """A price quoted at `quoted_at` may still be used for a purchase at `now`."""
    return quoted_at is not None and as_utc(now) - as_utc(quoted_at) <= ttl


def price_is_guaranteed(
    capabilities: SupplierCapabilities,
    *,
    hold_expires_at: datetime | None,
    quoted_at: datetime | None,
    now: datetime,
) -> bool:
    """The price a purchase would use right now is binding: a live hold, or a fresh quote."""
    if capabilities.supports_hold and hold_is_live(hold_expires_at, now):
        return True
    return quote_is_fresh(quoted_at, capabilities.quote_ttl, now)


def mode_noun(mode: TransportMode | None) -> str:
    """ "train" / "flight" / "bus" / "ferry" — for messages in the feed."""
    match mode:
        case TransportMode.RAIL:
            return "train"
        case TransportMode.FLIGHT:
            return "flight"
        case TransportMode.BUS:
            return "bus"
        case TransportMode.FERRY:
            return "ferry"
        case None:
            return "option"


def purchase_noun(kind: BookingKind, mode: TransportMode | None, travellers: int) -> str:
    """What one purchase buys, for the feed: "6 flight tickets", "the stay for 6"."""
    match kind:
        case BookingKind.TRANSPORT:
            return f"{travellers} {mode_noun(mode)} tickets"
        case BookingKind.STAY:
            return f"the stay for {travellers}"
        case BookingKind.ACTIVITY:
            return f"{travellers} activity tickets"
