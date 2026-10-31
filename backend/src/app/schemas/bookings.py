"""Booking / agent-run request and response schemas. Input validation at the HTTP boundary."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.domain.trips import (
    AgentOutcome,
    AgentRunStatus,
    BookingKind,
    BookingStatus,
    ContributionStatus,
    TripStatus,
)
from app.schemas.common import StrictRequest
from app.schemas.trips import VisibleText

OBJECT_ID_LENGTH = 24
MAX_DELAY_MINUTES = 24 * 60
CONFIRMATION_REF_MAX_LENGTH = 120


class ApproveRequest(StrictRequest):
    approved: bool


class CompleteManuallyRequest(StrictRequest):
    # The supplier's booking number, as the organizer read it after finishing by hand.
    confirmation_ref: VisibleText = Field(min_length=1, max_length=CONFIRMATION_REF_MAX_LENGTH)


class DisruptionRequest(StrictRequest):
    # Which booking is hit; defaults to the trip's confirmed train.
    booking_id: str | None = Field(
        default=None, min_length=OBJECT_ID_LENGTH, max_length=OBJECT_ID_LENGTH
    )
    delay_minutes: int = Field(default=140, ge=1, le=MAX_DELAY_MINUTES)
    # The replacement's price relative to the original: +5 = five percent dearer.
    price_change_percent: float = Field(default=5.0, ge=-90, le=300)


class AgentRunResponse(BaseModel):
    run_id: str
    status: AgentRunStatus
    outcome: AgentOutcome | None
    milestone: str | None
    steps: int
    reason: str
    cost_usd: float
    started_at: datetime | None
    finished_at: datetime | None


class BookingResponse(BaseModel):
    id: str
    trip_id: str
    kind: BookingKind
    title: str
    supplier: str
    supplier_url: str
    amount_minor: int
    status: BookingStatus
    confirmation_ref: str | None
    replaces_booking_id: str | None
    # Who travels on this purchase (empty on bookings made before parties were recorded).
    passenger_user_ids: list[str]
    run: AgentRunResponse | None


class TripBookingsResponse(BaseModel):
    trip_id: str
    trip_status: TripStatus
    currency: str
    total_minor: int
    travellers: int  # members of the trip
    # Lets the UI show organizer-only controls; the server enforces it regardless.
    is_organizer: bool
    bookings: list[BookingResponse]


class LiveStatusResponse(BaseModel):
    """What the runner reports in `status.json` right now."""

    milestone: str | None
    reached: list[str]
    step: int
    reason: str
    # The runner's outcome so far; `awaiting_approval` while it waits for the human.
    outcome: str | None
    cost_usd: float


class RunStatusResponse(BaseModel):
    booking_id: str
    run: AgentRunResponse
    live: LiveStatusResponse


class ShareChangeResponse(BaseModel):
    user_id: str
    display_name: str
    previous_minor: int
    share_minor: int
    delta_minor: int
    paid_minor: int
    status: ContributionStatus


class DisruptionResponse(BaseModel):
    # A train for a party above the supplier's cap is several purchases: every one of them is
    # cancelled and replaced (same order in both lists).
    cancelled_booking_ids: list[str]
    replacements: list[BookingResponse]
    trip_status: TripStatus
    previous_total_minor: int
    total_minor: int
    shares: list[ShareChangeResponse]
