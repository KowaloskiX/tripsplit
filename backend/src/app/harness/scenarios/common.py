"""The people and the brief most scenarios share: six friends, a Prague weekend from Warsaw."""

from datetime import date

from app.core.domain.trips import BookingStatus, TripStatus
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
    ExpectBookingStatus("train", BookingStatus.CONFIRMED),
    ExpectStatus(TripStatus.BOOKED),
)
