from dataclasses import replace

from app.core.domain.trips import TripStatus
from app.harness.scenario import (
    CastVotes,
    CloseVoting,
    ExpectAgentMessage,
    ExpectBudget,
    ExpectStatus,
    GeneratePackages,
    Scenario,
)
from app.harness.scenarios.common import FRIENDS, ORGANIZER, PRAGUE

SCENARIO = Scenario(
    name="budget_guard",
    title="A 300 PLN per-person budget below every package",
    description=(
        "The brief caps the trip at 300 PLN per person — less than the return train alone "
        "(423.25 PLN). The researcher offers the cheapest options it has (dorm beds, no paid "
        "evening), every package is flagged over budget and the feed says none fits; closing "
        "the vote on one is allowed, with the agent warning the group."
    ),
    brief=replace(PRAGUE, budget_per_person_minor=30_000),
    organizer=ORGANIZER,
    friends=FRIENDS,
    steps=(
        GeneratePackages(),
        ExpectBudget(within=0),
        ExpectAgentMessage("none fits the budget"),
        CastVotes(0),
        CloseVoting(),
        ExpectStatus(TripStatus.PAYING),
        ExpectAgentMessage("is over your budget"),
    ),
)
