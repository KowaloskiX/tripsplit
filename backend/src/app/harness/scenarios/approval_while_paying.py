from app.core.domain.trips import BookingStatus, TripStatus
from app.harness.scenario import (
    Approve,
    Disrupt,
    ExpectBookingStatus,
    ExpectError,
    ExpectStatus,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_PAID

SCENARIO = Scenario(
    name="approval_while_paying",
    title="A dearer disruption mid-booking must freeze the other purchases",
    description=(
        "The train is bought while the stay's summary waits for approval. The train is then "
        "delayed and its replacement is 20% dearer, so the trip is back in PAYING with top-ups "
        "owed. Approving the stay now would spend money nobody has fully paid — Rule #1 says the "
        "approval must be refused until the top-ups are in."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_PAID,
        StartBookings("all"),
        Approve("train"),
        ExpectBookingStatus("train", BookingStatus.CONFIRMED),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
        Disrupt(delay_minutes=140, price_change_percent=20),
        ExpectStatus(TripStatus.PAYING),
        ExpectError("trip_not_ready"),
        Approve("stay"),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
    ),
    xfail=(
        "BookingService.approve checks only the booking status, not the trip status or the "
        "shares: the stay is approved and CONFIRMED while the trip is PAYING (Rule #1 broken)"
    ),
)
