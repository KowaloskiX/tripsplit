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
        "After everything is booked the train is delayed 140 minutes. The old ticket is "
        "cancelled, a replacement 10% cheaper is queued, shares are re-split and everyone is "
        "owed a refund; the replacement is bought and the trip is BOOKED again."
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
        ExpectBookingStatus("train", BookingStatus.PENDING),
        StartBookings("train"),
        Approve("train"),
        ExpectBookingStatus("train", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
    ),
    known_violations={
        "refunds_settled_when_booked": (
            "product gap: PaymentProvider has no refund operation and nothing pays REFUND_DUE "
            "back, so the cheaper rebooking leaves the overpayment with the trip forever"
        ),
    },
)
