"""Mapping of domain errors onto HTTP.

A separate module because this is the only place that knows both worlds: `AuthError` codes
from the domain and HTTP statuses. Routers therefore carry no lookup tables, and adding a
new error is one line in one file.
"""

from starlette import status

from app.core.domain.errors import AuthError, BookingError, TripError
from app.core.domain.result import Ok, Result
from app.core.domain.wallet import InsufficientFunds, TopUpFailure, WalletError
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
    TripError.ATTRACTION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
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
    TripError.ATTRACTION_NOT_FOUND: "No such attraction on this trip.",
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
    BookingError.GRAPH_NOT_FOUND: status.HTTP_404_NOT_FOUND,
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
    BookingError.GRAPH_NOT_FOUND: "The agent has not written its plan yet.",
    BookingError.NOT_ORGANIZER: "Only the trip organizer can do this.",
    BookingError.TRIP_NOT_READY: "Booking starts only once everyone has paid their share.",
    BookingError.BOOKING_NOT_STARTABLE: "This booking is already in progress or done.",
    BookingError.NOT_AWAITING_APPROVAL: "This booking is not waiting for an approval.",
    BookingError.NOTHING_TO_DISRUPT: "There is no confirmed booking to disrupt.",
    BookingError.SOLD_OUT: "The supplier no longer offers this booking.",
    BookingError.PRICE_CHANGED: (
        "The supplier changed the price. Shares were re-split. Top up, then start again."
    ),
    BookingError.NOT_COMPLETABLE: "Only a handed-off or failed booking can be finished by hand.",
    BookingError.TRAVELLER_DETAILS_MISSING: (
        "Some travellers have not entered the details this supplier needs. See the trip feed."
    ),
    BookingError.QUOTE_EXPIRED: "The price is no longer guaranteed. Start the booking again.",
    BookingError.SUPPLIER_UNKNOWN: "The supplier of this booking is not available right now.",
}


def booking_failure(error: BookingError) -> DomainHTTPError:
    return DomainHTTPError(error, _BOOKING_STATUS[error], _BOOKING_MESSAGE[error])


_TOP_UP_STATUS: dict[TopUpFailure, int] = {
    TopUpFailure.AMOUNT_OUT_OF_RANGE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TopUpFailure.INVALID_BLIK_CODE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TopUpFailure.INVALID_CARD: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TopUpFailure.DECLINED: status.HTTP_402_PAYMENT_REQUIRED,
    TopUpFailure.NOT_FOUND: status.HTTP_404_NOT_FOUND,
}

_TOP_UP_MESSAGE: dict[TopUpFailure, str] = {
    TopUpFailure.AMOUNT_OUT_OF_RANGE: "A top-up is between 1 zł and 10 000 zł.",
    TopUpFailure.INVALID_BLIK_CODE: "Enter the 6-digit BLIK code from your bank app.",
    TopUpFailure.INVALID_CARD: "Enter a valid card.",
    TopUpFailure.DECLINED: "Your bank declined the payment.",
    TopUpFailure.NOT_FOUND: "No such top-up.",
}


def top_up_failure(error: TopUpFailure) -> DomainHTTPError:
    return DomainHTTPError(error, _TOP_UP_STATUS[error], _TOP_UP_MESSAGE[error])


def payment_value[T](result: Result[T, TripError | InsufficientFunds | TopUpFailure]) -> T:
    """`trip_value` for money paths: also maps a short wallet (409 with `shortfall_minor`) and
    a refused top-up."""
    if isinstance(result, Ok):
        return result.value
    error = result.error
    if isinstance(error, InsufficientFunds):
        raise DomainHTTPError(
            WalletError.INSUFFICIENT_FUNDS,
            status.HTTP_409_CONFLICT,
            "Your wallet does not cover your share. Top up first.",
            extra={"shortfall_minor": error.shortfall_minor},
        )
    if isinstance(error, TopUpFailure):
        raise top_up_failure(error)
    raise trip_failure(error)
