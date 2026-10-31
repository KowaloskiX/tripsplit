"""Mapping of domain errors onto HTTP.

A separate module because this is the only place that knows both worlds: `AuthError` codes
from the domain and HTTP statuses. Routers therefore carry no lookup tables, and adding a
new error is one line in one file.
"""

from starlette import status

from app.core.domain.errors import AuthError, BookingError, TripError
from app.core.domain.result import Ok, Result
from app.core.errors_http import DomainHTTPError

_STATUS: dict[AuthError, int] = {
    AuthError.INVALID_CREDENTIALS: status.HTTP_401_UNAUTHORIZED,
    AuthError.SESSION_INVALID: status.HTTP_401_UNAUTHORIZED,
    AuthError.ACCOUNT_DISABLED: status.HTTP_403_FORBIDDEN,
    AuthError.EMAIL_TAKEN: status.HTTP_409_CONFLICT,
}

_MESSAGE: dict[AuthError, str] = {
    AuthError.INVALID_CREDENTIALS: "Invalid email or password.",
    AuthError.SESSION_INVALID: "No active session.",
    AuthError.ACCOUNT_DISABLED: "This account is disabled.",
    AuthError.EMAIL_TAKEN: "An account with this email already exists.",
}


def auth_failure(error: AuthError) -> DomainHTTPError:
    return DomainHTTPError(error, _STATUS[error], _MESSAGE[error])


_TRIP_STATUS: dict[TripError, int] = {
    TripError.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    TripError.PROPOSAL_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    TripError.NOT_ORGANIZER: status.HTTP_403_FORBIDDEN,
    TripError.INVALID_STATE: status.HTTP_409_CONFLICT,
    TripError.NO_PROPOSALS: status.HTTP_409_CONFLICT,
    TripError.ALREADY_PAID: status.HTTP_409_CONFLICT,
    TripError.ORGANIZER_CANNOT_LEAVE: status.HTTP_409_CONFLICT,
    TripError.BOOKING_STARTED: status.HTTP_409_CONFLICT,
}

_TRIP_MESSAGE: dict[TripError, str] = {
    TripError.NOT_FOUND: "No such trip.",
    TripError.PROPOSAL_NOT_FOUND: "No such package on this trip.",
    TripError.NOT_ORGANIZER: "Only the organizer can do this.",
    TripError.INVALID_STATE: "The trip is not at a stage where this is possible.",
    TripError.NO_PROPOSALS: "There are no packages to vote on yet.",
    TripError.ALREADY_PAID: "Your share is already paid.",
    TripError.ORGANIZER_CANNOT_LEAVE: "The organizer cannot leave their own trip.",
    TripError.BOOKING_STARTED: "Too late to leave: the agent has already started booking.",
}


def trip_failure(error: TripError) -> DomainHTTPError:
    return DomainHTTPError(error, _TRIP_STATUS[error], _TRIP_MESSAGE[error])


def trip_value[T](result: Result[T, TripError]) -> T:
    """The value of a successful result, or the mapped HTTP error."""
    if isinstance(result, Ok):
        return result.value
    raise trip_failure(result.error)


_BOOKING_STATUS: dict[BookingError, int] = {
    BookingError.TRIP_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    BookingError.BOOKING_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    BookingError.RUN_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    BookingError.FRAME_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    BookingError.NOT_ORGANIZER: status.HTTP_403_FORBIDDEN,
    BookingError.TRIP_NOT_READY: status.HTTP_409_CONFLICT,
    BookingError.BOOKING_NOT_STARTABLE: status.HTTP_409_CONFLICT,
    BookingError.NOT_AWAITING_APPROVAL: status.HTTP_409_CONFLICT,
    BookingError.NOTHING_TO_DISRUPT: status.HTTP_409_CONFLICT,
    BookingError.SOLD_OUT: status.HTTP_409_CONFLICT,
    BookingError.PRICE_CHANGED: status.HTTP_409_CONFLICT,
    BookingError.NOT_COMPLETABLE: status.HTTP_409_CONFLICT,
    BookingError.TRAVELLER_DETAILS_MISSING: status.HTTP_409_CONFLICT,
    BookingError.QUOTE_EXPIRED: status.HTTP_409_CONFLICT,
    BookingError.SUPPLIER_UNKNOWN: status.HTTP_409_CONFLICT,
}

_BOOKING_MESSAGE: dict[BookingError, str] = {
    BookingError.TRIP_NOT_FOUND: "No such trip.",
    BookingError.BOOKING_NOT_FOUND: "No such booking.",
    BookingError.RUN_NOT_FOUND: "No such agent run.",
    BookingError.FRAME_NOT_FOUND: "The agent has not captured a frame yet.",
    BookingError.NOT_ORGANIZER: "Only the trip organizer can do this.",
    BookingError.TRIP_NOT_READY: "Booking starts only once everyone has paid their share.",
    BookingError.BOOKING_NOT_STARTABLE: "This booking is already in progress or done.",
    BookingError.NOT_AWAITING_APPROVAL: "This booking is not waiting for an approval.",
    BookingError.NOTHING_TO_DISRUPT: "There is no confirmed booking to disrupt.",
    BookingError.SOLD_OUT: "The supplier no longer offers this booking.",
    BookingError.PRICE_CHANGED: (
        "The supplier changed the price. Shares were re-split — top up, then start again."
    ),
    BookingError.NOT_COMPLETABLE: "Only a handed-off or failed booking can be finished by hand.",
    BookingError.TRAVELLER_DETAILS_MISSING: (
        "Some travellers have not entered the details this supplier needs — see the trip feed."
    ),
    BookingError.QUOTE_EXPIRED: "The price is no longer guaranteed. Start the booking again.",
    BookingError.SUPPLIER_UNKNOWN: "The supplier of this booking is not available right now.",
}


def booking_failure(error: BookingError) -> DomainHTTPError:
    return DomainHTTPError(error, _BOOKING_STATUS[error], _BOOKING_MESSAGE[error])
