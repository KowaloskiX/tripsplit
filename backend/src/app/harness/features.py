"""Detects which domain features the product code has today.

The harness is written against the contract of the domain-lifecycle work. Until a piece of it
lands, steps that need it are `pending` (named, never silently skipped) and invariants that
depend on it are reported as known issues. When it lands, everything turns strict on its own.
"""

import inspect
from dataclasses import dataclass
from enum import StrEnum

from app.core.domain.errors import BookingError
from app.core.domain.trips import EventKind
from app.models.bookings import Booking
from app.services.bookings import BookingService
from app.services.trips import TripService


class Feature(StrEnum):
    QUOTES = "quotes"
    LEAVE = "leave"
    COMPLETE_MANUALLY = "complete_manually"
    PASSENGER_SPLIT = "passenger_split"


@dataclass(frozen=True, slots=True)
class FeatureInfo:
    present: bool
    missing: str  # what exactly is missing, for the report


def _quotes() -> FeatureInfo:
    takes_quotes = "quotes" in inspect.signature(BookingService.__init__).parameters
    has_error = "PRICE_CHANGED" in BookingError.__members__
    has_event = "PRICE_CHANGED" in EventKind.__members__
    return FeatureInfo(
        present=takes_quotes and has_error and has_event,
        missing=(
            "BookingService(quotes=QuoteProvider) re-quoting on start, "
            "BookingError.PRICE_CHANGED and EventKind.PRICE_CHANGED (feat/domain-lifecycle)"
        ),
    )


def _leave() -> FeatureInfo:
    return FeatureInfo(
        present=callable(getattr(TripService, "leave", None)),
        missing="TripService.leave(trip_id, user_id) with a re-split (feat/domain-lifecycle)",
    )


def _complete_manually() -> FeatureInfo:
    return FeatureInfo(
        present=callable(getattr(BookingService, "complete_manually", None)),
        missing=(
            "BookingService.complete_manually(trip_id, user_id, booking_id, confirmation_ref) "
            "for a HANDOFF booking (feat/domain-lifecycle)"
        ),
    )


def _passenger_split() -> FeatureInfo:
    return FeatureInfo(
        present="passenger_user_ids" in Booking.model_fields,
        missing=(
            "Booking.passenger_user_ids — train bookings split into purchases of at most 5 "
            "passengers at voting close (feat/domain-lifecycle)"
        ),
    )


def feature(name: Feature) -> FeatureInfo:
    match name:
        case Feature.QUOTES:
            return _quotes()
        case Feature.LEAVE:
            return _leave()
        case Feature.COMPLETE_MANUALLY:
            return _complete_manually()
        case Feature.PASSENGER_SPLIT:
            return _passenger_split()


def all_features() -> dict[Feature, FeatureInfo]:
    return {name: feature(name) for name in Feature}
