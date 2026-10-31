from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectAgentRuns,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectHold,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    SupplierSpec,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="prague_liteapi_live",
    title="Prague with a REAL hotel: LiteAPI sandbox prebook at the vote, book at the approval",
    description=(
        "Six friends, Warszawa -> Praha 20-22 Nov 2026. The stays come from the real LiteAPI "
        "sandbox (hotels, rates for 3 double rooms in PLN). Closing the vote PREBOOKS the "
        "winning hotel (the hold), everyone pays, the train goes to the agent and the stay "
        "waits for the organizer's approval; approving BOOKS it through LiteAPI with the "
        "sandbox test card and the booking carries LiteAPI's booking id. Needs --live-stays; "
        "with --live-search the train is a real PKP Intercity fare too."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(
        SupplierSpec("sim_rail"),
        SupplierSpec("liteapi"),
        SupplierSpec("sim_activity"),
    ),
    live_stays_only=True,
    steps=(
        GeneratePackages(),
        ExpectStatus(TripStatus.VOTING),
        ExpectEvent(EventKind.PROPOSALS_READY),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectEvent(EventKind.HOLD_PLACED),
        ExpectHold("stay"),
        ExpectShares(status=ContributionStatus.PENDING, members=6),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        ExpectBookingStatus("rail", BookingStatus.AWAITING_APPROVAL),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
        Approve("all"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED, count=1),
        ExpectAgentRuns("stay", 0),
        ExpectStatus(TripStatus.BOOKED),
        ExpectShares(status=ContributionStatus.PAID, vs_initial="equal"),
    ),
)
