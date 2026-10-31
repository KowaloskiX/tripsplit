from app.core.domain.trips import BookingStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    EnterTravellerDetails,
    ExpectAgentMessage,
    ExpectBookingStatus,
    ExpectError,
    ExpectEvent,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    SupplierSpec,
)
from app.harness.scenarios.common import BARCELONA, FRIENDS, ORGANIZER

MISSING = (FRIENDS[0], FRIENDS[1])

SCENARIO = Scenario(
    name="flight_needs_passport",
    title="An international flight needs passports — two friends have not entered theirs",
    description=(
        "The airline requires full name, date of birth, nationality and document number for "
        "every passenger. Two friends never entered their details: starting the purchase is "
        "refused with `traveller_details_missing` and the feed names them and the missing "
        "fields — never a value. Once they fill in their details the purchase goes ahead."
    ),
    brief=BARCELONA,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(SupplierSpec("sim_flight"), SupplierSpec("sim_stay")),
    without_traveller_details=MISSING,
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        ExpectError("traveller_details_missing"),
        StartBookings("flight"),
        ExpectEvent(EventKind.TRAVELLER_DETAILS_MISSING),
        ExpectAgentMessage(f"{MISSING[0]} (date of birth, document number, nationality)"),
        ExpectAgentMessage(MISSING[1]),
        ExpectBookingStatus("flight", BookingStatus.PENDING),
        EnterTravellerDetails(MISSING),
        StartBookings("flight"),
        ExpectBookingStatus("flight", BookingStatus.AWAITING_APPROVAL),
        Approve("flight"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED),
        StartBookings("stay"),
        Approve("stay"),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
