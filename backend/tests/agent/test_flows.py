"""Flows: a run recorded for 6 passengers replays for 1..9, values are bound to the goal,
offers are chosen from the goal, and legacy trajectories still load."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent import flows
from app.agent.goal import GoalSpec
from app.agent.site_profiles import Stage, profile_for
from app.agent_evals.harness import baseline_flow
from tests.agent.pages import passengers_page, results_page, search_page, textbox

PROFILE = profile_for("http://127.0.0.1/api/demo-supplier/rail-variants/baseline")


def _player(party: int, train: str | None = "EC 113 Vltava") -> flows.FlowPlayer:
    goal = GoalSpec(passengers=party, date="2026-12-04", train=train)
    return flows.FlowPlayer(baseline_flow(), goal, PROFILE)


def test_the_six_passenger_recording_compiles_into_a_loop() -> None:
    flow = baseline_flow()
    assert flow["version"] == flows.FLOW_VERSION and flow["recorded_party"] == 6
    passengers = next(s for s in flow["steps"] if s["milestone"] == "passengers")
    loop, email = passengers["items"]
    assert loop["loop"] == "passengers"
    assert [b["target"]["name"] for b in loop["body"]] == ["p{i}_first", "p{i}_last"]
    assert email["value"] == "{{vault.email}}"


@pytest.mark.parametrize("party", [1, 3, 5, 9])
def test_replay_fills_exactly_the_current_party(party: int) -> None:
    player = _player(party)
    player.cursor = next(i for i, s in enumerate(player.steps) if s["milestone"] == "passengers")
    batch = player.next_actions(passengers_page(party)["elements"], Stage.PASSENGERS)
    assert batch is not None
    fill = batch[0]
    texts = [f["text"] for f in fill["fields"]]
    assert len(texts) == 2 * party + 1
    assert texts[-3:-1] == [
        f"{{{{vault.passenger_{party}_first_name}}}}",
        f"{{{{vault.passenger_{party}_last_name}}}}",
    ]
    assert len({f["ref"] for f in fill["fields"]}) == len(texts)


def test_a_party_larger_than_the_form_is_a_miss_not_a_partial_fill() -> None:
    player = _player(3)
    player.cursor = 4
    assert player.next_actions(passengers_page(2)["elements"], Stage.PASSENGERS) is None
    assert player.misses == 1


def test_search_values_are_bound_to_the_goal_and_batched_with_the_click() -> None:
    player = _player(3)
    batch = player.next_actions(search_page()["elements"], Stage.SEARCH)
    assert batch is not None
    assert [a["action"] for a in batch] == ["fill_form", "select", "click"]
    assert batch[0]["fields"][0]["text"] == "2026-12-04"  # recorded 2026-11-20
    assert batch[1]["text"] == "3"  # recorded 6


def test_the_offer_is_chosen_from_the_goal_not_the_recording() -> None:
    player = _player(3)
    player.cursor = 3
    batch = player.next_actions(results_page()["elements"], Stage.RESULTS)
    assert batch is not None and batch[0]["ref"] == 2  # EC 113 (recorded: EC 111)


def test_renamed_cta_is_a_miss_and_the_cursor_waits_for_the_heal() -> None:
    player = _player(3)
    page = search_page(cta="Szukaj połączeń")["elements"]
    batch = player.next_actions(page, Stage.SEARCH)
    assert batch is not None and [a["action"] for a in batch] == ["fill_form", "select"]
    assert player.next_actions(page, Stage.SEARCH) is None and player.misses == 1
    # After the rule layer clicked, the results page resynchronises the cursor.
    assert player.next_actions(results_page()["elements"], Stage.RESULTS) is not None


def test_a_step_for_a_later_stage_never_runs_on_an_earlier_page() -> None:
    player = _player(3)
    player.cursor = 3  # the offer click
    assert player.next_actions(search_page()["elements"], Stage.SEARCH) is None


def test_recording_and_recompiling_a_run_generalises_again() -> None:
    page = passengers_page(3)["elements"]
    action = {
        "action": "fill_form",
        "milestone": "passengers",
        "fields": [
            {"ref": e["ref"], "text": t}
            for e, t in zip(
                page,
                [
                    f"{{{{vault.passenger_{i}_{p}_name}}}}"
                    for i in (1, 2, 3)
                    for p in ("first", "last")
                ]
                + ["{{vault.email}}"],
                strict=False,
            )
        ],
    }
    flow = flows.compile_flow(
        [flows.record_step(action, page)], GoalSpec(passengers=3), vault_lookup={}
    )
    player = flows.FlowPlayer(flow, GoalSpec(passengers=5), PROFILE)
    batch = player.next_actions(passengers_page(5)["elements"], Stage.PASSENGERS)
    assert batch is not None and len(batch[0]["fields"]) == 11


def test_non_contiguous_passenger_blocks_stay_literal() -> None:
    page = passengers_page(2, first_index=3)["elements"]
    fields = [
        {"ref": page[0]["ref"], "text": "{{vault.passenger_3_first_name}}"},
        {"ref": page[1]["ref"], "text": "{{vault.passenger_3_last_name}}"},
    ]
    flow = flows.compile_flow(
        [flows.record_step({"action": "fill_form", "fields": fields}, page)], GoalSpec(5)
    )
    items = flow["steps"][0]["items"]
    assert all("loop" not in item for item in items)
    assert items[0]["target"]["name"] == "p3_first"


def test_a_literal_equal_to_a_vault_value_is_stored_as_its_placeholder() -> None:
    page = [textbox(1, "email", "Contact email")]
    raw = flows.record_step({"action": "type", "ref": 1, "text": "org@example.test"}, page)
    flow = flows.compile_flow([raw], GoalSpec(1), vault_lookup={"org@example.test": "email"})
    assert flow["steps"][0]["value"] == "{{vault.email}}"
    assert "org@example.test" not in json.dumps(flow)


def test_legacy_trajectory_is_loaded_and_new_flows_are_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_VAR_DIR", str(tmp_path))
    url = "http://localhost:8500/api/demo-supplier/rail"
    raw: Any = json.loads(
        (
            Path(flows.__file__).parents[1] / "agent_evals/fixtures/demorail_trajectory_6pax.json"
        ).read_text()
    )
    (tmp_path / "trajectories").mkdir()
    (tmp_path / "trajectories" / "localhost.json").write_text(json.dumps(raw))
    loaded = flows.load(url)
    assert loaded is not None and loaded["recorded_party"] == 6
    path = flows.save(url, loaded)
    assert path is not None and path.endswith("localhost.flow.json")
    assert flows.load(url) == loaded
