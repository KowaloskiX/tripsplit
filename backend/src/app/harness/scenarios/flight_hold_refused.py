from app.core.domain.trips import BookingStatus, ContributionStatus, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectAgentRuns,
    ExpectBookingStatus,
    ExpectHold,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    SupplierSpec,
)
from app.harness.scenarios.common import BARCELONA, FRIENDS, ORGANIZER
from app.suppliers.sim import SimBehaviour

SCENARIO = Scenario(
    name="flight_hold_refused",
    holds=True,
    title="Barcelona by plane: the airline advertises holds but refuses every one",
    description=(
        "HOLDS=on, but the airline API refuses every hold (as Duffel's test Iberia does). "
        "Closing the vote holds only the stay; starting the purchase tries the flight hold "
        "again, falls back to a fresh quote, so the summary carries a binding price and "
        "approving buys the flight directly through the API — no QUOTE_EXPIRED dead end."
    ),
    brief=BARCELONA,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(
        SupplierSpec("sim_flight", SimBehaviour(hold_refused=True)),
        SupplierSpec("sim_stay"),
        SupplierSpec("sim_activity"),
    ),
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectHold("flight", live=False),
        ExpectHold("stay"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("flight"),
        ExpectBookingStatus("flight", BookingStatus.AWAITING_APPROVAL),
        ExpectHold("flight", live=False),
        Approve("flight"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED),
        ExpectAgentRuns("flight", 0),
        StartBookings("stay"),
        Approve("stay"),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
        ExpectShares(status=ContributionStatus.PAID),
    ),
)
