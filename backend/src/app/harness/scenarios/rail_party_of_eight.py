from app.core.domain.trips import BookingStatus, TransportMode, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectAgentRuns,
    ExpectBookingStatus,
    ExpectPurchases,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import EIGHT_FRIENDS, ORGANIZER, budapest

SCENARIO = Scenario(
    name="rail_party_of_eight",
    title="The same eight friends by rail: two purchases of four (cap 5)",
    description=(
        "The rail carrier sells at most five passengers per online purchase, so the same "
        "party of eight becomes two bookings of four, bought by two agent runs; the price is "
        "split per passenger so both parts sum exactly to the item."
    ),
    brief=budapest(TransportMode.RAIL),
    organizer=ORGANIZER,
    friends=EIGHT_FRIENDS[:7],
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectPurchases("rail", (4, 4)),
        Pay(),
        StartBookings("all"),
        Approve("all"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED, count=2),
        ExpectAgentRuns("rail", 2),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
