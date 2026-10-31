from datetime import timedelta

from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    AdvanceClock,
    Approve,
    CastVotes,
    CloseVoting,
    ExpectAgentRuns,
    ExpectBookingStatus,
    ExpectError,
    ExpectEvent,
    ExpectHold,
    ExpectPurchases,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    SupplierPriceChange,
    SupplierSpec,
)
from app.harness.scenarios.common import BARCELONA, FRIENDS, ORGANIZER
from app.suppliers.sim import SimBehaviour

LATE = FRIENDS[-1]

SCENARIO = Scenario(
    name="barcelona_flight_hold",
    holds=True,
    title="Barcelona by plane: the fare hold lapses while one friend pays late",
    description=(
        "Six friends fly Warszawa -> Barcelona. When the vote closes the airline API holds the "
        "fare for 24 h and the hotel prebook holds the stay for 72 h. One friend pays a day "
        "late: the flight hold has expired, the re-hold comes back 8% dearer (HOLD_EXPIRED -> "
        "PRICE_CHANGED), everyone tops up, and the flight is bought through the API after the "
        "approval — no agent run. The stay is bought on its still-live hold."
    ),
    brief=BARCELONA,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(
        SupplierSpec("sim_flight", SimBehaviour(hold_ttl=timedelta(hours=24))),
        SupplierSpec("sim_stay"),
        SupplierSpec("sim_activity"),
    ),
    steps=(
        GeneratePackages(),
        ExpectStatus(TripStatus.VOTING),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectPurchases("flight", (6,)),
        ExpectEvent(EventKind.HOLD_PLACED),
        ExpectHold("flight"),
        ExpectHold("stay"),
        Pay(everyone_except=[LATE]),
        ExpectStatus(TripStatus.PAYING),
        AdvanceClock(hours=25),
        ExpectHold("flight", live=False),
        ExpectHold("stay"),
        SupplierPriceChange("flight", 8),
        Pay(members=[LATE]),
        ExpectStatus(TripStatus.BOOKING),
        ExpectError("price_changed"),
        StartBookings("flight"),
        ExpectEvent(EventKind.HOLD_EXPIRED),
        ExpectEvent(EventKind.PRICE_CHANGED),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(status=ContributionStatus.PENDING, vs_initial="higher"),
        ExpectHold("flight"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        ExpectBookingStatus("flight", BookingStatus.AWAITING_APPROVAL),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
        Approve("all"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED, count=1),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED),
        ExpectAgentRuns("flight", 0),
        ExpectStatus(TripStatus.BOOKED),
        ExpectShares(status=ContributionStatus.PAID, vs_initial="higher"),
    ),
)
