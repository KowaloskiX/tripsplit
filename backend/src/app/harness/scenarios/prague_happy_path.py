from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="prague_happy_path",
    title="Six friends, Warszawa -> Praha, everything goes right",
    description=(
        "Generate, everyone votes the budget package, close, everyone pays, the agent books the "
        "train and the hostel, the organizer approves both, the trip is BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        ExpectStatus(TripStatus.VOTING),
        ExpectEvent(EventKind.PROPOSALS_READY),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(status=ContributionStatus.PENDING, members=6),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        ExpectEvent(EventKind.ALL_PAID),
        StartBookings("all"),
        ExpectBookingStatus("rail", BookingStatus.AWAITING_APPROVAL),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
        Approve("all"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
        ExpectShares(status=ContributionStatus.PAID, vs_initial="equal"),
    ),
)
