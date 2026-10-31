"""Trip, proposal, contribution and feed schemas — the HTTP contract of the trip room.

Input: `StrictRequest`, scalar fields only (see `tests/test_injection_contract.py`). Output:
read models validated `from_attributes` straight from the services' views.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.core.domain.suppliers import TravellerField
from app.core.domain.trips import (
    MAX_TRANSFERS_LIMIT,
    BookingKind,
    ContributionStatus,
    EventActor,
    EventKind,
    MemberRole,
    TransportMode,
    TripStatus,
)
from app.schemas.common import StrictRequest, normalize_text

TITLE_MAX_LENGTH = 120
NAME_MAX_LENGTH = 60
BRIEF_MAX_LENGTH = 4000
MESSAGE_MAX_LENGTH = 2000
INVITE_CODE_MAX_LENGTH = 64
MAX_GROUP_SIZE = 20
MAX_DEMO_MEMBERS = 10
OBJECT_ID_LENGTH = 24


def _visible(value: str) -> str:
    normalized = normalize_text(value)
    if not normalized:
        raise ValueError("Must contain at least one visible character.")
    return normalized


# Normalized (NFKC, no control/format characters) and non-blank AFTER normalization.
VisibleText = Annotated[str, AfterValidator(_visible)]


class CreateTripRequest(StrictRequest):
    title: VisibleText = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    origin: VisibleText = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    brief: str = Field(default="", max_length=BRIEF_MAX_LENGTH)
    date_from: date
    date_to: date
    group_size: int = Field(ge=1, le=MAX_GROUP_SIZE)
    budget_per_person_minor: int | None = Field(default=None, ge=0)
    # How the organizer appears to the group.
    display_name: VisibleText = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    # Where to; empty = read from the title and brief.
    destination: str = Field(default="", max_length=TITLE_MAX_LENGTH)
    # How the group wants to travel; null = any mode the suppliers offer.
    transport_mode: TransportMode | None = None
    # Earliest departure hour (local, 0-23) for every leg; null = any time.
    earliest_departure_hour: int | None = Field(default=None, ge=0, le=23)
    # Most changes per direction (0 = direct only); null = any.
    max_transfers: int | None = Field(default=None, ge=0, le=MAX_TRANSFERS_LIMIT)

    @model_validator(mode="after")
    def _dates_in_order(self) -> Self:
        if self.date_to < self.date_from:
            raise ValueError("The trip cannot end before it starts.")
        return self


QUICK_TEXT_MAX_LENGTH = 1000
QUICK_ANSWER_MAX_LENGTH = 60

type QuickFieldName = Literal["destination", "dates", "group_size"]


class QuickTripRequest(StrictRequest):
    """A one-line brief ("weekend w Pradze dla 6, 20-22.11, do 700 zł/os, pociągiem"). The
    optional fields answer earlier `questions` (send the chip's `value` in the field named by
    the question) and win over what the text says."""

    text: VisibleText = Field(min_length=1, max_length=QUICK_TEXT_MAX_LENGTH)
    # How the organizer appears to the group; default: read from the e-mail address.
    display_name: VisibleText | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    destination: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)
    origin: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)
    # "2026-11-20/2026-11-22" (a chip value) or any phrase the brief parser reads.
    dates: str | None = Field(default=None, max_length=QUICK_ANSWER_MAX_LENGTH)
    group_size: int | None = Field(default=None, ge=1, le=MAX_GROUP_SIZE)
    budget_per_person_minor: int | None = Field(default=None, ge=0)
    transport_mode: TransportMode | None = None


class JoinTripRequest(StrictRequest):
    invite_code: str = Field(min_length=1, max_length=INVITE_CODE_MAX_LENGTH)
    display_name: VisibleText = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class PostMessageRequest(StrictRequest):
    text: VisibleText = Field(min_length=1, max_length=MESSAGE_MAX_LENGTH)


class CastVoteRequest(StrictRequest):
    proposal_id: str = Field(min_length=1, max_length=64)


class SeedMembersRequest(StrictRequest):
    count: int = Field(default=5, ge=1, le=MAX_DEMO_MEMBERS)


class DemoLeaveRequest(StrictRequest):
    # The seeded member who drops out.
    user_id: str = Field(min_length=OBJECT_ID_LENGTH, max_length=OBJECT_ID_LENGTH)


class _ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TripResponse(_ReadModel):
    id: str
    title: str
    origin: str
    brief: str
    date_from: date
    date_to: date
    group_size: int
    budget_per_person_minor: int | None
    currency: str
    destination: str
    transport_mode: TransportMode | None
    earliest_departure_hour: int | None
    max_transfers: int | None
    status: TripStatus
    organizer_id: str
    chosen_proposal_id: str | None
    total_minor: int


class TripSummaryResponse(_ReadModel):
    trip: TripResponse
    my_role: MemberRole


class MemberResponse(_ReadModel):
    user_id: str
    display_name: str
    role: MemberRole
    # Which traveller details the trip's suppliers need that this member has not entered yet
    # (field names only — values are never shown to anyone else).
    traveller_details_missing: list[TravellerField]
    traveller_details_complete: bool


class SegmentResponse(_ReadModel):
    carrier: str
    number: str
    origin: str
    destination: str
    departs_at: datetime
    arrives_at: datetime


class ProposalItemResponse(_ReadModel):
    kind: BookingKind
    mode: TransportMode | None
    title: str
    supplier: str
    supplier_url: str
    price_minor: int
    details: str
    starts_at: datetime | None
    segments: list[SegmentResponse]


class ProposalResponse(_ReadModel):
    id: str
    title: str
    summary: str
    items: list[ProposalItemResponse]
    total_minor: int
    per_person_minor: int
    # More per person than the trip's budget — shown as a badge on the package card.
    over_budget: bool
    votes: int
    voted_by_me: bool
    chosen: bool


class ContributionResponse(_ReadModel):
    user_id: str
    display_name: str
    amount_minor: int
    paid_minor: int
    outstanding_minor: int
    # Paid beyond the current share (status `refund_due`): "you get X back".
    refund_minor: int
    status: ContributionStatus


class RoomResponse(_ReadModel):
    trip: TripResponse
    invite_code: str
    my_user_id: str
    my_role: MemberRole
    members: list[MemberResponse]
    proposals: list[ProposalResponse]
    my_vote_proposal_id: str | None
    contributions: list[ContributionResponse]
    my_contribution: ContributionResponse | None
    paid_count: int


class EventResponse(_ReadModel):
    id: str
    kind: EventKind
    actor: EventActor
    message: str
    payload: dict[str, JsonValue]
    actor_user_id: str | None
    actor_name: str | None
    created_at: datetime


class TripStatusResponse(_ReadModel):
    trip_id: str
    status: TripStatus


class QuickOptionResponse(_ReadModel):
    label: str  # the chip: "Next weekend (13-15 Nov)"
    value: str  # sent back in the request field named by the question


class QuickQuestionResponse(_ReadModel):
    field: QuickFieldName
    question: str
    options: list[QuickOptionResponse]


class QuickDraftResponse(_ReadModel):
    """What the brief says so far; null = not understood (yet)."""

    title: str
    origin: str
    destination: str | None
    date_from: date | None
    date_to: date | None
    group_size: int | None
    budget_per_person_minor: int | None
    # A total budget ("3000 zł łącznie") still waiting for the party size.
    budget_total_minor: int | None
    transport_mode: TransportMode | None
    missing: list[QuickFieldName]


class QuickTripResponse(_ReadModel):
    # Set when the brief was complete: the trip exists (caller = organizer) and the package
    # research runs (status `proposing`). Null = answer `questions` and send the brief again.
    trip: TripStatusResponse | None
    draft: QuickDraftResponse
    questions: list[QuickQuestionResponse]


class PaymentResponse(_ReadModel):
    trip_id: str
    status: TripStatus
    paid_minor: int
    all_paid: bool


class DemoResultResponse(BaseModel):
    # How many fake members were added / voted / paid.
    affected: int
