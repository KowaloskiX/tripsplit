from app.core.domain.trips import BookingStatus, EventKind, TripStatus
from app.harness.scenario import (
    AgentOutcome,
    Approve,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectStatus,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_PAID

SCENARIO = Scenario(
    name="agent_stuck_retry",
    title="The train agent gets stuck — a retry books it",
    description=(
        "The first train run gets stuck (FAILED, feed says why); the organizer retries, the "
        "second run reaches the summary, is approved and the trip ends BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_PAID,
        AgentOutcome("rail", "stuck"),
        StartBookings("all"),
        ExpectBookingStatus("rail", BookingStatus.FAILED),
        ExpectEvent(EventKind.BOOKING_FAILED),
        ExpectStatus(TripStatus.BOOKING),
        AgentOutcome("rail", "done"),
        StartBookings("rail"),
        Approve("all"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
