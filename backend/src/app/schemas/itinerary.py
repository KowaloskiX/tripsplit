"""Attraction voting and day-plan schemas — the HTTP contract of "what do we do there".

Output only (the vote toggle takes no body): read models validated `from_attributes` straight
from the services' views.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.core.domain.attractions import AttractionKind, TicketStatus
from app.core.domain.itinerary import ItemKind


class _ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VoterResponse(_ReadModel):
    user_id: str
    display_name: str


class AttractionResponse(_ReadModel):
    attraction_id: str
    title: str
    kind: AttractionKind
    image_url: str
    website: str
    lat: float | None
    lon: float | None
    # Opening hours when the supplier knows them ("10:00"), else null.
    opens: str | None
    closes: str | None
    duration_minutes: int
    # Per person; null = free / pay on site.
    price_per_person_minor: int | None
    currency: str
    # The agent can buy tickets for the group (they join the plan's purchases).
    bookable: bool
    # Where the idea comes from ("Demo ticket shop", "Wikidata / OpenStreetMap").
    provenance: str
    rank: int
    votes: int
    voters: list[VoterResponse]
    voted_by_me: bool


class AttractionsResponse(_ReadModel):
    trip_id: str
    destination: str
    members: int
    # Attractions with at least this many votes are planned first.
    majority: int
    attractions: list[AttractionResponse]


class ItineraryItemResponse(_ReadModel):
    start: str  # "HH:MM", local time at the destination
    end: str
    kind: ItemKind
    title: str
    place: str
    lat: float | None
    lon: float | None
    link: str
    map_url: str
    note: str
    attraction_id: str | None
    # Tickets for this visit, when it needs any: to_buy / buying / booked / needs_help.
    tickets: TicketStatus | None
    booking_id: str | None


class ItineraryDayResponse(_ReadModel):
    date: date
    label: str
    items: list[ItineraryItemResponse]


class ItineraryResponse(_ReadModel):
    trip_id: str
    # null = no plan yet.
    generated_at: datetime | None
    # The votes changed since the plan was made.
    stale: bool
    days: list[ItineraryDayResponse]
