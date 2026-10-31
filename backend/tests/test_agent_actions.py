"""Agent action plumbing that needs no browser: vault substitution and trajectory replay."""

from typing import Any

import pytest

from app.agent import trajectory
from app.agent.act import UnknownVaultKey, _resolve
from app.agent.vault import Vault


def test_known_placeholder_is_substituted() -> None:
    vault = Vault({"passenger_1_first_name": "Anna"})
    assert _resolve("{{vault.passenger_1_first_name}}", vault) == "Anna"


def test_card_secrets_are_masked_however_short_but_a_party_size_is_not() -> None:
    vault = Vault({"card_cvc": "737", "card_number": "4242424242424242", "party": "3"})
    masked = vault.mask("CVC 737, card 4242424242424242, 3 passengers")
    assert masked == "CVC •••, card •••, 3 passengers"


def test_unknown_placeholder_fails_loudly_and_lists_the_real_keys() -> None:
    vault = Vault({"passenger_1_first_name": "Anna"})
    with pytest.raises(UnknownVaultKey, match="passenger_1_first_name"):
        _resolve("{{vault.passenger_1}}", vault)


def test_fill_form_is_recorded_and_replayed_by_stable_descriptors() -> None:
    recorded_page: list[dict[str, Any]] = [
        {"ref": 1, "tag": "input", "type": "text", "name": "p1_first", "text": "", "href": ""},
        {"ref": 2, "tag": "input", "type": "text", "name": "p1_last", "text": "", "href": ""},
    ]
    action = {
        "action": "fill_form",
        "fields": [
            {"ref": 1, "text": "{{vault.passenger_1_first_name}}"},
            {"ref": 2, "text": "{{vault.passenger_1_last_name}}"},
        ],
        "milestone": "passengers",
    }
    step = trajectory.record_step(action, recorded_page)

    # Next run: same fields, different ephemeral refs.
    replay_page = [{**element, "ref": element["ref"] + 10} for element in recorded_page]
    replayed = trajectory.action_from_cache(step, replay_page)

    assert replayed is not None
    assert [field["ref"] for field in replayed["fields"]] == [11, 12]
    assert replayed["fields"][0]["text"] == "{{vault.passenger_1_first_name}}"


def test_fill_form_replay_misses_when_a_field_is_gone() -> None:
    page: list[dict[str, Any]] = [
        {"ref": 1, "tag": "input", "type": "text", "name": "p1_first", "text": "", "href": ""}
    ]
    step = trajectory.record_step(
        {"action": "fill_form", "fields": [{"ref": 1, "text": "x"}]}, page
    )
    assert trajectory.action_from_cache(step, []) is None
