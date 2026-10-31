""" "I'll pay for everyone" and AUTO_BOOK over HTTP: the organizer covers every outstanding share
from their wallet (one top-up of the whole shortfall), and the last payment starts every
purchase by itself — the organizer still approves the basket once."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.domain.trips import BookingStatus, EventKind, TripStatus
from app.core.http_security import CSRF_HEADER_NAME
from app.db.client import Database
from app.db.identifiers import to_object_id
from app.main import create_app
from app.models.bookings import Booking
from app.models.trips import TripEvent
from app.routes.dependencies import get_booking_service, get_supplier_registry
from app.services.bookings import BookingService
from tests.test_lifecycle import RecordingLauncher
from tests.test_wallet import (  # noqa: F401 — `browsers` is a pytest fixture
    Browser,
    _drain,
    _paying_trip,
    browsers,
)


@pytest.fixture
def wallet_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "payments": "wallet",
            "wallet_confirm_delay_s": 0,
            "auto_book": True,
            # Paying for everyone tops up several shares at once; KYC light has its own tests.
            "kyc_light_limit_minor": 100_000_000,
        }
    )


@pytest.fixture
def launcher() -> RecordingLauncher:
    return RecordingLauncher()


@pytest.fixture
def wallet_app(
    wallet_settings: Settings, database: Database, tmp_path: Any, launcher: RecordingLauncher
) -> Iterator[FastAPI]:
    application = create_app(wallet_settings)
    application.state.database = database
    application.dependency_overrides[get_settings] = lambda: wallet_settings

    def bookings() -> BookingService:
        return BookingService(
            database, launcher, tmp_path / "runs", suppliers=get_supplier_registry(wallet_settings)
        )

    application.dependency_overrides[get_booking_service] = bookings
    yield application
    application.dependency_overrides.clear()


async def _events(trip_id: str, kind: EventKind) -> list[TripEvent]:
    return await TripEvent.find(
        TripEvent.trip_id == to_object_id(trip_id), TripEvent.kind == kind
    ).to_list(50)


async def test_the_organizer_pays_every_share_and_the_trip_books_itself(
    wallet_app: FastAPI,
    browsers: list[Browser],  # noqa: F811 — the fixture imported above
    launcher: RecordingLauncher,
) -> None:
    anna, kuba = browsers
    for browser, name in ((anna, "Anna Kowalska"), (kuba, "Kuba Mazur")):
        token = browser.client.cookies.get(browser.settings.effective_csrf_cookie_name)
        assert token is not None
        named = await browser.client.put(
            "/api/me/traveller-details", json={"full_name": name}, headers={CSRF_HEADER_NAME: token}
        )
        assert named.status_code == 200, named.text
    trip_id, share = await _paying_trip(wallet_app, anna, kuba)

    refused = await kuba.post(
        f"/api/trips/{trip_id}/contributions/pay-all-shares",
        {"method": "blik", "blik_code": "123456"},
    )
    assert refused.status_code == 403, refused.text

    response = await anna.post(
        f"/api/trips/{trip_id}/contributions/pay-all-shares",
        {"method": "blik", "blik_code": "123456"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["shares"] == 2
    assert body["payments"] == [] and body["all_paid"] is False
    assert body["top_up"]["amount_minor"] == body["total_minor"] == 2 * share
    await _drain(wallet_app)

    room = (await anna.get(f"/api/trips/{trip_id}")).json()
    assert room["trip"]["status"] == TripStatus.BOOKING
    assert {c["status"] for c in room["contributions"]} == {"paid"}
    wallet = (await anna.get("/api/wallet")).json()
    assert wallet["balance_minor"] == 0
    assert [t["kind"] for t in wallet["transactions"]] == [
        "share_payment",
        "share_payment",
        "top_up",
    ]
    assert (await kuba.get("/api/wallet")).json()["transactions"] == []
    paid = await _events(trip_id, EventKind.CONTRIBUTION_PAID)
    assert any("paid Kuba's share" in event.message for event in paid)
    kuba_id = room["contributions"][1]["user_id"]
    assert {event.payload["for_user_id"] for event in paid} >= {kuba_id}

    # AUTO_BOOK: the purchases started by themselves after the last payment.
    messages = await _events(trip_id, EventKind.MESSAGE)
    assert any("Booking everything now" in event.message for event in messages)
    bookings = await Booking.find(Booking.trip_id == to_object_id(trip_id)).to_list(10)
    assert launcher.started  # the agent was asked to buy (and refused in tests)
    assert all(b.status is not BookingStatus.PENDING for b in bookings)

    again = await anna.post(
        f"/api/trips/{trip_id}/contributions/pay-all-shares",
        {"method": "blik", "blik_code": "123456"},
    )
    assert again.status_code == 409


async def test_a_covered_total_is_paid_at_once(
    wallet_app: FastAPI,
    browsers: list[Browser],  # noqa: F811 — the fixture imported above
) -> None:
    anna, kuba = browsers
    trip_id, share = await _paying_trip(wallet_app, anna, kuba)
    await anna.post(
        "/api/wallet/top-ups",
        {"amount_minor": 3 * share, "method": "card", "card_last4": "4242"},
    )
    await _drain(wallet_app)
    response = await anna.post(
        f"/api/trips/{trip_id}/contributions/pay-all-shares",
        {"method": "card", "card_last4": "4242"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["top_up"] is None
    assert len(body["payments"]) == 2
    assert body["all_paid"] is True
    assert (await anna.get("/api/wallet")).json()["balance_minor"] == share
