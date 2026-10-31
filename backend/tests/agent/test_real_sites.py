"""Real third-party sites as canned observations: BlazeDemo (a public flight-booking demo
built for test automation) and PKP Intercity's e-IC up to the filled guest form."""

from typing import Any

from app.agent import flows
from app.agent.goal import parse_goal
from app.agent.rules import RuleEngine, choose_fare, choose_offer, detect_stage
from app.agent.runner import RunResult, reached_planned_handoff
from app.agent.site_profiles import Stage, profile_for
from app.agent.vault import Vault
from app.core.domain.bookings import is_real_eic
from tests.agent.pages import button, el, state, textbox

BLAZE = "https://blazedemo.com/"
EIC = "https://ebilet.intercity.pl/polaczenia-miedzynarodowe?dwyj=2026-11-20&ticket100=1010"
BLAZE_GOAL = "Book a flight from Paris to London for 3 passengers, cheapest, stop at the purchase"
EIC_GOAL = (
    "Warszawa Centralna -> Praha hl.n. on 2026-11-20 for 3 passengers, 2nd class, non-refundable"
)


def _vault() -> Vault:
    return Vault(
        {
            "passenger_1_first_name": "Ada",
            "passenger_1_last_name": "Testowa",
            "passenger_2_first_name": "Bob",
            "passenger_2_last_name": "Probny",
            "passenger_3_first_name": "Cleo",
            "passenger_3_last_name": "Example",
        }
    )


def _engine(url: str, goal: str) -> RuleEngine:
    vault = _vault()
    return RuleEngine(
        goal=parse_goal(goal, vault),
        profile=profile_for(url),
        vault_get=vault.get,
        vault_keys=vault.planner_keys(),
    )


def _ref(element: dict[str, Any] | None) -> int | None:
    return element["ref"] if element is not None else None


def _city_select(ref: int, name: str, value: str, options: list[str]) -> dict[str, Any]:
    return el(
        ref, "select", "combobox", name=name, text=" ".join(options), value=value, options=options
    )


def _blaze_search() -> dict[str, Any]:
    return state(
        [
            _city_select(1, "fromPort", "Paris", ["Paris", "Boston", "São Paolo"]),
            _city_select(2, "toPort", "Buenos Aires", ["Buenos Aires", "Rome", "London"]),
            el(3, "input", "button", type="submit", text="Find Flights"),
        ],
        "Welcome to the Simple Travel Agency!",
        url=BLAZE,
    )


def _blaze_flights() -> dict[str, Any]:
    rows = [
        (4, "43 Virgin America 1:43 AM 9:45 PM $472.56"),
        (5, "234 United Airlines 7:43 AM 10:45 PM $432.98"),
        (6, "9696 Aer Lingus 5:27 AM 8:22 PM $200.98"),
        (7, "12 Virgin America 11:23 AM 1:45 PM $1,765.32"),
    ]
    return state(
        [
            button(ref, "Choose This Flight", context=f"Choose This Flight {row}")
            for ref, row in rows
        ],
        "Flights from Paris to London",
        url=BLAZE + "reserve.php",
    )


def _blaze_purchase(name_value: str = "") -> dict[str, Any]:
    return state(
        [
            textbox(1, "inputName", "Name", placeholder="First Last", value=name_value),
            textbox(2, "address", "Address", placeholder="123 Main St."),
            textbox(3, "creditCardNumber", "Credit Card Number"),
            el(4, "input", "button", type="submit", text="Purchase Flight"),
        ],
        "Your flight from TLV to SFO has been reserved. Price: 400 Total Cost: 914.76 "
        "Please submit the form below to purchase the flight.",
        url=BLAZE + "purchase.php",
    )


def test_the_goal_names_a_route_cheapest_and_the_fare() -> None:
    goal = parse_goal("Book a flight from São Paolo to New York for 2 people, cheapest")
    assert (goal.origin, goal.destination, goal.cheapest) == ("São Paolo", "New York", True)
    fare = parse_goal("3 passengers, 1st class, flexible fare")
    assert (fare.travel_class, fare.flexible) == (1, True)
    assert parse_goal("2nd class, the cheapest non-refundable fare").flexible is False


def test_blazedemo_search_sets_both_cities_even_when_one_is_preselected() -> None:
    decision = _engine(BLAZE, BLAZE_GOAL).decide(_blaze_search())
    assert decision is not None and decision.stage is Stage.SEARCH
    assert [(a["action"], a.get("text")) for a in decision.actions] == [
        ("select", "Paris"),
        ("select", "London"),
        ("click", None),
    ]


def test_dollar_prices_and_twelve_hour_times_pick_the_cheapest_flight() -> None:
    page = _blaze_flights()
    goal = parse_goal(BLAZE_GOAL)
    assert detect_stage(page, profile_for(BLAZE)) is Stage.RESULTS
    assert _ref(choose_offer(page["elements"], goal, profile_for(BLAZE))) == 6


def test_a_pay_page_with_an_empty_billing_form_is_left_to_the_flow_or_planner() -> None:
    engine = _engine(BLAZE, BLAZE_GOAL)
    assert detect_stage(_blaze_purchase(), engine.profile) is Stage.REVIEW
    assert engine.decide(_blaze_purchase()) is None


def test_a_lead_name_typed_into_the_form_verifies_the_whole_party() -> None:
    decision = _engine(BLAZE, BLAZE_GOAL).decide(_blaze_purchase("Ada Testowa"))
    assert decision is not None
    assert decision.actions[0]["action"] == "done"
    assert "lead passenger" in decision.actions[0]["reason"]


def test_a_single_lead_name_field_does_not_compile_into_a_passenger_loop() -> None:
    raw = [
        {
            "action": "fill_form",
            "milestone": "review",
            "fields": [
                {
                    "text": "{{vault.passenger_1_first_name}} {{vault.passenger_1_last_name}}",
                    "desc": {"tag": "input", "role": "textbox", "id": "inputName"},
                }
            ],
        }
    ]
    step = flows.compile_flow(raw, parse_goal(BLAZE_GOAL, _vault()))["steps"][0]
    assert "loop" not in step["items"][0]
    assert step["items"][0]["value"].startswith("{{vault.passenger_1_first_name}}")


def test_route_selects_are_bound_to_the_goal() -> None:
    raw = [
        {"action": "select", "text": "Paris", "milestone": "search", "desc": {"name": "fromPort"}},
        {"action": "select", "text": "London", "milestone": "search", "desc": {"name": "toPort"}},
    ]
    steps = flows.compile_flow(raw, parse_goal(BLAZE_GOAL))["steps"]
    assert [s["value"] for s in steps] == ["{{goal.origin}}", "{{goal.destination}}"]


def _eic_results(adults: int, opened: bool = False) -> dict[str, Any]:
    card = "Connection to 07:52 Warszawa Centr. Praha hl.n. Class 2 155,65 PLN"
    other = "Connection to 12:44 Warszawa Centr. Praha hl.n. Class 1 177,95 PLN"
    elements = [button(1, "CHANGE")]
    if opened:
        elements += [
            button(2, "details", context=card),
            button(3, "Choose class 2", context=card),
            button(4, "Choose class 2", context=card),
        ]
    else:
        elements.append(button(2, "Buy a ticket for a connection 07:52", context=card))
    elements.append(button(5, "Buy a ticket for a connection 12:44", context=other))
    return state(elements, f"{adults}x Passengers {adults} x Adults CHANGE", url=EIC)


def test_e_ic_offers_wait_until_the_party_matches_the_goal() -> None:
    engine = _engine(EIC, EIC_GOAL)
    assert engine.decide(_eic_results(adults=1)) is None
    assert "change the party" in engine.notes[-1]
    decision = engine.decide(_eic_results(adults=3))
    assert decision is not None and decision.actions[0]["ref"] == 2


def test_e_ic_fare_boxes_pick_the_first_fare_of_the_class_or_the_flexible_one() -> None:
    page = _eic_results(adults=3, opened=True)
    profile = profile_for(EIC)
    assert detect_stage(page, profile) is Stage.FARE
    assert _ref(choose_fare(page["elements"], parse_goal(EIC_GOAL), profile)) == 3
    flexible = parse_goal("3 passengers, 2nd class, flexible fare")
    assert _ref(choose_fare(page["elements"], flexible, profile)) == 4


def test_a_header_button_on_a_results_page_is_not_an_offer_choice() -> None:
    raw = [
        {"action": "click", "milestone": "results", "desc": {"tag": "button", "text": "CHANGE"}},
        {
            "action": "click",
            "milestone": "results",
            "desc": {"tag": "button", "text": "Buy", "context": "Connection to 07:52 155,65 PLN"},
        },
    ]
    steps = flows.compile_flow(raw, parse_goal(EIC_GOAL))["steps"]
    assert [s.get("choice") for s in steps] == [None, "offer"]


def test_the_filled_guest_form_is_a_planned_handoff_that_still_counts_as_success() -> None:
    profile = profile_for(EIC)
    assert profile.handoff_milestone == "guest_form_filled"
    stopped = RunResult(run_id="r", url=EIC, goal="g", outcome="handoff")
    stopped.milestones = ["results", "fare", "guest_screen", "guest_form_filled"]
    assert reached_planned_handoff(stopped, profile)
    blocked = RunResult(run_id="r", url=EIC, goal="g", outcome="handoff", milestones=["results"])
    assert not reached_planned_handoff(blocked, profile)
    assert not reached_planned_handoff(stopped, profile_for(BLAZE))


def test_the_guest_wall_is_passed_through_continue_as_guest() -> None:
    wall = state(
        [
            button(1, "LOG IN"),
            button(2, "REGISTER"),
            el(3, "a", "link", text="Continue as Guest"),
        ],
        "Sign in LOG IN REGISTER Continue as Guest",
        url=EIC,
    )
    decision = _engine(EIC, EIC_GOAL).decide(wall)
    assert decision is not None
    assert decision.actions == [{"action": "click", "ref": 3, "milestone": "guest_screen"}]


def test_the_guest_form_is_filled_then_handed_off_without_any_consent_or_submit() -> None:
    vault = Vault({"email": "demo.guest@example.com"})
    engine = RuleEngine(
        goal=parse_goal(EIC_GOAL, vault),
        profile=profile_for(EIC),
        vault_get=vault.get,
        vault_keys=vault.planner_keys(),
    )
    form = state(
        [
            textbox(1, "email", "E-mail", required=True),
            textbox(2, "email2", "E-mail repeat", required=True),
            el(3, "input", "checkbox", type="checkbox", label="I accept the e-IC Regulations"),
            button(4, "SAVE"),
        ],
        "Enter data E-mail E-mail repeat I accept the e-IC Regulations SAVE",
        url="https://sso.intercity.pl/oauth_server/oauth/register?type=guest",
    )
    decision = engine.decide(form)
    assert decision is not None
    fill, handoff = decision.actions
    assert fill["action"] == "fill_form"
    assert [f["ref"] for f in fill["fields"]] == [1, 2]
    assert handoff["action"] == "handoff"
    assert handoff["milestone"] == "guest_form_filled"


def test_only_intercity_hosts_count_as_the_real_e_ic_checkout() -> None:
    assert is_real_eic(EIC)
    assert is_real_eic("https://sso.intercity.pl/x")
    assert not is_real_eic("http://localhost:8000/api/demo-supplier/rail")
    assert not is_real_eic("https://intercity.pl.evil.example/")
