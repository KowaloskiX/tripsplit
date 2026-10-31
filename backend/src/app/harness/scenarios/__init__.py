"""Every scenario, in the order `trip-harness run all` executes them."""

from app.harness.scenario import Scenario
from app.harness.scenarios import (
    agent_stuck_retry,
    approval_while_paying,
    barcelona_flight_hold,
    budget_fit,
    budget_guard,
    bus_party_of_eight,
    cancelled_flight,
    captcha_handoff,
    dearer_rebooking,
    delayed_train,
    dropout_after_paying,
    flight_needs_passport,
    missing_payment,
    mixed_modes,
    prague_happy_path,
    prague_liteapi_live,
    price_jump,
    rail_party_of_eight,
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
        barcelona_flight_hold,
        flight_needs_passport,
        bus_party_of_eight,
        rail_party_of_eight,
        mixed_modes,
        cancelled_flight,
        prague_liteapi_live,
    )
}
