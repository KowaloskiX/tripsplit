from app.core.domain.trips import BookingStatus, ContributionStatus, TripStatus
from app.harness.scenario import (
    Approve,
    Disrupt,
    ExpectBookingStatus,
    ExpectShares,
    ExpectStatus,
    Pay,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_BOOKED

SCENARIO = Scenario(
    name="dearer_rebooking",
    title="The booked train is delayed and the replacement is 20% dearer",
    description=(
        "After everything is booked the train is delayed; the replacement costs 20% more. "
        "Everyone owes a top-up (PAYING); once paid, the trip should be REBOOKING (the agent "
        "buys the replacement) and end BOOKED."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_BOOKED,
        Disrupt(delay_minutes=140, price_change_percent=20),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(status=ContributionStatus.PENDING, vs_initial="higher"),
        Pay(),
        ExpectStatus(TripStatus.REBOOKING),
        StartBookings("train"),
        Approve("train"),
        ExpectBookingStatus("train", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
    ),
    xfail=(
        "after the top-ups ContributionService moves PAYING -> BOOKING (it knows no other "
        "transition), so a rebooking in progress is indistinguishable from a first booking"
    ),
)
