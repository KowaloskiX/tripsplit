"""Domain error codes. Never a bare string — see docs/conventions/01."""

from enum import StrEnum


class AuthError(StrEnum):
    INVALID_CREDENTIALS = "invalid_credentials"
    EMAIL_TAKEN = "email_taken"
    SESSION_INVALID = "session_invalid"
    ACCOUNT_DISABLED = "account_disabled"


class ApiError(StrEnum):
    """Edge-layer errors — they do not belong to any business domain."""

    RATE_LIMITED = "rate_limited"
    CSRF_INVALID = "csrf_invalid"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    VALIDATION_FAILED = "validation_failed"
    INTERNAL_ERROR = "internal_error"


class BookingError(StrEnum):
    TRIP_NOT_FOUND = "trip_not_found"  # also what a non-member sees: no existence oracle
    BOOKING_NOT_FOUND = "booking_not_found"
    RUN_NOT_FOUND = "run_not_found"
    FRAME_NOT_FOUND = "frame_not_found"
    NOT_ORGANIZER = "not_organizer"
    TRIP_NOT_READY = "trip_not_ready"  # Rule #1: nobody buys before everyone has paid
    BOOKING_NOT_STARTABLE = "booking_not_startable"
    NOT_AWAITING_APPROVAL = "not_awaiting_approval"
    NOTHING_TO_DISRUPT = "nothing_to_disrupt"
