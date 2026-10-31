"""Booking / agent-run request and response schemas. Input validation at the HTTP boundary."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.domain.errors import BookingError
from app.core.domain.trips import (
    AgentOutcome,
    AgentRunStatus,
    BookingKind,
    BookingStatus,
    ContributionStatus,
    RunStepSource,
    RunStepStatus,
    SupplierChannel,
    TransportMode,
    TripStatus,
)
from app.schemas.common import StrictRequest
from app.schemas.trips import LinkResponse, ProvenanceResponse, VisibleText

OBJECT_ID_LENGTH = 24
MAX_DELAY_MINUTES = 24 * 60
CONFIRMATION_REF_MAX_LENGTH = 120


class ApproveRequest(StrictRequest):
    approved: bool


class CompleteManuallyRequest(StrictRequest):
    # The supplier's booking number, as the organizer read it after finishing by hand.
    confirmation_ref: VisibleText = Field(min_length=1, max_length=CONFIRMATION_REF_MAX_LENGTH)


class DisruptionRequest(StrictRequest):
    # Which booking is hit; defaults to the trip's first confirmed transport.
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
    mode: TransportMode | None
    title: str
    supplier: str
    supplier_url: str
    # The supplier plugin and how it is bought: the agent drives the site, the backend calls
    # the supplier's API after the approval, or a human books it by hand.
    supplier_id: str
    channel: SupplierChannel
    # Until when the supplier holds this price; null = no hold.
    hold_expires_at: datetime | None
    amount_minor: int
    status: BookingStatus
    confirmation_ref: str | None
    replaces_booking_id: str | None
    # Who travels on this purchase (empty on bookings made before parties were recorded).
    passenger_user_ids: list[str]
    run: AgentRunResponse | None
    # Trust: where to book / verify / find it, photos, where the data came from.
    links: list[LinkResponse]
    images: list[str]
    provenance: ProvenanceResponse | None


class TripBookingsResponse(BaseModel):
    trip_id: str
    trip_status: TripStatus
    currency: str
    total_minor: int
    travellers: int  # members of the trip
    # Lets the UI show organizer-only controls; the server enforces it regardless.
    is_organizer: bool
    bookings: list[BookingResponse]


class RunStepResponse(BaseModel):
    index: int
    # The flow-graph node this step belongs to (see `FlowGraphResponse`).
    node_id: str | None
    # The agent's action ("goto", "click", "fill_form", ...): an open set that grows with the
    # agent, so a plain string — the UI shows an unknown one as "other".
    kind: str
    status: RunStepStatus
    duration_ms: int | None
    source: RunStepSource
    iteration: int | None


class LiveStatusResponse(BaseModel):
    """What the runner reports in `status.json` right now."""

    milestone: str | None
    reached: list[str]
    step: int
    reason: str
    # The runner's outcome so far; `awaiting_approval` while it waits for the human.
    outcome: str | None
    cost_usd: float
    steps: list[RunStepResponse]
    # Engine counters: replayed flow steps, rule steps, planner (LLM) calls, tokens used.
    flow_steps: int
    rule_steps: int
    llm_calls: int
    tokens: int


class FlowNodeResponse(BaseModel):
    id: str
    # open_url | fill | choose | click | loop | verify | approve — an open set like `kind`.
    type: str
    label: str
    stage: str | None
    # Variable NAMES the node reads (`vault.passenger_{i}_first_name`), never values.
    inputs: list[str]
    outputs: list[str]


class FlowEdgeResponse(BaseModel):
    # `from` is a Python keyword: the field is `source` with the wire name `from`.
    source: str = Field(serialization_alias="from")
    to: str


class FlowGraphResponse(BaseModel):
    """The run's plan, `runs/<id>/flow_graph.json`: what the agent intends to do, node by node."""

    nodes: list[FlowNodeResponse]
    edges: list[FlowEdgeResponse]


class BatchItemResponse(BaseModel):
    booking: BookingResponse
    # Why THIS booking was refused (the same codes as the single-booking endpoints); null = ok.
    error: BookingError | None


class BatchResponse(BaseModel):
    """Every booking a "book everything" / "approve the basket" click touched."""

    trip_status: TripStatus
    items: list[BatchItemResponse]


class SupplierCallResponse(BaseModel):
    """One API call a supplier adapter made for this trip — for the live terminal. The path
    has every identifier replaced by `{id}` and no query string; nothing else is kept."""

    supplier_id: str
    supplier: str
    method: str
    path: str
    # The HTTP status; null = no answer (network error or timeout).
    status: int | None
    ms: int
    at: datetime


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
    # An item for a party above the supplier's cap is several purchases: every one of them is
    # cancelled and replaced (same order in both lists).
    cancelled_booking_ids: list[str]
    replacements: list[BookingResponse]
    trip_status: TripStatus
    previous_total_minor: int
    total_minor: int
    shares: list[ShareChangeResponse]
