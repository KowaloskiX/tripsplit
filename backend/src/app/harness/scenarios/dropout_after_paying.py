from app.core.domain.trips import ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    Leave,
    Pay,
    Scenario,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_PAID

LEAVER = "Tomek Dudek"

SCENARIO = Scenario(
    name="dropout_after_paying",
    title="A friend drops out after paying, before anything is bought",
    description=(
        "Everyone has paid (the trip is BOOKING); one friend leaves before the agent starts. "
        "The five who stay are re-split (each owes a top-up, the trip goes back to PAYING), the "
        "leaver's share drops to zero and their payment becomes a refund, paid out once the "
        "trip is booked."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_PAID,
        Leave(LEAVER),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(
            status=ContributionStatus.PENDING,
            per_member={LEAVER: ContributionStatus.REFUND_DUE},
            members=5,
            vs_initial="higher",
        ),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        Approve("all"),
        ExpectStatus(TripStatus.BOOKED),
        ExpectEvent(EventKind.REFUND_ISSUED),
        ExpectShares(status=ContributionStatus.PAID, members=5),
    ),
)
