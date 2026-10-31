"""Traveller details over HTTP: a member sets their own, the document number is write-only,
and the room shows every member's completeness against what the trip's suppliers need."""

from typing import Any

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.domain.suppliers import TravellerField
from tests.test_trips_flow import (  # noqa: F401 — `member_factory` is a pytest fixture
    MemberFactory,
    _create_trip,
    _research,
    _room,
    member_factory,
)

PATH = "/api/me/traveller-details"
PASSPORT: dict[str, Any] = {
    "full_name": "Anna Maria Kowalska",
    "date_of_birth": "1990-05-01",
    "nationality": "pl",
    "document_number": "eh 123 4567",
    "document_expiry": "2031-01-01",
    "gender": "female",
}


async def test_a_member_sets_their_own_details_and_never_reads_the_number_back(
    member_factory: MemberFactory,  # noqa: F811 — the fixture imported above
) -> None:
    anna = await member_factory("anna@example.com")
    empty = await anna.get(PATH)
    assert empty.status_code == 200, empty.text
    assert empty.json()["provided"] == []

    saved = await anna.put(PATH, PASSPORT)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["document_number_masked"] == "*******67"
    assert body["nationality"] == "PL"
    assert "EH1234567" not in saved.text
    assert set(body["provided"]) == {field.value for field in TravellerField}

    partial = await anna.put(PATH, {"nationality": "DE"})
    assert partial.json()["document_number_masked"] == "*******67"  # left as it was
    assert partial.json()["nationality"] == "DE"


async def test_invalid_details_are_rejected_without_echoing_them(
    member_factory: MemberFactory,  # noqa: F811
) -> None:
    anna = await member_factory("anna@example.com")
    for wrong in (
        {"document_number": "!!"},
        {"nationality": "POL"},
        {"date_of_birth": "2999-01-01"},
        {"document_expiry": "2001-01-01"},
        {"full_name": "Anna"},
        {"document_number": {"$ne": None}},
        {"user_id": "someone else"},
    ):
        response = await anna.put(PATH, wrong)
        assert response.status_code == 422, (wrong, response.text)
    leaked = await anna.put(PATH, {"document_number": "SECRET-1234567890-LONG"})
    assert leaked.status_code == 422
    assert "SECRET" not in leaked.text


async def test_the_room_shows_who_lacks_what_the_suppliers_need(
    app: FastAPI,
    settings: Settings,
    member_factory: MemberFactory,  # noqa: F811
) -> None:
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"suppliers": "sim_flight,sim_stay,sim_activity"}
    )
    organizer = await member_factory("organizer@example.com")
    trip_id = await _create_trip(
        organizer, title="Barcelona", destination="Barcelona", display_name="Anna Kowalska"
    )
    before = (await _room(organizer, trip_id))["members"][0]
    assert before["traveller_details_complete"] is True  # nothing on the table needs more yet

    await _research(app, organizer, trip_id)
    (me,) = (await _room(organizer, trip_id))["members"]
    assert me["traveller_details_complete"] is False
    assert set(me["traveller_details_missing"]) == {
        "date_of_birth",
        "document_number",
        "nationality",
    }
    assert (await organizer.put(PATH, PASSPORT)).status_code == 200
    (me,) = (await _room(organizer, trip_id))["members"]
    assert me["traveller_details_complete"] is True
    room = await organizer.get(f"/api/trips/{trip_id}")
    assert "EH1234567" not in room.text
