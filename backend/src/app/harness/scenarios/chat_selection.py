from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    ExpectAgentMessage,
    ExpectBookingStatus,
    ExpectError,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    PayAllShares,
    Scenario,
    SelectOptions,
    StartBookings,
)
from app.harness.scenarios.common import ORGANIZER, PRAGUE

FRIEND = "Kuba Mazur"

SCENARIO = Scenario(
    name="chat_selection",
    title="The chat flow: pick transport, stay and an activity step by step, pay for everyone",
    description=(
        "The organizer types one sentence; the research finishes and its options are listed. "
        "Instead of a group vote, the organizer picks the dearest way to go, the cheapest stay "
        "and one activity: the picks become one package, chosen and split at once. Rule #1 "
        "holds (nothing is bought before every share is paid); the organizer pays both shares, "
        "the purchases start by themselves, the basket is approved and the trip is BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=(FRIEND,),
    quick_text="Weekend w Pradze dla 2, 20-22.11, do 900 zł/os, pociągiem",
    auto_book=True,
    steps=(
        ExpectStatus(TripStatus.VOTING),
        ExpectEvent(EventKind.PROPOSALS_READY),
        SelectOptions(transport=-1, stay=0, activities=(0,)),
        ExpectStatus(TripStatus.PAYING),
        ExpectEvent(EventKind.PROPOSAL_CHOSEN),
        ExpectShares(status=ContributionStatus.PENDING, members=2),
        # Rule #1: a picked package is still bought only once everyone has paid.
        ExpectError("trip_not_ready"),
        StartBookings("all"),
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
