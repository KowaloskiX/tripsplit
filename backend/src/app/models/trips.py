"""Trip-side documents: the trip, its members, proposals, votes, contributions and the feed.

Trips are NOT tenant-owned: friends from different organizations join one trip through an
invite link. Access control is trip membership (`TripMember`), checked in the services.
"""

from datetime import date, datetime
from typing import Any, ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field, model_validator

from app.core.domain.trips import (
    MAX_TRANSFERS_LIMIT,
    BookingKind,
    ContributionStatus,
    EventActor,
    EventKind,
    MemberRole,
    TransportMode,
    TripStatus,
    upgrade_legacy_kind,
)
from app.db.documents import TimestampMixin
from app.models.trust import TrustLink, TrustProvenance

TITLE_MAX_LENGTH = 120
TEXT_MAX_LENGTH = 4000


class Trip(TimestampMixin, Document):
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    origin: str = Field(max_length=TITLE_MAX_LENGTH)  # e.g. "Warszawa"
    # Free-text brief: "weekend in Prague, cheap, good food" — the AI turns it into packages.
    brief: str = Field(default="", max_length=TEXT_MAX_LENGTH)
    date_from: date
    date_to: date
    group_size: int = Field(ge=1, le=20)
    budget_per_person_minor: int | None = None
    currency: str = "PLN"
    # Where to: "Barcelona". Empty = the researcher reads it from the title and brief.
    destination: str = Field(default="", max_length=TITLE_MAX_LENGTH)
    # How the group wants to travel; None = any mode the enabled suppliers offer.
    transport_mode: TransportMode | None = None
    # Simple transport preferences (see `TravelPreferences`); None = no preference.
    earliest_departure_hour: int | None = Field(default=None, ge=0, le=23)
    max_transfers: int | None = Field(default=None, ge=0, le=MAX_TRANSFERS_LIMIT)
    status: TripStatus = TripStatus.COLLECTING
    organizer_id: PydanticObjectId
    invite_code: str
    chosen_proposal_id: PydanticObjectId | None = None
    # The amount the group is paying right now (sum of bookings of the chosen package).
    total_minor: int = 0
    # The trip escrow wallet at the payment partner ("wlt_…"), opened at voting close.
    escrow_wallet_id: str | None = None
    # The funding deadline: not 100% paid by then, the escrow refunds everyone (EXPIRED).
    pay_by: datetime | None = None

    class Settings:
        name: ClassVar[str] = "trips"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("invite_code", 1)], unique=True, name="uq_trips_invite_code"),
            pymongo.IndexModel([("organizer_id", 1)], name="ix_trips_organizer_id"),
            # The funding-deadline sweep: PAYING trips whose `pay_by` has passed.
            pymongo.IndexModel([("status", 1), ("pay_by", 1)], name="ix_trips_status_pay_by"),
        ]


class TripMember(TimestampMixin, Document):
    trip_id: PydanticObjectId
    user_id: PydanticObjectId
    display_name: str = Field(max_length=TITLE_MAX_LENGTH)
    role: MemberRole = MemberRole.MEMBER

    class Settings:
        name: ClassVar[str] = "trip_members"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel(
                [("trip_id", 1), ("user_id", 1)], unique=True, name="uq_trip_members_trip_user"
            ),
            pymongo.IndexModel([("user_id", 1)], name="ix_trip_members_user_id"),
        ]


class TransportSegment(BaseModel):
    """One leg of a transport item: a flight, a train, a bus ride."""

    carrier: str = Field(max_length=TITLE_MAX_LENGTH)
    number: str = Field(max_length=TITLE_MAX_LENGTH)
    origin: str = Field(max_length=TITLE_MAX_LENGTH)
    destination: str = Field(max_length=TITLE_MAX_LENGTH)
    departs_at: datetime
    arrives_at: datetime


class ProposalItem(BaseModel):
    """One purchasable part of a package — becomes a `Booking` when the package wins."""

    kind: BookingKind
    mode: TransportMode | None = None  # transport only
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    supplier: str = Field(max_length=TITLE_MAX_LENGTH)  # who sells it: "Ryanair", "Booking.com"
    supplier_url: str = Field(max_length=2000)
    price_minor: int = Field(ge=0)  # for the WHOLE group
    details: str = Field(default="", max_length=TEXT_MAX_LENGTH)  # times, room type, ...
    starts_at: datetime | None = None
    # The supplier plugin and its offer; empty for an item researched outside the registry.
    supplier_id: str = ""
    offer_ref: str = Field(default="", max_length=TEXT_MAX_LENGTH)
    segments: list[TransportSegment] = Field(default_factory=list)
    refundable: bool = False
    # Adapter-owned (see `Booking.supplier_data`); never shown to or accepted from a client.
    supplier_data: dict[str, Any] = Field(default_factory=dict)
    # Trust (see `app.core.domain.trust`); empty on items researched before it existed.
    links: list[TrustLink] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    provenance: TrustProvenance | None = None

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_kind(cls, data: Any) -> Any:
        return upgrade_legacy_kind(data) if isinstance(data, dict) else data


class Proposal(TimestampMixin, Document):
    trip_id: PydanticObjectId
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    summary: str = Field(default="", max_length=TEXT_MAX_LENGTH)
    items: list[ProposalItem] = Field(default_factory=list)
    total_minor: int = Field(ge=0)
    per_person_minor: int = Field(ge=0)
    # Costs more per person than the brief's budget (False when the brief has none).
    over_budget: bool = False
    image_url: str | None = None

    class Settings:
        name: ClassVar[str] = "proposals"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("trip_id", 1)], name="ix_proposals_trip_id"),
        ]


class TripOption(BaseModel):
    """One pickable option of a research: a transport (one item, or out + back), a stay or an
    activity. `option_id` is stable within one research ("t0", "s2", "a1")."""

    option_id: str = Field(max_length=16)
    items: list[ProposalItem] = Field(default_factory=list)


class TripOptions(TimestampMixin, Document):
    """Every candidate the latest research considered — the chat flow picks from these one
    step at a time and builds its own package (`ProposalService.select`). Replaced by each
    research, next to the proposals."""

    trip_id: PydanticObjectId
    transport: list[TripOption] = Field(default_factory=list)
    stays: list[TripOption] = Field(default_factory=list)
    activities: list[TripOption] = Field(default_factory=list)

    class Settings:
        name: ClassVar[str] = "trip_options"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("trip_id", 1)], unique=True, name="uq_trip_options_trip_id"),
        ]


class Vote(TimestampMixin, Document):
    trip_id: PydanticObjectId
    proposal_id: PydanticObjectId
    user_id: PydanticObjectId

    class Settings:
        name: ClassVar[str] = "votes"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            # One vote per member per trip; changing your mind overwrites it.
            pymongo.IndexModel(
                [("trip_id", 1), ("user_id", 1)], unique=True, name="uq_votes_trip_user"
            ),
            pymongo.IndexModel([("user_id", 1)], name="ix_votes_user_id"),
        ]


class Contribution(TimestampMixin, Document):
    """A member's share. `amount_minor` can change after a re-split; `paid_minor` only grows
    (or is reduced by an explicit refund)."""

    trip_id: PydanticObjectId
    user_id: PydanticObjectId
    amount_minor: int = Field(ge=0)
    paid_minor: int = Field(default=0, ge=0)
    status: ContributionStatus = ContributionStatus.PENDING
    # Reference at the payment provider (FakePayments: "fake_..."; Stripe later: session id).
    provider_ref: str | None = None
    paid_at: datetime | None = None

    class Settings:
        name: ClassVar[str] = "contributions"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel(
                [("trip_id", 1), ("user_id", 1)], unique=True, name="uq_contributions_trip_user"
            ),
            pymongo.IndexModel([("user_id", 1)], name="ix_contributions_user_id"),
        ]


class TripEvent(Document):
    """The group feed: everything members say and everything the agent does, in order."""

    trip_id: PydanticObjectId
    kind: EventKind
    actor: EventActor
    message: str = Field(max_length=TEXT_MAX_LENGTH)
    # Small structured extras for the UI (proposal id, booking id, amounts). Written by our
    # services only — never accepted from a client as-is.
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_user_id: PydanticObjectId | None = None
    created_at: datetime

    class Settings:
        name: ClassVar[str] = "trip_events"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("trip_id", 1), ("created_at", 1)], name="ix_trip_events_feed"),
        ]
