"""Domain error codes. Never a bare string — see docs/conventions/01."""

from enum import StrEnum


class AuthError(StrEnum):
    INVALID_CREDENTIALS = "invalid_credentials"
    EMAIL_TAKEN = "email_taken"
    SESSION_INVALID = "session_invalid"
    ACCOUNT_DISABLED = "account_disabled"


class TripError(StrEnum):
    # A trip the caller is not a member of is reported as missing — existence is not leaked.
    NOT_FOUND = "trip_not_found"
    PROPOSAL_NOT_FOUND = "proposal_not_found"
    NOT_ORGANIZER = "not_organizer"
    INVALID_STATE = "invalid_trip_state"
    NO_PROPOSALS = "no_proposals"
    ALREADY_PAID = "already_paid"
    ORGANIZER_CANNOT_LEAVE = "organizer_cannot_leave"
    BOOKING_STARTED = "booking_started"  # too late to leave: the agent is already buying


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
    SOLD_OUT = "sold_out"  # the supplier no longer offers what the booking describes
    PRICE_CHANGED = "price_changed"  # re-quoted dearer: the group tops up before the purchase
    NOT_COMPLETABLE = "booking_not_completable"  # only a handoff / failure is finished by hand
    # The supplier needs traveller details (date of birth, document, ...) somebody has not
    # entered yet; the feed names who and which fields — never the values.
    TRAVELLER_DETAILS_MISSING = "traveller_details_missing"
    # The quote (or hold) behind a summary went stale before the approval: start again.
    QUOTE_EXPIRED = "quote_expired"
    SUPPLIER_UNKNOWN = "supplier_unknown"  # the booking names a supplier that is not enabled
