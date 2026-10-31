"""What the group does at the destination: the attraction candidates they vote on and the
day-by-day plan built from the votes.

Both are one document per trip (unique `trip_id`). The candidates are a snapshot taken at the
first request after the package vote, so the list does not reshuffle while people vote; each
candidate carries its voters. Not tenant-owned, like every trip document: access is trip
membership, checked in the services.
"""

from datetime import date, datetime
from typing import Any, ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field

from app.core.domain.attractions import AttractionKind
from app.core.domain.itinerary import ItemKind
from app.db.documents import TimestampMixin

TITLE_MAX_LENGTH = 200
TEXT_MAX_LENGTH = 2000
URL_MAX_LENGTH = 2000


class AttractionCandidate(BaseModel):
    attraction_id: str = Field(max_length=TITLE_MAX_LENGTH)  # stable within the trip
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    kind: AttractionKind
    image_url: str = Field(default="", max_length=URL_MAX_LENGTH)
    website: str = Field(default="", max_length=URL_MAX_LENGTH)
    lat: float | None = None
    lon: float | None = None
    opens: str | None = None  # "10:00"; None = unknown
    closes: str | None = None
    duration_minutes: int = Field(ge=1)
    # Per person; None = free / pay on site.
    price_per_person_minor: int | None = Field(default=None, ge=0)
    currency: str = "PLN"
    # Tickets can be bought for the group (by the agent or a supplier API).
    bookable: bool = False
    provenance: str = Field(default="", max_length=TITLE_MAX_LENGTH)
    rank: int = 0
    supplier_id: str = ""
    supplier_name: str = Field(default="", max_length=TITLE_MAX_LENGTH)
    offer_ref: str = Field(default="", max_length=TEXT_MAX_LENGTH)
    purchase_url: str = Field(default="", max_length=URL_MAX_LENGTH)
    # Adapter-owned; handed back to the supplier when tickets are bought. Never shown.
    supplier_data: dict[str, Any] = Field(default_factory=dict)
    voter_ids: list[PydanticObjectId] = Field(default_factory=list)


class TripAttractions(TimestampMixin, Document):
    trip_id: PydanticObjectId
    destination: str = Field(default="", max_length=TITLE_MAX_LENGTH)
    candidates: list[AttractionCandidate] = Field(default_factory=list)

    class Settings:
        name: ClassVar[str] = "trip_attractions"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("trip_id", 1)], unique=True, name="uq_trip_attractions_trip"),
            pymongo.IndexModel([("candidates.voter_ids", 1)], name="ix_trip_attractions_voter_ids"),
        ]


class ItineraryEntry(BaseModel):
    start: datetime  # local wall-clock time at the destination
    end: datetime
    kind: ItemKind
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    place: str = Field(default="", max_length=TITLE_MAX_LENGTH)
    lat: float | None = None
    lon: float | None = None
    link: str = Field(default="", max_length=URL_MAX_LENGTH)
    note: str = Field(default="", max_length=TEXT_MAX_LENGTH)
    attraction_id: str | None = None


class ItineraryDay(BaseModel):
    day: date
    items: list[ItineraryEntry] = Field(default_factory=list)


class Itinerary(TimestampMixin, Document):
    trip_id: PydanticObjectId
    days: list[ItineraryDay] = Field(default_factory=list)
    # The votes the plan was built from ("<attraction>:<votes>,..."), to tell a stale plan.
    votes_signature: str = ""
    generated_at: datetime

    class Settings:
        name: ClassVar[str] = "itineraries"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("trip_id", 1)], unique=True, name="uq_itineraries_trip"),
        ]
