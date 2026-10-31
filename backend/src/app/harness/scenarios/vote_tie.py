from app.core.domain.trips import BookingStatus, ContributionStatus, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectBookingStatus,
    ExpectShares,
    ExpectStatus,
    ExpectWinner,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="vote_tie",
    title="A 3/3 vote between comfort and splurge — the earlier package wins",
    description=(
        "Three vote the comfort package (#1), three the splurge (#2). The tie goes to the "
        "earliest package, and the split, bookings and payments follow #1."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        CastVotes(
            {
                ORGANIZER: 2,
                FRIENDS[0]: 1,
                FRIENDS[1]: 2,
                FRIENDS[2]: 1,
                FRIENDS[3]: 2,
                FRIENDS[4]: 1,
            }
        ),
        CloseVoting(),
        ExpectWinner(1),
        ExpectShares(status=ContributionStatus.PENDING, members=6),
        Pay(),
        StartBookings("all"),
        Approve("all"),
        ExpectBookingStatus("activity", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
