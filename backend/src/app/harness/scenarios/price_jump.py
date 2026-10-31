from app.core.domain.trips import ContributionStatus, TripStatus
from app.harness.scenario import (
    Approve,
    ExpectError,
    ExpectEvent,
    ExpectShares,
    ExpectStatus,
    Pay,
    Scenario,
    StartBookings,
    SupplierPriceChange,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_PAID

SCENARIO = Scenario(
    name="price_jump",
    title="The train got 15% dearer between the vote and the purchase",
    description=(
        "Everyone has paid, then PKP's live price rises 15%. Starting the train booking must "
        "re-quote, fail with `price_changed`, re-split and send the trip back to PAYING with a "
        "top-up for everyone; after the top-ups the booking proceeds."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_PAID,
        SupplierPriceChange("train", 15),
        ExpectError("price_changed"),
        StartBookings("train"),
        ExpectStatus(TripStatus.PAYING),
        ExpectEvent("price_changed"),
        ExpectShares(status=ContributionStatus.PENDING, vs_initial="higher"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        Approve("all"),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
