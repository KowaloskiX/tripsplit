"""Registry of documents handed to `init_beanie`.

A separate module, because Beanie has to know ALL models at initialization time, while
`app.db` must not import `app.models` (the layer contract in `.importlinter`). A new document
has to be added here — otherwise queries against it fail with `CollectionWasNotInitialized`.
"""

from typing import Any

from app.models.auth import User, UserSession
from app.models.bookings import AgentRun, Booking
from app.models.organizations import Membership, Organization
from app.models.travellers import TravellerProfile
from app.models.trips import Contribution, Proposal, Trip, TripEvent, TripMember, Vote

DOCUMENT_MODELS: tuple[type[Any], ...] = (
    User,
    UserSession,
    Organization,
    Membership,
    Trip,
    TripMember,
    Proposal,
    Vote,
    Contribution,
    TripEvent,
    Booking,
    AgentRun,
    TravellerProfile,
)
