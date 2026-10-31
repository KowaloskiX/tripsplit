"""Mapping of domain errors onto HTTP.

A separate module because this is the only place that knows both worlds: `AuthError` codes
from the domain and HTTP statuses. Routers therefore carry no lookup tables, and adding a
new error is one line in one file.
"""

from starlette import status

from app.core.domain.errors import AuthError, TripError
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
}

_TRIP_MESSAGE: dict[TripError, str] = {
    TripError.NOT_FOUND: "No such trip.",
    TripError.PROPOSAL_NOT_FOUND: "No such package on this trip.",
    TripError.NOT_ORGANIZER: "Only the organizer can do this.",
    TripError.INVALID_STATE: "The trip is not at a stage where this is possible.",
    TripError.NO_PROPOSALS: "There are no packages to vote on yet.",
    TripError.ALREADY_PAID: "Your share is already paid.",
}


def trip_failure(error: TripError) -> DomainHTTPError:
    return DomainHTTPError(error, _TRIP_STATUS[error], _TRIP_MESSAGE[error])


def trip_value[T](result: Result[T, TripError]) -> T:
    """The value of a successful result, or the mapped HTTP error."""
    if isinstance(result, Ok):
        return result.value
    raise trip_failure(result.error)
