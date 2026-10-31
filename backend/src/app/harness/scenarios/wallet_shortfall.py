from app.core.domain.trips import BookingStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    Disrupt,
    ExpectBookingStatus,
    ExpectError,
    ExpectEvent,
    ExpectPot,
    ExpectStatus,
    ExpectWallet,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    TopUp,
    TopUpAndPay,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

KUBA = "Kuba Mazur"

SCENARIO = Scenario(
    name="wallet_shortfall",
    title="A wallet short of the share — top up the difference and pay",
    description=(
        "Shares are paid from members' wallets. Kuba has only 50 zł in his: paying from the "
        "wallet fails with `insufficient_funds` and nothing moves. His bank declines the first "
        "BLIK; the second tops up exactly the shortfall and pays the share, so the trip moves "
        "to booking. After a cheaper rebooking the refunds land back in everyone's wallets and "
        "the trip pot holds nothing it does not owe."
    ),
    brief=PRAGUE,
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        TopUp(KUBA, 5_000),
        Pay(everyone_except=[KUBA]),
        ExpectError("insufficient_funds"),
        Pay(members=[KUBA], fund_wallets=False),
        ExpectWallet(KUBA, balance_minor=5_000),
        ExpectStatus(TripStatus.PAYING),
        ExpectError("payment_declined"),
        TopUpAndPay([KUBA], blik_code="000000"),
        ExpectWallet(KUBA, balance_minor=5_000),
        TopUpAndPay([KUBA]),
        ExpectWallet(KUBA, balance_minor=0),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        Approve("all"),
        ExpectStatus(TripStatus.BOOKED),
        ExpectPot(held_minor=0),
        Disrupt(delay_minutes=140, price_change_percent=-10),
        ExpectStatus(TripStatus.REBOOKING),
        StartBookings("rail"),
        Approve("rail"),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED, count=2),
        ExpectStatus(TripStatus.BOOKED),
        ExpectEvent(EventKind.REFUND_ISSUED),
        ExpectWallet(KUBA, refunded=True),
        ExpectWallet(ORGANIZER, refunded=True),
        ExpectPot(held_minor=0),
    ),
)
