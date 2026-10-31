from app.core.domain.trips import BookingStatus, EventKind, TripStatus
from app.harness.scenario import (
    AdvanceClock,
    Approve,
    CastVotes,
    CloseVoting,
    EnterTravellerDetails,
    ExpectBookingStatus,
    ExpectError,
    ExpectEvent,
    ExpectHold,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.barcelona_duffel_live import (
    AIRLINE_REPRICE_TOLERANCE,
    BARCELONA_WEEKEND,
    DUFFEL_TRIP,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER

LATE = (FRIENDS[2], FRIENDS[4])

SCENARIO = Scenario(
    name="barcelona_duffel_slow_group",
    holds=True,
    title="A slow group on REAL airline offers: the Duffel offer expires, the flights are re-found",
    description=(
        "Same Barcelona weekend on Duffel's test API, but the group takes over an hour to vote "
        "and two friends have not entered their traveller details. Duffel offers live ~30 "
        "minutes, and an airline hold names every passenger, so no flight hold is placed at "
        "close (the stay is held). Starting the purchase is refused until the two add their "
        "details; then the adapter re-finds the same flights with a fresh search, holds them, "
        "and the approval pays the held order. Runs only with --live-flights."
    ),
    brief=BARCELONA_WEEKEND,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=DUFFEL_TRIP,
    without_traveller_details=LATE,
    live_flights_only=True,
    price_tolerance_percent=AIRLINE_REPRICE_TOLERANCE,
    steps=(
        GeneratePackages(),
        CastVotes(0),
        AdvanceClock(hours=1.5),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectHold("flight", live=False),
        ExpectHold("stay"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        ExpectError("traveller_details_missing"),
        StartBookings("flight"),
        ExpectEvent(EventKind.TRAVELLER_DETAILS_MISSING),
        EnterTravellerDetails(LATE),
        StartBookings("flight", top_up_on_price_change=True),
        ExpectEvent(EventKind.HOLD_PLACED),
        ExpectHold("flight"),
        ExpectBookingStatus("flight", BookingStatus.AWAITING_APPROVAL),
        Approve("flight"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED, count=1),
        StartBookings("stay"),
        Approve("stay"),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
