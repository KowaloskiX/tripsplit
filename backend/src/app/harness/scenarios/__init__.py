"""Every scenario, in the order `trip-harness run all` executes them."""

from app.harness.scenario import Scenario
from app.harness.scenarios import (
    agent_stuck_retry,
    approval_while_paying,
    budget_fit,
    budget_guard,
    captcha_handoff,
    dearer_rebooking,
    delayed_train,
    dropout_after_paying,
    missing_payment,
    prague_happy_path,
    price_jump,
    vote_tie,
)

SCENARIOS: dict[str, Scenario] = {
    module.SCENARIO.name: module.SCENARIO
    for module in (
        prague_happy_path,
        missing_payment,
        price_jump,
        delayed_train,
        dropout_after_paying,
        captcha_handoff,
        vote_tie,
        budget_guard,
        budget_fit,
        approval_while_paying,
        dearer_rebooking,
        agent_stuck_retry,
    )
}
