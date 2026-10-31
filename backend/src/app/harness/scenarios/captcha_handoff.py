from app.core.domain.trips import BookingStatus, TripStatus
from app.harness.scenario import (
    AgentOutcome,
    Approve,
    CompleteManually,
    ExpectBookingStatus,
    ExpectStatus,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_PAID

SCENARIO = Scenario(
    name="captcha_handoff",
    title="A CAPTCHA stops the agent on the stay — the organizer finishes by hand",
    description=(
        "The train goes through; the stay's agent hits a CAPTCHA and hands off. The organizer "
        "books it manually and records the supplier reference -> CONFIRMED, trip BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_PAID,
        AgentOutcome(stay="handoff"),
        StartBookings("all"),
        ExpectBookingStatus("stay", BookingStatus.HANDOFF),
        ExpectBookingStatus("train", BookingStatus.AWAITING_APPROVAL),
        Approve("train"),
        ExpectStatus(TripStatus.BOOKING),
        CompleteManually("stay", ref="BKG-4711"),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
