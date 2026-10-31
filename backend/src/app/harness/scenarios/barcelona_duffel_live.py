from datetime import date

from app.core.domain.trips import BookingStatus, EventKind, TransportMode, TripStatus
from app.harness.scenario import (
    Approve,
    Brief,
    CastVotes,
    CloseVoting,
    ExpectAgentRuns,
    ExpectBookingStatus,
    ExpectEvent,
    ExpectHold,
    ExpectPurchases,
    ExpectStatus,
    GeneratePackages,
    Pay,
    Scenario,
    StartBookings,
    SupplierSpec,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER

# A Friday-to-Sunday weekend: the dates the lead verified against the Duffel test account.
BARCELONA_WEEKEND = Brief(
    title="Barcelona weekend",
    origin="Warszawa",
    brief="Weekend in Barcelona for 6 — beach, tapas, one big night out.",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 22),
    group_size=6,
    destination="Barcelona",
    transport_mode=TransportMode.FLIGHT,
)

AIRLINE_REPRICE_TOLERANCE = 1.0

DUFFEL_TRIP = (SupplierSpec("duffel"), SupplierSpec("sim_stay"), SupplierSpec("sim_activity"))

SCENARIO = Scenario(
    name="barcelona_duffel_live",
    holds=True,
    title="Barcelona on REAL airline offers (Duffel test API): hold at close, pay, ticket",
    description=(
        "Six friends fly Warszawa -> Barcelona on offers from Duffel's test API (real search, "
        "EUR prices converted to PLN). Everyone's traveller details are in, so when the vote "
        "closes a real HOLD order is created at Duffel with the six named passengers; the stay "
        "is held by the simulated hotel. Everyone pays, the flight purchase awaits the "
        "approval, and approving pays the held Duffel order from the test balance — CONFIRMED "
        "with the airline's booking reference, no agent run. Runs only with --live-flights."
    ),
    brief=BARCELONA_WEEKEND,
    organizer=ORGANIZER,
    friends=FRIENDS,
    suppliers=DUFFEL_TRIP,
    live_flights_only=True,
    # Airline sandboxes re-price by cents between the search and the order.
    price_tolerance_percent=AIRLINE_REPRICE_TOLERANCE,
    steps=(
        GeneratePackages(),
        ExpectStatus(TripStatus.VOTING),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectPurchases("flight", (6,)),
        ExpectEvent(EventKind.HOLD_PLACED),
        ExpectHold("flight"),
        ExpectHold("stay"),
        Pay(),
        ExpectStatus(TripStatus.BOOKING),
        StartBookings("flight", top_up_on_price_change=True),
        ExpectBookingStatus("flight", BookingStatus.AWAITING_APPROVAL),
        Approve("flight"),
        ExpectBookingStatus("flight", BookingStatus.CONFIRMED, count=1),
        ExpectAgentRuns("flight", 0),
        StartBookings("stay"),
        Approve("stay"),
        ExpectBookingStatus("stay", BookingStatus.CONFIRMED),
        ExpectStatus(TripStatus.BOOKED),
    ),
)
