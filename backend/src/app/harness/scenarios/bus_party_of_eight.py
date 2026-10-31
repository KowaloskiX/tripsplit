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
    SupplierSpec,
)
from app.harness.scenarios.common import EIGHT_FRIENDS, ORGANIZER, budapest

SCENARIO = Scenario(
    name="bus_party_of_eight",
    title="Eight friends by coach Kraków -> Budapest: one purchase (cap 9)",
    description=(
        "The coach site sells up to nine seats per purchase, so eight friends are ONE booking "
        "and one agent run — the split comes from the supplier's capabilities, not from its "
        "name. Contrast: `rail_party_of_eight` (cap 5 -> 4 + 4)."
    ),
    brief=budapest(TransportMode.BUS),
    organizer=ORGANIZER,
    friends=EIGHT_FRIENDS[:7],
    suppliers=(
        SupplierSpec("sim_bus"),
        SupplierSpec("sim_stay_site"),
        SupplierSpec("sim_activity"),
    ),
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectPurchases("bus", (8,)),
        Pay(),
        StartBookings("all"),
        Approve("all"),
        ExpectBookingStatus("bus", BookingStatus.CONFIRMED, count=1),
        ExpectAgentRuns("bus", 1),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
