from dataclasses import replace

from app.core.domain.escrow import CardStatus, PurchasePayment
from app.core.domain.trips import BookingStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectBookingStatus,
    ExpectError,
    ExpectEscrow,
    ExpectEvent,
    ExpectPayment,
    ExpectPot,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    SupplierSpec,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="escrow_happy_path",
    title="Money through the partner: wallets -> trip escrow -> payouts and virtual cards",
    description=(
        "The licensed partner holds every zloty. Voting closes and the trip escrow opens with a "
        "pay-by deadline. Nothing can leave it before everyone has paid. Then the airline (an "
        "API supplier) is paid by a PAYOUT at the approval, while each train purchase and the "
        "stay/activity sites are paid by the agent with a single-use virtual card for exactly "
        "the purchase amount — charged once and closed. At BOOKED the escrow is empty."
    ),
    brief=replace(PRAGUE, brief="Weekend in Prague for 6 — fly there, train back, good food."),
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(
        SupplierSpec("sim_flight"),
        SupplierSpec("sim_rail"),
        SupplierSpec("sim_stay_site"),
        SupplierSpec("sim_activity"),
    ),
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectEvent(EventKind.ESCROW_OPENED),
        ExpectEscrow(collected_minor=0, held_minor=0),
        Pay(everyone_except=["Kuba Mazur"]),
        ExpectStatus(TripStatus.PAYING),
        # Rule #1: not a zloty leaves the escrow while Kuba owes.
        ExpectError("trip_not_ready"),
        StartBookings("all"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        Approve("all"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED, count=1),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED, count=2),
        ExpectStatus(TripStatus.BOOKED),
        ExpectPayment("flight", PurchasePayment.PAYOUT),
        ExpectPayment("rail", PurchasePayment.VIRTUAL_CARD, CardStatus.USED),
        ExpectPayment("stay", PurchasePayment.VIRTUAL_CARD, CardStatus.USED),
        ExpectEvent(EventKind.SUPPLIER_PAID),
        ExpectEscrow(refunded_minor=0, held_minor=0),
        ExpectPot(held_minor=0),
    ),
)
