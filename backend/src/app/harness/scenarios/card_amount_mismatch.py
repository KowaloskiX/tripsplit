from app.core.domain.escrow import CardStatus, PurchasePayment
from app.core.domain.trips import BookingStatus, TripStatus
from app.harness.scenario import (
    Approve,
    CompleteManually,
    ExpectAgentMessage,
    ExpectBookingStatus,
    ExpectEscrow,
    ExpectPayment,
    ExpectStatus,
    Scenario,
    SiteAsksMore,
    StartBookings,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE, UNTIL_PAID

SCENARIO = Scenario(
    name="card_amount_mismatch",
    title="The site asks more than the virtual card allows — declined, handed to a human",
    description=(
        "The agent's single-use card is limited to exactly the approved purchase amount (+0%). "
        "At checkout the stay site suddenly charges 5% more: the card network declines, nothing "
        "is paid, the card closes and its reserve returns to the escrow, and the booking is "
        "handed off. The organizer settles it by hand; the escrow pays the supplier by payout."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        *UNTIL_PAID,
        SiteAsksMore("stay", 5),
        StartBookings("all"),
        Approve("all"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED, count=2),
        ExpectBookingStatus("stay", BookingStatus.HANDOFF),
        ExpectPayment("stay", PurchasePayment.VIRTUAL_CARD, CardStatus.CLOSED),
        ExpectPayment("rail", PurchasePayment.VIRTUAL_CARD, CardStatus.USED),
        ExpectAgentMessage("declined the virtual card"),
        ExpectStatus(TripStatus.BOOKING),
        ExpectEscrow(refunded_minor=0),
        CompleteManually("stay", "BK-HAND-42"),
        ExpectPayment("stay", PurchasePayment.PAYOUT),
        ExpectStatus(TripStatus.BOOKED),
        ExpectEscrow(held_minor=0),
    ),
)
