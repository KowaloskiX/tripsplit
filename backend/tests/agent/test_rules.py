"""The rule layer on canned observations: confident where the page is unambiguous, silent
(None -> planner) where it is not, and never pressing pay."""

from typing import Any

import pytest

from app.agent.goal import GoalSpec, parse_goal
from app.agent.rules import FieldKind, RuleEngine, classify_field, detect_stage
from app.agent.site_profiles import DEMORAIL, GENERIC, Stage, profile_for
from app.agent.summary import extract_summary
from app.agent.vault import Vault
from tests.agent.pages import (
    button,
    el,
    passengers_page,
    results_page,
    search_page,
    state,
    summary_page,
    textbox,
)

NAMES = [("Anna", "Nowak"), ("Bartek", "Wiśniewski"), ("Celina", "Lewandowska")]
GOAL_TEXT = (
    "Find and book EC 113 Vltava for 3 passengers, outbound on 2026-12-04. "
    "Passengers on this purchase: 3. Budget: 657.00 PLN total. Stop at the summary."
)


def _vault(names: list[tuple[str, str]] = NAMES) -> Vault:
    data = {"email": "org@example.test"}
    for i, (first, last) in enumerate(names, start=1):
        data[f"passenger_{i}_first_name"] = first
        data[f"passenger_{i}_last_name"] = last
    return Vault(data)


def _engine(goal: GoalSpec | None = None, vault: Vault | None = None) -> RuleEngine:
    vault = vault or _vault()
    return RuleEngine(
        goal=goal or parse_goal(GOAL_TEXT, vault),
        profile=profile_for("http://127.0.0.1/api/demo-supplier/rail-variants/baseline"),
        vault_get=vault.get,
        vault_keys=vault.planner_keys(),
    )


def _kinds(actions: list[dict[str, Any]]) -> list[str]:
    return [a["action"] for a in actions]


def test_goal_parsing_takes_party_from_vault_and_facts_from_text() -> None:
    goal = parse_goal(GOAL_TEXT, _vault())
    assert (goal.passengers, goal.date, goal.train, goal.budget) == (
        3,
        "2026-12-04",
        "EC 113 Vltava",
        657.0,
    )
    assert parse_goal("Book 2 tickets on 2026-01-02").passengers == 2


@pytest.mark.parametrize(
    ("label", "name", "kind", "index"),
    [
        ("Passenger 2 first name", "p2_first", FieldKind.FIRST_NAME, 2),
        ("Nazwisko pasażera 3", "", FieldKind.LAST_NAME, 3),
        ("Imię", "fname", FieldKind.FIRST_NAME, None),
        ("Contact email", "email", FieldKind.EMAIL, None),
        ("Date of birth", "p1_dob", FieldKind.DATE_OF_BIRTH, 1),
        ("Phone number (optional)", "phone", FieldKind.PHONE, None),
        ("Date (YYYY-MM-DD)", "date", FieldKind.TRAVEL_DATE, None),
    ],
)
def test_fields_are_classified_by_accessible_label(
    label: str, name: str, kind: FieldKind, index: int | None
) -> None:
    role = classify_field(textbox(1, name, label))
    assert role is not None
    assert (role.kind, role.index) == (kind, index)


def test_search_form_fills_date_selects_party_and_clicks_the_cta() -> None:
    decision = _engine().decide(search_page())
    assert decision is not None and decision.stage is Stage.SEARCH
    fill, select, click = decision.actions
    assert fill["fields"] == [{"ref": 3, "text": "2026-12-04"}]
    assert (select["ref"], select["text"]) == (4, "3")
    assert click["ref"] == 5


def test_renamed_cta_is_still_the_single_submit_button() -> None:
    decision = _engine().decide(search_page(cta="Szukaj połączeń"))
    assert decision is not None
    assert decision.actions[-1] == {"action": "click", "ref": 5, "milestone": "search"}


def test_offer_named_by_the_goal_wins_over_the_earliest() -> None:
    decision = _engine().decide(results_page(select="Wybierz"))
    assert decision is not None
    assert decision.actions[0]["ref"] == 2  # EC 113, not the 06:20 EC 111


def test_without_a_named_offer_the_profile_policy_picks_the_earliest() -> None:
    goal = GoalSpec(passengers=3, date="2026-12-04")
    decision = _engine(goal).decide(results_page())
    assert decision is not None and decision.actions[0]["ref"] == 1


def test_an_offer_a_real_site_does_not_show_is_left_to_the_planner() -> None:
    goal = GoalSpec(passengers=3, train="IC 5300")
    engine = _engine(goal)
    engine.profile = GENERIC
    assert engine.decide(results_page()) is None


def test_the_demo_site_substitutes_the_closest_departure_and_says_so() -> None:
    goal = GoalSpec(passengers=3, date="2026-12-04", train="EC 131 Batory", departs="07:52")
    engine = _engine(goal)
    decision = engine.decide(results_page())
    assert decision is not None and decision.actions[0]["ref"] == 1  # 06:20 is closest to 07:52
    done = engine.decide(summary_page(NAMES, train="EC 111 Praha", total="567.00"))
    assert done is not None and done.actions[0]["action"] == "done"
    assert "EC 131 Batory is not offered here; booked EC 111" in done.actions[0]["reason"]


@pytest.mark.parametrize("reordered", [False, True])
def test_passenger_form_maps_every_field_to_its_vault_key(reordered: bool) -> None:
    decision = _engine().decide(passengers_page(3, reordered=reordered, extras=True))
    assert decision is not None and decision.stage is Stage.PASSENGERS
    fill, click = decision.actions
    texts = sorted(f["text"] for f in fill["fields"])
    assert texts == sorted(
        ["{{vault.email}}"]
        + [f"{{{{vault.passenger_{i}_{p}_name}}}}" for i in (1, 2, 3) for p in ("first", "last")]
    )
    assert click["action"] == "click"


def test_second_page_of_split_passengers_keeps_the_real_indices() -> None:
    decision = _engine().decide(passengers_page(1, first_index=3))
    assert decision is not None
    assert {f["text"] for f in decision.actions[0]["fields"]} == {
        "{{vault.passenger_3_first_name}}",
        "{{vault.passenger_3_last_name}}",
        "{{vault.email}}",
    }


def test_a_required_field_nobody_can_fill_defers_to_the_planner() -> None:
    page = passengers_page(1)
    page["elements"].insert(0, textbox(99, "pesel", "PESEL", required=True))
    assert _engine().decide(page) is None


def test_more_passenger_fields_than_travellers_defers_to_the_planner() -> None:
    assert _engine().decide(passengers_page(5)) is None


def test_matching_summary_is_done_and_never_presses_pay() -> None:
    decision = _engine().decide(summary_page(NAMES))
    assert decision is not None and _kinds(decision.actions) == ["done"]
    assert "657.00 PLN" in decision.actions[0]["reason"]
    assert "Anna" not in decision.actions[0]["reason"]


def test_changed_price_hands_off_quoting_the_supplier_total() -> None:
    decision = _engine().decide(summary_page(NAMES, total="821.25"))
    assert decision is not None and _kinds(decision.actions) == ["handoff"]
    assert "supplier total 821.25" in decision.actions[0]["reason"]


def test_a_missing_traveller_on_the_summary_hands_off() -> None:
    decision = _engine().decide(summary_page(NAMES[:2], total="657.00"))
    assert decision is not None and _kinds(decision.actions) == ["handoff"]


def test_sold_out_hands_off_with_the_suppliers_words() -> None:
    decision = _engine().decide(results_page(sold_out=True))
    assert decision is not None and decision.actions[0]["action"] == "handoff"
    assert "sold out" in decision.actions[0]["reason"].lower()


def test_consent_wall_accepts_never_rejects() -> None:
    page = state([button(1, "Reject all"), button(2, "Accept all cookies")], "We use cookies")
    decision = _engine().decide(page)
    assert decision is not None and decision.actions[0]["ref"] == 2


def test_a_page_with_nothing_on_it_waits_a_bounded_number_of_times() -> None:
    engine = _engine()
    waits = [engine.decide(state([], "")) for _ in range(6)]
    assert [w is not None for w in waits] == [True] * 4 + [False] * 2


def test_stage_detection_and_profiles() -> None:
    assert detect_stage(summary_page(NAMES), DEMORAIL.merged(GENERIC)) is Stage.REVIEW
    assert detect_stage(search_page(), GENERIC) is Stage.SEARCH
    assert profile_for("https://www.intercity.pl/x").name == "intercity"
    assert profile_for("https://example.com").name == "generic"
    unknown = state([el(1, "a", "link", text="Home", href="/")], "Welcome")
    assert detect_stage(unknown, GENERIC) is Stage.UNKNOWN


def test_summary_extraction_reads_a_typed_record_and_masks_names() -> None:
    record = extract_summary(summary_page(NAMES), DEMORAIL.merged(GENERIC))
    assert (record.total_minor, record.currency, record.passenger_count) == (65700, "PLN", 3)
    assert (record.date, record.service) == ("2026-12-04", "EC 113")
    assert record.masked()["passengers"] == ["A*** N***", "B*** W***", "C*** L***"]
