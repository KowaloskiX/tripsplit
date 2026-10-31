"""The people and the briefs scenarios share: six friends, a Prague weekend from Warsaw by
rail, a Barcelona long weekend by plane, and eight friends from Kraków to Budapest."""

from datetime import date

from app.core.domain.trips import BookingStatus, TransportMode, TripStatus
from app.harness.scenario import (
    Approve,
    Brief,
    CastVotes,
    CloseVoting,
    ExpectBookingStatus,
    ExpectStatus,
    GeneratePackages,
    Pay,
    StartBookings,
    Step,
)

ORGANIZER = "Anna Kowalska"
FRIENDS = ("Kuba Mazur", "Marta Lis", "Piotr Nowak", "Zosia Wrona", "Tomek Dudek")

PRAGUE = Brief(
    title="Weekend in Prague",
    origin="Warszawa",
    brief="Weekend in Prague for 6 from Warsaw — cheap, good food, one fun evening.",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 22),
    group_size=6,
)

BARCELONA = Brief(
    title="Barcelona long weekend",
    origin="Warszawa",
    brief="Long weekend in Barcelona for 6 — beach, tapas, one big night out.",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 23),
    group_size=6,
    destination="Barcelona",
    transport_mode=TransportMode.FLIGHT,
)

EIGHT_FRIENDS = (*FRIENDS, "Ola Sikora", "Bartek Pawlak")


def budapest(mode: TransportMode) -> Brief:
    return Brief(
        title="Budapest weekend",
        origin="Kraków",
        brief="Weekend in Budapest for 8 — thermal baths and ruin bars.",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
        group_size=8,
        destination="Budapest",
        transport_mode=mode,
    )


# Packages -> everyone votes the budget package -> close -> everyone pays.
UNTIL_PAID: tuple[Step, ...] = (
    GeneratePackages(),
    ExpectStatus(TripStatus.VOTING),
    CastVotes(0),
    CloseVoting(),
    ExpectStatus(TripStatus.PAYING),
    Pay(),
    ExpectStatus(TripStatus.BOOKING),
)

# ... then every booking is bought and approved.
UNTIL_BOOKED: tuple[Step, ...] = (
    *UNTIL_PAID,
    StartBookings("all"),
    Approve("all"),
    ExpectBookingStatus("transport", BookingStatus.CONFIRMED),
    ExpectStatus(TripStatus.BOOKED),
)
