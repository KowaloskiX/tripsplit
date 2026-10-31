from app.core.domain.trips import BookingStatus, TripStatus
from app.harness.scenario import (
    Approve,
    Disrupt,
    ExpectBookingStatus,
    ExpectError,
    ExpectStatus,
    Pay,
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
        "owed. Approving the stay now would spend money nobody has fully paid — Rule #1 refuses "
        "it and the stay's run keeps waiting; after the top-ups the trip is REBOOKING, the stay "
        "is approved, the replacement train bought and the trip ends BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_PAID,
        StartBookings("all"),
        Approve("rail"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED, count=2),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
        Disrupt(delay_minutes=140, price_change_percent=20),
        ExpectStatus(TripStatus.PAYING),
        ExpectError("trip_not_ready"),
        Approve("stay"),
        ExpectBookingStatus("stay", BookingStatus.AWAITING_APPROVAL),
        Pay(),
        ExpectStatus(TripStatus.REBOOKING),
        Approve("stay"),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED),
        StartBookings("rail"),
        Approve("rail"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED, count=2),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
