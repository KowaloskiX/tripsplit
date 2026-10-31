from app.core.domain.trips import ContributionStatus, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectError,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

LATE = "Tomek Dudek"

SCENARIO = Scenario(
    name="missing_payment",
    title="One friend has not paid — Rule #1 holds the agent back",
    description=(
        "Five of six pay. Starting the bookings must fail with `trip_not_ready`; once the last "
        "friend pays, the bookings start and finish."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        Pay(everyone_except=[LATE]),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(status=ContributionStatus.PAID, per_member={LATE: ContributionStatus.PENDING}),
        ExpectError("trip_not_ready"),
        StartBookings("all"),
        Pay(members=[LATE]),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        Approve("all"),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
