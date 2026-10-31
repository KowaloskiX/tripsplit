"""Package rules and the research adapters — no database, no network."""

import json
from dataclasses import replace
from datetime import date, datetime

import pytest

from app.ai.claude_research import ClaudeCliResearcher, parse_packages
from app.ai.fixture_research import FixtureResearcher
from app.ai.research import TripBrief
from app.core.domain.packages import (
    booking_goal,
    format_money,
    is_over_budget,
    per_person,
    pick_winner,
)
from app.core.domain.trips import BookingKind

BRIEF = TripBrief(
    title="Weekend in Prague",
    origin="Warszawa Centralna",
    brief="cheap, good food",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 22),
    travellers=6,
)


def test_per_person_rounds_up() -> None:
    assert per_person(100, 3) == 34
    assert per_person(99, 3) == 33


def test_winner_is_most_voted_and_ties_go_to_the_earliest() -> None:
    assert pick_winner(["a", "b", "c"], ["b", "c", "b"]) == "b"
    assert pick_winner(["a", "b", "c"], ["c", "b"]) == "b"
    assert pick_winner(["a", "b", "c"], []) == "a"
    assert pick_winner(["a", "b"], ["stale", "stale", "b"]) == "b"
    with pytest.raises(ValueError):
        pick_winner([], [])


def test_format_money() -> None:
    assert format_money(123_456, "PLN") == "1234.56 PLN"
    assert format_money(5, "PLN") == "0.05 PLN"


def test_train_goal_is_a_complete_instruction() -> None:
    goal = booking_goal(
        kind=BookingKind.TRAIN,
        title="PKP Intercity EIC Warszawa -> Praha hl.n.",
        details="Departing 06:00-10:00.",
        travellers=6,
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
    )
    assert "6 passengers" in goal
    assert "2026-11-20" in goal
    assert "Departing 06:00-10:00." in goal
    assert goal.endswith("Stop at the summary before paying.")


def test_activity_goal_uses_its_own_day() -> None:
    goal = booking_goal(
        kind=BookingKind.ACTIVITY,
        title="Beer tasting",
        details="",
        travellers=4,
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
        starts_at=datetime(2026, 11, 21, 19, 0),
    )
    assert "on 2026-11-21" in goal


async def test_fixture_packages_are_deterministic_and_priced_for_the_group() -> None:
    first = await FixtureResearcher().research(BRIEF)
    second = await FixtureResearcher().research(BRIEF)
    assert first == second
    assert len(first) == 3
    totals = [package.total_minor for package in first]
    assert totals == sorted(totals), "budget -> comfort -> splurge"
    assert "Praha hl.n." in first[0].items[0].title
    assert all(item.supplier_url.startswith("https://") for p in first for item in p.items)


async def test_the_prague_train_is_the_real_pkp_ec_offer_scaled_per_traveller() -> None:
    train = (await FixtureResearcher().research(BRIEF))[0].items[0]
    assert train.kind is BookingKind.TRAIN
    assert train.supplier == "PKP Intercity"
    assert "EC 131 Batory" in train.title and "2nd class" in train.title
    assert "EC 117 Silesia" in train.details
    # 466.95 + 802.80 PLN per three passengers, twice.
    assert train.price_minor == 253_950
    assert train.starts_at is not None and train.starts_at.strftime("%H:%M") == "07:52"
    four = await FixtureResearcher().research(replace(BRIEF, travellers=4))
    assert four[0].items[0].price_minor == 4 * 42_325


def test_is_over_budget() -> None:
    assert is_over_budget(30_001, 30_000) is True
    assert is_over_budget(30_000, 30_000) is False
    assert is_over_budget(99_999, None) is False


async def test_a_budget_trims_the_cheaper_packages_to_fit() -> None:
    fits = await FixtureResearcher().research(replace(BRIEF, budget_per_person_minor=55_000))
    budget, comfort, splurge = fits
    assert "dorm beds" in budget.title
    assert per_person(budget.total_minor, 6) <= 55_000
    assert all(item.kind is not BookingKind.ACTIVITY for item in comfort.items)
    assert any(item.kind is BookingKind.ACTIVITY for item in splurge.items)
    unconstrained = await FixtureResearcher().research(BRIEF)
    assert "private rooms" in unconstrained[0].items[1].title


def _envelope(packages: object) -> bytes:
    return json.dumps({"type": "result", "result": f"Here:\n{json.dumps(packages)}"}).encode()


_ITEM = {
    "kind": "train",
    "title": "EIC",
    "supplier": "PKP Intercity",
    "supplier_url": "https://www.intercity.pl/pl/",
    "price_minor": 1000,
}


def test_claude_output_is_parsed_from_the_envelope() -> None:
    packages = parse_packages(_envelope([{"title": f"P{i}", "items": [_ITEM]} for i in range(3)]))
    assert [p.title for p in packages] == ["P0", "P1", "P2"]
    assert packages[0].total_minor == 1000


@pytest.mark.parametrize(
    "stdout",
    [
        b"not json",
        _envelope([{"title": "only one", "items": [_ITEM]}]),
        _envelope([{"title": f"P{i}", "items": [{**_ITEM, "kind": "plane"}]} for i in range(3)]),
        json.dumps({"type": "result", "is_error": True, "result": "[]"}).encode(),
    ],
)
def test_malformed_claude_output_is_rejected(stdout: bytes) -> None:
    with pytest.raises(ValueError):
        parse_packages(stdout)


async def test_claude_failure_falls_back_to_the_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    researcher = ClaudeCliResearcher(timeout_s=1)

    async def broken(_prompt: str) -> bytes:
        raise TimeoutError

    monkeypatch.setattr(researcher, "_run", broken)
    assert await researcher.research(BRIEF) == await FixtureResearcher().research(BRIEF)
