from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    Disrupt,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_BOOKED

SCENARIO = Scenario(
    name="delayed_train",
    title="The booked train is delayed 140 min — a cheaper replacement",
    description=(
        "After everything is booked the train is delayed 140 minutes. Both purchases of the "
        "train (3 + 3 passengers) are cancelled, a replacement 10% cheaper is queued for each, "
        "shares are re-split once and everyone is owed a refund; the replacements are bought, "
        "the trip is BOOKED again and the overpayments are refunded."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_BOOKED,
        Disrupt(delay_minutes=140, price_change_percent=-10),
        ExpectStatus(TripStatus.REBOOKING),
        ExpectEvent(EventKind.DISRUPTION),
        ExpectEvent(EventKind.RESPLIT),
        ExpectShares(status=ContributionStatus.REFUND_DUE, vs_initial="lower"),
        ExpectBookingStatus("train", BookingStatus.PENDING, count=2),
        StartBookings("train"),
        Approve("train"),
        ExpectBookingStatus("train", BookingStatus.CONFIRMED, count=2),
        ExpectStatus(TripStatus.BOOKED),
        ExpectEvent(EventKind.REFUND_ISSUED),
        ExpectShares(status=ContributionStatus.PAID, vs_initial="lower"),
    ),
)
