"""Booking-side documents: what to buy (`Booking`) and each agent attempt at buying it
(`AgentRun`). The run's live artifacts (screenshots, status.json) live on disk under
`AGENT_VAR_DIR/runs/<run_id>/`; the document is the durable record."""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field

from app.core.domain.trips import AgentOutcome, AgentRunStatus, BookingKind, BookingStatus
from app.db.documents import TimestampMixin

TEXT_MAX_LENGTH = 4000


class TrainQuery(BaseModel):
    """What it takes to re-quote a PKP Intercity booking (see `app.suppliers.quotes`).

    Optional: set only when the booking was built from a real PKP quote. Without it the
    booking's stored amount is taken as current.
    """

    from_code: int  # PKP station codes (`Station.code`)
    to_code: int
    departs_at: datetime  # departure of the first leg, local time as PKP reports it
    train_number: int  # number of the first leg, e.g. 131 for "EC 131"
    travel_class: int = 2
    refundable: bool = False


class Booking(TimestampMixin, Document):
    trip_id: PydanticObjectId
    kind: BookingKind
    title: str = Field(max_length=200)
    supplier: str = Field(max_length=200)
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
    # party per purchase (see `purchase_cap`) splits one package item into several bookings.
    # Empty on documents created before the split existed: then the whole trip travels.
    passenger_user_ids: list[PydanticObjectId] = Field(default_factory=list)
    # Index of the chosen proposal's item this booking buys (shared by the parts of a split).
    proposal_item_index: int | None = None
    train_query: TrainQuery | None = None

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
