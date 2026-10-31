from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CheckDisruptions,
    ExpectAgentMessage,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    Pay,
    Scenario,
    StartBookings,
    SupplierDisruption,
    SupplierSpec,
)
from app.harness.scenarios.common import BARCELONA, FRIENDS, ORGANIZER, UNTIL_BOOKED

SCENARIO = Scenario(
    name="cancelled_flight",
    title="The booked flight is cancelled — rebooked on another airline, 12% dearer",
    description=(
        "Everything is booked when the airline's status feed reports the flight cancelled, with "
        "a re-accommodation on another carrier at +12%. The old booking is cancelled, the "
        "replacement queued, the shares re-split once and everyone tops up; the replacement is "
        "held, bought through the API and the trip is BOOKED again."
    ),
    brief=BARCELONA,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(SupplierSpec("sim_flight"), SupplierSpec("sim_stay"), SupplierSpec("sim_activity")),
    steps=(
        *UNTIL_BOOKED,
        SupplierDisruption("flight", cancelled=True, replacement_percent=12),
        CheckDisruptions(),
        ExpectEvent(EventKind.DISRUPTION),
        ExpectEvent(EventKind.RESPLIT),
        ExpectAgentMessage("Wizz Air"),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(status=ContributionStatus.PENDING, vs_initial="higher"),
        ExpectBookingStatus("flight", BookingStatus.PENDING, count=1),
        Pay(),
        ExpectStatus(TripStatus.REBOOKING),
        StartBookings("flight"),
        Approve("flight"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED, count=1),
        ExpectStatus(TripStatus.BOOKED),
        ExpectShares(status=ContributionStatus.PAID, vs_initial="higher"),
    ),
)
