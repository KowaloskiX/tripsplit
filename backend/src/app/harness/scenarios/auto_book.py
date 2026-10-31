from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectAgentMessage,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="auto_book",
    title="AUTO_BOOK: the last payment starts every purchase, the organizer approves once",
    description=(
        "Six friends pay their shares; the moment the last one pays, the train and the hostel "
        "start on their own (no 'Book everything' click). The organizer approves the basket "
        "once and the trip is BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    auto_book=True,
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        Pay(everyone_except=[FRIENDS[-1]]),
        ExpectStatus(TripStatus.PAYING),
        ExpectBookingStatus("rail", BookingStatus.PENDING),
        Pay([FRIENDS[-1]]),
        ExpectEvent(EventKind.ALL_PAID),
        ExpectAgentMessage("booking everything now"),
        ExpectBookingStatus("rail", BookingStatus.AWAITING_APPROVAL),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
        Approve("all"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
        ExpectShares(status=ContributionStatus.PAID, vs_initial="equal"),
    ),
)
