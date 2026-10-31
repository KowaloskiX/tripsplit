"""Mapping of domain errors onto HTTP.

A separate module because this is the only place that knows both worlds: `AuthError` codes
from the domain and HTTP statuses. Routers therefore carry no lookup tables, and adding a
new error is one line in one file.
"""

from starlette import status

from app.core.domain.errors import AuthError, BookingError
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
}


def booking_failure(error: BookingError) -> DomainHTTPError:
    return DomainHTTPError(error, _BOOKING_STATUS[error], _BOOKING_MESSAGE[error])
