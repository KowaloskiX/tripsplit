"""A trip from one sentence: the deterministic brief parser (Polish + English), the Claude
reader that fills what it missed, and `POST /api/trips/quick` (questions for what is
missing, then a trip with research running)."""

import json
from datetime import date

import pytest
from fastapi import FastAPI

from app.ai.claude_brief import ClaudeCliBriefReader, merge, parse_reading
from app.ai.quick_brief import (
    EN_DASH,
    QuickAnswers,
    QuickField,
    apply_answers,
    dates_of,
    parse_quick_brief,
    questions_for,
    reply_for,
)
from app.core.domain.trips import TransportMode, TripStatus
from app.services.quick_trips import name_from_email
from tests.test_trips_flow import (  # noqa: F401 — `member_factory` is a pytest fixture
    MemberFactory,
    _room,
    _runner,
    member_factory,
)

TODAY = date(2026, 10, 31)  # a Saturday


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "weekend w Pradze dla 6, 20-22.11, do 700 zł/os, pociągiem",
            ("Warszawa", "Prague", date(2026, 11, 20), date(2026, 11, 22), 6, 70_000, "rail"),
        ),
        (
            "Barcelona for 4, Nov 20-23, flight, 3000 zł łącznie",
            ("Warszawa", "Barcelona", date(2026, 11, 20), date(2026, 11, 23), 4, 75_000, "flight"),
        ),
        (
            "z Krakowa do Wiednia 20\u201322 listopada, 6 osób",
            ("Kraków", "Vienna", date(2026, 11, 20), date(2026, 11, 22), 6, None, None),
        ),
        (
            "Warszawa - Praga next weekend dla dwojga",
            ("Warszawa", "Prague", date(2026, 11, 13), date(2026, 11, 15), 2, None, None),
        ),
        (
            "Lizbona 30.11-2.12 dla 2 samolotem, budżet 1,5k zł na osobę",
            ("Warszawa", "Lisbon", date(2026, 11, 30), date(2026, 12, 2), 2, 150_000, "flight"),
        ),
        (
            "Budapeszt 20 listopada, 3 noce, dla 8, autobusem",
            ("Warszawa", "Budapest", date(2026, 11, 20), date(2026, 11, 23), 8, None, "bus"),
        ),
        (
            "trip to Rome 2026-12-04/2026-12-07, we are 5, under 900 zł per person",
            ("Warszawa", "Rome", date(2026, 12, 4), date(2026, 12, 7), 5, 90_000, None),
        ),
        (
            "z Poznania do Sztokholmu 27-29.11 dla 4, samolotem",
            ("Poznań", "Stockholm", date(2026, 11, 27), date(2026, 11, 29), 4, None, "flight"),
        ),
        (
            "split the bill: Tallinn 20-22.11 for 2",
            ("Warszawa", "Tallinn", date(2026, 11, 20), date(2026, 11, 22), 2, None, None),
        ),
    ],
)
def test_the_parser_reads_polish_and_english_briefs(
    text: str, expected: tuple[object, ...]
) -> None:
    draft = parse_quick_brief(text, TODAY)
    mode = draft.transport_mode.value if draft.transport_mode else None
    assert (
        draft.origin,
        draft.destination,
        draft.date_from,
        draft.date_to,
        draft.group_size,
        draft.budget_per_person_minor,
        mode,
    ) == expected
    assert draft.complete


def test_a_vague_brief_asks_one_question_per_missing_essential() -> None:
    draft = parse_quick_brief("somewhere nice with friends", TODAY)
    questions = questions_for(draft, TODAY)
    assert [q.field for q in questions] == [
        QuickField.DESTINATION,
        QuickField.DATES,
        QuickField.GROUP_SIZE,
    ]
    party = questions[2]
    assert party.question == "How many people?"
    assert [o.value for o in party.options] == ["2", "4", "6", "8"]
    # Every date chip is something the parser reads back.
    for option in questions[1].options:
        assert dates_of(option.value, TODAY) is not None


def test_answers_fill_the_gaps_and_a_total_budget_becomes_per_person() -> None:
    draft = parse_quick_brief("Berlin, 3000 zł łącznie", TODAY)
    assert draft.budget_total_minor == 300_000
    assert draft.budget_per_person_minor is None
    answered = apply_answers(
        draft, QuickAnswers(dates="2026-11-20/2026-11-22", group_size=4), TODAY
    )
    assert answered.complete
    assert answered.budget_per_person_minor == 75_000
    assert answered.budget_total_minor is None


def test_explicit_answers_win_over_the_text() -> None:
    draft = parse_quick_brief("Prague for 6 by train, 20-22.11", TODAY)
    answered = apply_answers(
        draft,
        QuickAnswers(destination="Wiedeń", group_size=2, transport_mode=TransportMode.BUS),
        TODAY,
    )
    assert (answered.destination, answered.group_size, answered.transport_mode) == (
        "Vienna",
        2,
        TransportMode.BUS,
    )


def test_a_date_without_a_year_is_the_next_one_and_ranges_may_cross_the_year() -> None:
    assert dates_of("5-7.03", TODAY) == (date(2027, 3, 5), date(2027, 3, 7))
    assert dates_of("30.12-2.01", TODAY) == (date(2026, 12, 30), date(2027, 1, 2))
    assert dates_of("this weekend", TODAY) == (date(2026, 11, 6), date(2026, 11, 8))
    assert dates_of("no dates at all", TODAY) is None


def test_a_name_comes_from_the_email() -> None:
    assert name_from_email("anna.kowalska@example.com") == "Anna Kowalska"
    assert name_from_email("x9@example.com") == "Organizer"


async def test_quick_asks_then_creates_the_trip_and_researches(
    app: FastAPI,
    member_factory: MemberFactory,  # noqa: F811 — the fixture imported above
) -> None:
    organizer = await member_factory("anna.kowalska@example.com")
    first = await organizer.post("/api/trips/quick", {"text": "weekend w Pradze, pociągiem"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["trip"] is None
    assert body["draft"]["destination"] == "Prague"
    assert body["draft"]["transport_mode"] == "rail"
    assert sorted(body["draft"]["missing"]) == ["dates", "group_size"]
    assert body["reply"] == "Prague, by train, got it. Just tell me when and how many people."
    asked = {q["field"]: q for q in body["questions"]}
    dates = asked["dates"]["options"][1]["value"]

    second = await organizer.post(
        "/api/trips/quick",
        {"text": "weekend w Pradze, pociągiem", "dates": dates, "group_size": 6},
    )
    assert second.status_code == 200, second.text
    created = second.json()
    assert created["questions"] == []
    assert created["trip"]["status"] == TripStatus.PROPOSING
    trip_id = created["trip"]["trip_id"]

    await _runner(app).drain()
    room = await _room(organizer, trip_id)
    assert room["trip"]["status"] == TripStatus.VOTING
    assert room["trip"]["destination"] == "Prague"
    assert room["trip"]["group_size"] == 6
    assert room["trip"]["transport_mode"] == "rail"
    assert room["my_role"] == "organizer"
    assert room["members"][0]["display_name"] == "Anna Kowalska"
    assert room["proposals"]


async def test_quick_refuses_a_blank_brief(
    member_factory: MemberFactory,  # noqa: F811 — the fixture imported above
) -> None:
    organizer = await member_factory("blank@example.com")
    response = await organizer.post("/api/trips/quick", {"text": "   "})
    assert response.status_code == 422


def _envelope(reading: dict[str, object]) -> bytes:
    return json.dumps({"type": "result", "result": f"Sure:\n{json.dumps(reading)}"}).encode()


def test_the_rules_reply_says_what_was_understood_and_what_is_missing() -> None:
    assert reply_for(parse_quick_brief("weekend w Pradze, pociągiem", TODAY)) == (
        "Prague, by train, got it. Just tell me when and how many people."
    )
    assert reply_for(parse_quick_brief("hello", TODAY)) == (
        "Tell me where to, when and how many people."
    )
    assert reply_for(parse_quick_brief("Prague 20-22.11 for 6", TODAY)) == (
        f"Got it: Prague, 20{EN_DASH}22 Nov, 6 people. Looking for packages now."
    )


async def test_claude_fills_only_what_the_rules_missed(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = ClaudeCliBriefReader(timeout_s=1)
    draft = parse_quick_brief("Praga w grudniu, pociągiem", TODAY)
    assert draft.date_from is None

    async def read(prompt: str) -> bytes:
        assert "Praga w grudniu" in prompt
        return _envelope(
            {
                "destination": "Berlin",  # the rules already found Prague: ignored
                "date_from": "2026-12-04",
                "date_to": "2026-12-06",
                "transport_mode": "flight",  # the rules already found rail: ignored
                "reply": "Prague, 4-6 Dec. How many of you?",
            }
        )

    monkeypatch.setattr(reader, "_run", read)
    reading = await reader.read(draft, TODAY)
    assert reading.draft.destination == "Prague"
    assert (reading.draft.date_from, reading.draft.date_to) == (
        date(2026, 12, 4),
        date(2026, 12, 6),
    )
    assert reading.draft.transport_mode is TransportMode.RAIL
    assert reading.reply == "Prague, 4-6 Dec. How many of you?"


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [("2026-10-01", "2026-10-03"), ("2026-12-06", "2026-12-04"), ("2026-12-01", "2027-02-01")],
)
def test_claude_dates_in_the_past_backwards_or_too_long_are_dropped(
    date_from: str, date_to: str
) -> None:
    draft = parse_quick_brief("Prague for 6", TODAY)
    reading = parse_reading(
        _envelope({"date_from": date_from, "date_to": date_to, "reply": "When?"})
    )
    assert merge(draft, reading, TODAY).date_from is None


async def test_a_claude_failure_keeps_the_rules_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = ClaudeCliBriefReader(timeout_s=1)
    draft = parse_quick_brief("Praga w grudniu", TODAY)

    async def broken(_prompt: str) -> bytes:
        return b"not json"

    monkeypatch.setattr(reader, "_run", broken)
    reading = await reader.read(draft, TODAY)
    assert reading.draft == draft
    assert reading.reply == reply_for(draft)


async def test_a_complete_brief_never_calls_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = ClaudeCliBriefReader(timeout_s=1)

    async def unexpected(_prompt: str) -> bytes:
        raise AssertionError("Claude was asked about a complete brief")

    monkeypatch.setattr(reader, "_run", unexpected)
    reading = await reader.read(parse_quick_brief("Prague 20-22.11 for 6", TODAY), TODAY)
    assert reading.draft.complete
