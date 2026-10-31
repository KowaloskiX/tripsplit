from dataclasses import replace

from app.core.domain.trips import TripStatus
from app.harness.scenario import (
    CastVotes,
    CloseVoting,
    ExpectStatus,
    ExpectWithinBudget,
    GeneratePackages,
    Scenario,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="budget_guard",
    title="A 300 PLN per-person budget below every package",
    description=(
        "The brief caps the trip at 300 PLN per person, below the cheapest package. Records what "
        "the system does about it: the packages should fit the budget, or the group should be "
        "told they do not."
    ),
    brief=replace(PRAGUE, budget_per_person_minor=30_000),
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        ExpectWithinBudget(),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
    ),
    xfail=(
        "budget_per_person_minor reaches the researcher but nothing enforces or flags it: "
        "every package is over budget and voting/closing proceed silently"
    ),
)
