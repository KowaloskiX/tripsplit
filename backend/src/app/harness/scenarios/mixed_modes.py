from dataclasses import replace

from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus
from app.harness.scenario import (
    Approve,
    CastVotes,
    CloseVoting,
    ExpectAgentRuns,
    ExpectBookingStatus,
    ExpectError,
    ExpectEvent,
    ExpectHold,
    ExpectPurchases,
    ExpectShares,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    SupplierPriceChange,
    SupplierSpec,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="mixed_modes",
    holds=True,
    title="Fly there, train back: two transport bookings of different modes",
    description=(
        "The brief says “fly there, train back”: the package has a one-way flight (airline "
        "API, held, one purchase for six) and a one-way train home (carrier site, cap 5 -> "
        "3 + 3). The rail fare rises 10% before the purchase and goes through the same single "
        "re-split pipeline as any other price change; then everything is bought."
    ),
    brief=replace(PRAGUE, brief="Weekend in Prague for 6 — fly there, train back, good food."),
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=(
        SupplierSpec("sim_flight"),
        SupplierSpec("sim_rail"),
        SupplierSpec("sim_stay"),
        SupplierSpec("sim_activity"),
    ),
    steps=(
        GeneratePackages(),
        CastVotes(0),
        CloseVoting(),
        ExpectPurchases("flight", (6,)),
        ExpectPurchases("rail", (3, 3)),
        ExpectHold("flight"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        SupplierPriceChange("rail", 10),
        ExpectError("price_changed"),
        StartBookings("rail"),
        ExpectEvent(EventKind.PRICE_CHANGED),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(status=ContributionStatus.PENDING, vs_initial="higher"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("all"),
        Approve("all"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED, count=1),
        ExpectBookingStatus("rail", BookingStatus.CONFIRMED, count=2),
        ExpectAgentRuns("flight", 0),
        ExpectAgentRuns("rail", 2),
        ExpectStatus(TripStatus.BOOKED),
        ExpectShares(status=ContributionStatus.PAID, vs_initial="higher"),
    ),
)
