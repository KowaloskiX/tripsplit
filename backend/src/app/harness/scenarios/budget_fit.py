from dataclasses import replace

from app.core.domain.trips import TripStatus
from app.harness.scenario import (
    CastVotes,
    CloseVoting,
    ExpectBudget,
    ExpectShares,
    ExpectStatus,
    ExpectWinner,
    GeneratePackages,
    Scenario,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="budget_fit",
    title="A 550 PLN per-person budget — the budget package trims itself to fit",
    description=(
        "With 550 PLN per person the hostel's private rooms (593.25 PLN pp) would not fit, so "
        "the budget package switches to dorm beds (533.25 PLN pp) and fits; comfort and splurge "
        "stay over budget and are flagged. The group picks the package that fits."
    ),
    brief=replace(PRAGUE, budget_per_person_minor=55_000),
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        ExpectBudget(within=1),
        CastVotes(0),
        CloseVoting(),
        ExpectWinner(0),
        ExpectStatus(TripStatus.PAYING),
        ExpectShares(members=6),
    ),
)
