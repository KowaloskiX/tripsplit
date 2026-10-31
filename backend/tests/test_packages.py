"""Package rules and the research adapters — no database, no network."""

import json
from dataclasses import replace
from datetime import date, datetime

import pytest

from app.ai.catalog_research import CatalogResearcher
from app.ai.claude_research import ClaudeCliResearcher, offers_json, parse_descriptions
from app.ai.research import TripBrief
from app.core.domain.packages import (
    booking_goal,
    format_money,
    is_over_budget,
    per_person,
    pick_winner,
)
from app.core.domain.trips import BookingKind, TransportMode
from app.db.documents import utc_now
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import sim_supplier


def _catalogue(*ids: str) -> CatalogResearcher:
    chosen = ids or ("sim_rail", "sim_stay_site", "sim_activity")
    return CatalogResearcher(SupplierRegistry(sim_supplier(i, utc_now) for i in chosen))


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


def test_transport_goal_is_a_complete_instruction() -> None:
    goal = booking_goal(
        kind=BookingKind.TRANSPORT,
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


def test_a_transport_goal_names_its_segments() -> None:
    goal = booking_goal(
        kind=BookingKind.TRANSPORT,
        title="Ryanair FR 1234",
        details="",
        travellers=6,
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 23),
        itinerary="FR 1234 WMI -> BCN 2026-11-20 06:25",
    )
    assert "FR 1234 WMI -> BCN 2026-11-20 06:25" in goal
    assert "return on" not in goal


async def test_catalogue_packages_are_deterministic_and_priced_for_the_group() -> None:
    first = await _catalogue().research(BRIEF)
    second = await _catalogue().research(BRIEF)
    assert first == second
    assert len(first) == 3
    totals = [package.total_minor for package in first]
    assert totals == sorted(totals), "budget -> comfort -> splurge"
    assert "Praha hl.n." in first[0].items[0].title
    assert all(item.supplier_id.startswith("sim_") for p in first for item in p.items)
    assert all(item.offer_ref for p in first for item in p.items)


async def test_the_prague_train_is_the_real_pkp_ec_offer_scaled_per_traveller() -> None:
    train = (await _catalogue().research(BRIEF))[0].items[0]
    assert (train.kind, train.mode) == (BookingKind.TRANSPORT, TransportMode.RAIL)
    assert train.supplier == "PKP Intercity"
    assert "EC 131 Batory" in train.title and "2nd class" in train.title
    assert "EC 117" in train.details
    assert [segment.number for segment in train.segments] == ["EC 131", "EC 117"]
    # 466.95 + 802.80 PLN per three passengers, twice.
    assert train.price_minor == 253_950
    assert train.starts_at is not None and train.starts_at.strftime("%H:%M") == "07:52"
    four = await _catalogue().research(replace(BRIEF, travellers=4))
    assert four[0].items[0].price_minor == 4 * 42_325


async def test_a_mode_preference_picks_the_suppliers() -> None:
    researcher = _catalogue("sim_rail", "sim_flight", "sim_bus", "sim_stay", "sim_activity")
    flights = await researcher.research(replace(BRIEF, transport_mode=TransportMode.FLIGHT))
    assert {p.items[0].mode for p in flights} == {TransportMode.FLIGHT}
    assert flights[0].items[0].supplier == "Ryanair"
    assert flights[2].items[0].supplier == "LOT Polish Airlines"
    mixed = await researcher.research(replace(BRIEF, brief="fly there, train back"))
    assert [item.mode for item in mixed[0].items[:2]] == [TransportMode.FLIGHT, TransportMode.RAIL]
    assert [len(item.segments) for item in mixed[0].items[:2]] == [1, 1]


async def test_no_transport_offer_is_a_research_failure() -> None:
    with pytest.raises(ValueError):
        await _catalogue().research(replace(BRIEF, brief="Barcelona", destination="Barcelona"))


def test_is_over_budget() -> None:
    assert is_over_budget(30_001, 30_000) is True
    assert is_over_budget(30_000, 30_000) is False
    assert is_over_budget(99_999, None) is False


async def test_a_budget_trims_the_cheaper_packages_to_fit() -> None:
    fits = await _catalogue().research(replace(BRIEF, budget_per_person_minor=55_000))
    budget, comfort, splurge = fits
    assert "dorm beds" in budget.title
    assert per_person(budget.total_minor, 6) <= 55_000
    assert all(item.kind is not BookingKind.ACTIVITY for item in comfort.items)
    assert any(item.kind is BookingKind.ACTIVITY for item in splurge.items)
    unconstrained = await _catalogue().research(BRIEF)
    assert "private rooms" in unconstrained[0].items[1].title


def _envelope(descriptions: object) -> bytes:
    return json.dumps({"type": "result", "result": f"Here:\n{json.dumps(descriptions)}"}).encode()


def test_claude_descriptions_are_parsed_from_the_envelope() -> None:
    parsed = parse_descriptions(_envelope([{"title": f"P{i}"} for i in range(3)]), 3)
    assert [d.title for d in parsed] == ["P0", "P1", "P2"]


@pytest.mark.parametrize(
    "stdout",
    [
        b"not json",
        _envelope([{"title": "only one"}]),
        _envelope([{"title": ""} for _ in range(3)]),
        json.dumps({"type": "result", "is_error": True, "result": "[]"}).encode(),
    ],
)
def test_malformed_claude_output_is_rejected(stdout: bytes) -> None:
    with pytest.raises(ValueError):
        parse_descriptions(stdout, 3)


async def test_claude_only_rewrites_the_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue = _catalogue()
    researcher = ClaudeCliResearcher(catalogue, timeout_s=1)

    async def describe(prompt: str) -> bytes:
        assert "Kowalska" not in prompt  # offers only — never people
        return _envelope([{"title": f"Package {i}", "summary": "Nice."} for i in range(3)])

    monkeypatch.setattr(researcher, "_run", describe)
    described = await researcher.research(BRIEF)
    plain = await catalogue.research(BRIEF)
    assert [p.title for p in described] == ["Package 0", "Package 1", "Package 2"]
    assert [p.items for p in described] == [p.items for p in plain]


async def test_claude_failure_keeps_the_catalogue_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue = _catalogue()
    researcher = ClaudeCliResearcher(catalogue, timeout_s=1)

    async def broken(_prompt: str) -> bytes:
        raise TimeoutError

    monkeypatch.setattr(researcher, "_run", broken)
    assert await researcher.research(BRIEF) == await catalogue.research(BRIEF)
    assert "PKP Intercity" in offers_json(await catalogue.research(BRIEF))
