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
    PayAllShares,
    Scenario,
)
from app.harness.scenarios.common import ORGANIZER, PRAGUE

FRIEND = "Kuba Mazur"

SCENARIO = Scenario(
    name="quick_solo_trip",
    title="One sentence to tickets: quick brief, the organizer pays for everyone, auto-book",
    description=(
        "The organizer types 'Weekend w Pradze dla 2, 20-22.11, do 900 zł/os, pociągiem'; the "
        "trip is created and researched at once. A friend joins, the organizer picks a package "
        "and pays both shares from their wallet (one top-up of the whole shortfall). The "
        "purchases start by themselves, the organizer approves the basket, the trip is BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=(FRIEND,),
    quick_text="Weekend w Pradze dla 2, 20-22.11, do 900 zł/os, pociągiem",
    auto_book=True,
    steps=(
        ExpectStatus(TripStatus.VOTING),
        ExpectEvent(EventKind.PROPOSALS_READY),
        CastVotes({ORGANIZER: 0}),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(status=ContributionStatus.PENDING, members=2),
        PayAllShares(),
        ExpectShares(status=ContributionStatus.PAID, members=2),
        ExpectEvent(EventKind.ALL_PAID),
        ExpectAgentMessage("booking everything now"),
        ExpectBookingStatus("rail", BookingStatus.AWAITING_APPROVAL),
        Approve("all"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
