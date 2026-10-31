"""The supplier call log behind the mission-control terminal: paths without identifiers, calls
tagged with the trip they were made for, and `GET /trips/{id}/bookings/activity` for members."""

from datetime import date

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.suppliers.call_log import CALL_LOG, CallLog, redact_path, trip_context
from app.suppliers.duffel import DuffelConfig, DuffelSupplier
from app.suppliers.duffel_client import DuffelClient
from app.suppliers.ports import SearchRequest
from tests.duffel_fake import FakeDuffel
from tests.test_trips_flow import (  # noqa: F401 — `member_factory` is a pytest fixture
    MemberFactory,
    _create_trip,
    member_factory,
)

TRIP = "6720f0a1b2c3d4e5f6a7b8c9"


def test_paths_lose_every_identifier_and_the_query() -> None:
    assert redact_path("/air/orders/ord_00009hthhsUZ8W4LxQgkjo") == "/air/orders/{id}"
    assert redact_path("/air/offers/off_0000AxYz?return_available_services=true") == (
        "/air/offers/{id}"
    )
    assert redact_path("/bookings/OOXZCMgku1") == "/bookings/{id}"
    assert redact_path("/air/offer_requests") == "/air/offer_requests"
    assert redact_path("/rates/prebook") == "/rates/prebook"
    assert redact_path("https://api.liteapi.travel/v3.0/data/hotels?countryCode=CZ") == (
        "/v3.0/data/hotels"
    )


def test_calls_are_kept_per_trip_and_newest_last() -> None:
    log = CallLog(max_calls=3)
    log.record("duffel", "post", "/air/offer_requests", 201, 0.8)  # no trip: never shown
    with trip_context(TRIP):
        for status in (200, 422, None):
            log.record("liteapi", "GET", "/data/hotels", status, 0.25)
    calls = log.for_trip(TRIP)
    assert [call.status for call in calls] == [200, 422, None]
    assert calls[0].method == "GET" and calls[0].ms == 250
    assert log.for_trip(TRIP, limit=1)[0].status is None
    assert log.for_trip("someone-else") == []


async def test_a_duffel_search_is_recorded_for_the_trip() -> None:
    api = FakeDuffel()
    config = DuffelConfig(api_key=SecretStr("duffel_test_activity"))
    client = DuffelClient(config.api_key, transport=httpx.MockTransport(api.handle), backoff_s=0)
    duffel = DuffelSupplier(client, config)
    CALL_LOG.clear()
    with trip_context(TRIP):
        await duffel.search(SearchRequest("Warszawa", "Barcelona", date(2026, 11, 20), None, 2))
    calls = CALL_LOG.for_trip(TRIP)
    assert calls and calls[0].supplier_id == "duffel"
    assert calls[0].path == "/air/offer_requests"
    assert calls[0].status == 201


async def test_members_read_the_trips_activity_and_nobody_else(
    app: FastAPI,
    member_factory: MemberFactory,  # noqa: F811 — the fixture imported above
) -> None:
    organizer = await member_factory("terminal@example.com")
    stranger = await member_factory("stranger@example.com")
    trip_id = await _create_trip(organizer)
    CALL_LOG.clear()
    with trip_context(trip_id):
        CALL_LOG.record("duffel", "POST", "/air/orders/ord_0000SECRET1", 201, 1.234)

    response = await organizer.get(f"/api/trips/{trip_id}/bookings/activity")
    assert response.status_code == 200, response.text
    (call,) = response.json()
    assert call["supplier_id"] == "duffel"
    assert call["path"] == "/air/orders/{id}"
    assert (call["method"], call["status"], call["ms"]) == ("POST", 201, 1234)
    assert "SECRET" not in response.text

    hidden = await stranger.get(f"/api/trips/{trip_id}/bookings/activity")
    assert hidden.status_code == 404
