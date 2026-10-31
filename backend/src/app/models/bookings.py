"""Booking-side documents: what to buy (`Booking`) and each agent attempt at buying it
(`AgentRun`). The run's live artifacts (screenshots, status.json) live on disk under
`AGENT_VAR_DIR/runs/<run_id>/`; the document is the durable record."""

from datetime import datetime
from typing import Any, ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import Field, model_validator

from app.core.domain.trips import (
    AgentOutcome,
    AgentRunStatus,
    BookingKind,
    BookingStatus,
    SupplierChannel,
    TransportMode,
    upgrade_legacy_kind,
)
from app.db.documents import TimestampMixin
from app.models.trust import TrustLink, TrustProvenance

TEXT_MAX_LENGTH = 4000


class Booking(TimestampMixin, Document):
    trip_id: PydanticObjectId
    kind: BookingKind
    # Set for kind=transport only: how it moves (rail / flight / bus / ferry).
    mode: TransportMode | None = None
    title: str = Field(max_length=200)
    # Who the group buys from, for people ("Ryanair", "PKP Intercity", "Booking.com").
    supplier: str = Field(max_length=200)
    # Where the agent starts (channel=agent) or a human books (channel=manual).
    supplier_url: str = Field(max_length=2000)
    # Natural-language goal handed to the agent ("2nd class, 6 passengers, Fri 14:00-18:00").
    goal: str = Field(max_length=TEXT_MAX_LENGTH)
    amount_minor: int = Field(ge=0)
    status: BookingStatus = BookingStatus.PENDING
    current_run_id: str | None = None
    confirmation_ref: str | None = None
    # Set when this booking replaces another one after a disruption.
    replaces_booking_id: PydanticObjectId | None = None
    # Who travels on THIS purchase, in vault order (passenger_1..N). A supplier that caps the
    # party per purchase (`SupplierCapabilities.max_party_per_purchase`) splits one package item
    # into several bookings. Empty on documents created before the split: the whole trip travels.
    passenger_user_ids: list[PydanticObjectId] = Field(default_factory=list)
    # Index of the chosen proposal's item this booking buys (shared by the parts of a split).
    proposal_item_index: int | None = None
    # The supplier plugin (`app.suppliers.registry`) and its identifier of the offer. Empty on
    # documents written before suppliers were plugins: such a booking is bought as before (by
    # the agent at `supplier_url`) and its stored amount is taken as the price.
    supplier_id: str = ""
    offer_ref: str = Field(default="", max_length=TEXT_MAX_LENGTH)
    channel: SupplierChannel = SupplierChannel.AGENT
    # Adapter-owned data handed back on quote/hold/purchase/status. Written by the backend from
    # a supplier answer only — never accepted from a client.
    supplier_data: dict[str, Any] = Field(default_factory=dict)
    hold_ref: str | None = None
    hold_expires_at: datetime | None = None
    # When `amount_minor` was last confirmed by the supplier (a quote or a hold).
    quoted_at: datetime | None = None
    # Trust, copied from the package item (see `app.core.domain.trust`). Backfilled on old
    # documents by migration 20261031_180000_booking_trust.
    links: list[TrustLink] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    provenance: TrustProvenance | None = None

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_kind(cls, data: Any) -> Any:
        return upgrade_legacy_kind(data) if isinstance(data, dict) else data

    class Settings:
        name: ClassVar[str] = "bookings"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("trip_id", 1)], name="ix_bookings_trip_id"),
        ]


class AgentRun(TimestampMixin, Document):
    run_id: str  # directory name under runs/, URL-safe
    booking_id: PydanticObjectId
    trip_id: PydanticObjectId
    status: AgentRunStatus = AgentRunStatus.QUEUED
    outcome: AgentOutcome | None = None
    reason: str = Field(default="", max_length=TEXT_MAX_LENGTH)
    steps: int = 0
    milestone: str | None = None
    stop_before_pay: bool = True
    cost_usd: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Settings:
        name: ClassVar[str] = "agent_runs"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("run_id", 1)], unique=True, name="uq_agent_runs_run_id"),
            pymongo.IndexModel([("booking_id", 1)], name="ix_agent_runs_booking_id"),
            pymongo.IndexModel([("trip_id", 1)], name="ix_agent_runs_trip_id"),
        ]
