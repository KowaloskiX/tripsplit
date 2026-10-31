"""Demo director and six-phone grid schemas (dev/test only routes)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.domain.demo_director import DirectorPace, DirectorPhase, DirectorScript, DirectorState
from app.core.domain.trips import TripStatus
from app.schemas.common import StrictRequest


class DirectorRequest(StrictRequest):
    script: DirectorScript = DirectorScript.FULL
    pace: DirectorPace = DirectorPace.STAGE
    # True: every friend pays, the organizer's share is left for the presenter to pay on stage.
    leave_organizer_payment: bool = False
    # The `full` script only: end with a delayed train, rebooked and topped up.
    with_disruption: bool = True


class _ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DirectorFeaturesResponse(_ReadModel):
    auto_book: bool
    wallet: bool


class DirectorBeatResponse(_ReadModel):
    at: datetime
    phase: DirectorPhase
    actor: str
    text: str


class DirectorProgressResponse(_ReadModel):
    trip_id: str
    script: DirectorScript
    pace: DirectorPace
    state: DirectorState
    phase: DirectorPhase
    features: DirectorFeaturesResponse
    beats: list[DirectorBeatResponse]
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class PhoneResponse(_ReadModel):
    user_id: str
    name: str
    initials: str
    is_organizer: bool
    is_demo: bool  # a seeded friend
    last_message: str | None
    voted_for_proposal_id: str | None
    voted_for_title: str | None
    paid: bool
    amount_minor: int | None  # None before the vote closes (no shares yet)
    paid_minor: int
    currency: str


class PhonesResponse(_ReadModel):
    trip_id: str
    status: TripStatus
    phones: list[PhoneResponse]
