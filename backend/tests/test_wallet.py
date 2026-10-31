"""The wallet: dummy top-ups, atomic ledger, paying a share from it and the trip pot."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.background import BackgroundRunner
from app.core.config import Settings, get_settings
from app.core.domain.result import Err, Ok
from app.core.domain.trips import TripStatus
from app.core.domain.wallet import (
    InsufficientFunds,
    PaymentMethod,
    TopUpFailure,
    WalletTransactionKind,
    WalletTransactionStatus,
    processor_declines,
    shortfall,
    top_up_for_shortfall,
    validate_top_up,
)
from app.core.http_security import CSRF_HEADER_NAME
from app.db.client import Database
from app.db.identifiers import to_object_id
from app.main import create_app
from app.services.auth import AuthService
from app.services.wallet import TopUpRequest, WalletService

PASSWORD = "correct-horse-battery-staple"
TRIP = {
    "title": "Weekend in Prague",
    "origin": "Warszawa",
    "brief": "weekend in Prague for 2 from Warsaw",
    "date_from": "2026-11-20",
    "date_to": "2026-11-22",
    "group_size": 2,
    "display_name": "Anna",
}


# ---- domain -----------------------------------------------------------------------------


def test_top_up_validation() -> None:
    assert (
        validate_top_up(99, PaymentMethod.BLIK, "123456", None) is TopUpFailure.AMOUNT_OUT_OF_RANGE
    )
    assert validate_top_up(1_000_001, PaymentMethod.CARD, None, "4242") is (
        TopUpFailure.AMOUNT_OUT_OF_RANGE
    )
    assert validate_top_up(100, PaymentMethod.BLIK, "12345", None) is TopUpFailure.INVALID_BLIK_CODE
    assert validate_top_up(100, PaymentMethod.CARD, None, None) is TopUpFailure.INVALID_CARD
    assert validate_top_up(100, PaymentMethod.WALLET, None, None) is TopUpFailure.INVALID_CARD
    assert validate_top_up(1_000_000, PaymentMethod.BLIK, "123456", None) is None
    assert processor_declines(PaymentMethod.BLIK, "000000", None)
    assert processor_declines(PaymentMethod.CARD, None, "0002")
    assert not processor_declines(PaymentMethod.CARD, None, "4242")


def test_shortfall_and_minimum_top_up() -> None:
    assert shortfall(5_000, 3_000) == 0
    assert shortfall(1_000, 3_000) == 2_000
    assert top_up_for_shortfall(0) == 0
    assert top_up_for_shortfall(40) == 100  # the processor's 1 zł minimum
    assert top_up_for_shortfall(2_000) == 2_000


# ---- service ----------------------------------------------------------------------------


async def _user(database: Database, settings: Settings, email: str) -> str:
    issued = await AuthService(database, settings).register(email, PASSWORD, email)
    assert isinstance(issued, Ok)
    return issued.value.user.id


async def _ledger_matches_balance(user_id: str, service: WalletService) -> None:
    view = await service.wallet(user_id)
    completed = sum(
        t.amount_minor for t in view.transactions if t.status is WalletTransactionStatus.COMPLETED
    )
    assert completed == view.balance_minor >= 0


async def test_top_up_is_pending_then_credited_once(database: Database, settings: Settings) -> None:
    runner = BackgroundRunner()
    service = WalletService(database, runner, confirm_delay_s=0)
    user = await _user(database, settings, "topup@example.com")

    started = await service.start_top_up(
        user, TopUpRequest(amount_minor=25_000, method=PaymentMethod.BLIK, blik_code="777123")
    )
    assert isinstance(started, Ok)
    assert started.value.status is WalletTransactionStatus.PENDING
    await runner.drain()
    status = await service.top_up_status(user, started.value.id)
    assert isinstance(status, Ok)
    assert status.value.status is WalletTransactionStatus.COMPLETED
    assert status.value.balance_after_minor == 25_000
    # A second confirmation of the same top-up credits nothing.
    entry_id = to_object_id(status.value.id)
    assert entry_id is not None
    assert await service._confirm(entry_id) is False
    assert await service.balance(user) == 25_000
    await _ledger_matches_balance(user, service)


async def test_declined_blik_and_card_leave_the_balance_alone(
    database: Database, settings: Settings
) -> None:
    service = WalletService(database, None, confirm_delay_s=0)
    user = await _user(database, settings, "declined@example.com")
    last_id = ""
    for request in (
        TopUpRequest(amount_minor=10_000, method=PaymentMethod.BLIK, blik_code="000000"),
        TopUpRequest(amount_minor=10_000, method=PaymentMethod.CARD, card_last4="0002"),
    ):
        started = await service.start_top_up(user, request)
        assert isinstance(started, Ok)
        status = await service.top_up_status(user, started.value.id)
        assert isinstance(status, Ok)
        assert status.value.status is WalletTransactionStatus.FAILED
        assert status.value.failure_reason == TopUpFailure.DECLINED
        last_id = started.value.id
    assert await service.balance(user) == 0
    # Somebody else's top-up does not exist for you.
    other = await _user(database, settings, "other@example.com")
    assert await service.top_up_status(other, last_id) == Err(TopUpFailure.NOT_FOUND)


async def test_concurrent_charges_never_overdraw(database: Database, settings: Settings) -> None:
    service = WalletService(database)
    user = await _user(database, settings, "race@example.com")
    await service.credit(user, 10_000, WalletTransactionKind.ADJUSTMENT)

    results = await asyncio.gather(*(service.charge(user, "0" * 24, 4_000) for _ in range(5)))
    assert sum(isinstance(r, Ok) for r in results) == 2
    refused = [r for r in results if isinstance(r, Err)]
    assert all(isinstance(r.error, InsufficientFunds) for r in refused)
    assert await service.balance(user) == 2_000
    await _ledger_matches_balance(user, service)


# ---- HTTP -------------------------------------------------------------------------------


@pytest.fixture
def wallet_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"payments": "wallet", "wallet_confirm_delay_s": 0})


@pytest.fixture
def wallet_app(wallet_settings: Settings, database: Database) -> Iterator[FastAPI]:
    application = create_app(wallet_settings)
    application.state.database = database
    application.dependency_overrides[get_settings] = lambda: wallet_settings
    yield application
    application.dependency_overrides.clear()


class Browser:
    def __init__(self, client: AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        token = self.client.cookies.get(self.settings.effective_csrf_cookie_name)
        assert token is not None
        return await self.client.post(path, json=body or {}, headers={CSRF_HEADER_NAME: token})

    async def get(self, path: str) -> Any:
        return await self.client.get(path)


@pytest.fixture
async def browsers(wallet_app: FastAPI, wallet_settings: Settings) -> AsyncIterator[list[Browser]]:
    made: list[Browser] = []
    for email in ("anna@example.com", "kuba@example.com"):
        client = AsyncClient(transport=ASGITransport(app=wallet_app), base_url="http://test")
        await client.get("/api/auth/session")
        browser = Browser(client, wallet_settings)
        registered = await browser.post(
            "/api/auth/register",
            {"email": email, "password": PASSWORD, "organization_name": email},
        )
        assert registered.status_code == 201, registered.text
        made.append(browser)
    yield made
    for browser in made:
        await browser.client.aclose()


async def _drain(app: FastAPI) -> None:
    runner: BackgroundRunner = app.state.background
    await runner.drain()


async def test_wallet_endpoints_top_up_and_history(
    wallet_app: FastAPI, browsers: list[Browser]
) -> None:
    anna = browsers[0]
    empty = (await anna.get("/api/wallet")).json()
    assert empty == {"balance_minor": 0, "currency": "PLN", "transactions": []}

    bad = await anna.post("/api/wallet/top-ups", {"amount_minor": 50, "method": "blik"})
    assert bad.status_code == 422
    no_code = await anna.post("/api/wallet/top-ups", {"amount_minor": 10_000, "method": "blik"})
    assert no_code.status_code == 422
    assert no_code.json()["code"] == TopUpFailure.INVALID_BLIK_CODE

    started = await anna.post(
        "/api/wallet/top-ups", {"amount_minor": 25_000, "method": "card", "card_last4": "4242"}
    )
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "pending"
    assert started.json()["reference"] == "Card •••• 4242"
    await _drain(wallet_app)
    polled = (await anna.get(f"/api/wallet/top-ups/{started.json()['id']}")).json()
    assert polled["status"] == "completed"

    wallet = (await anna.get("/api/wallet")).json()
    assert wallet["balance_minor"] == 25_000
    assert [t["kind"] for t in wallet["transactions"]] == ["top_up"]


async def _paying_trip(app: FastAPI, anna: Browser, kuba: Browser) -> tuple[str, int]:
    trip_id = (await anna.post("/api/trips", TRIP)).json()["trip_id"]
    code = (await anna.get(f"/api/trips/{trip_id}")).json()["invite_code"]
    await kuba.post("/api/trips/join", {"invite_code": code, "display_name": "Kuba"})
    await anna.post(f"/api/trips/{trip_id}/proposals/generate")
    await _drain(app)
    room = (await anna.get(f"/api/trips/{trip_id}")).json()
    for browser in (anna, kuba):
        await browser.post(
            f"/api/trips/{trip_id}/votes", {"proposal_id": room["proposals"][0]["id"]}
        )
    closed = await anna.post(f"/api/trips/{trip_id}/voting/close")
    assert closed.status_code == 200, closed.text
    room = (await anna.get(f"/api/trips/{trip_id}")).json()
    assert room["trip"]["status"] == TripStatus.PAYING
    return trip_id, room["my_contribution"]["amount_minor"]


async def test_paying_a_share_from_the_wallet_and_the_pot(
    wallet_app: FastAPI, browsers: list[Browser]
) -> None:
    anna, kuba = browsers
    trip_id, share = await _paying_trip(wallet_app, anna, kuba)

    short = await anna.post(f"/api/trips/{trip_id}/contributions/pay")
    assert short.status_code == 409
    assert short.json()["code"] == "insufficient_funds"
    assert short.json()["shortfall_minor"] == share

    # Anna tops up part of it first; top-up-and-pay covers exactly the rest.
    await anna.post(
        "/api/wallet/top-ups", {"amount_minor": 10_000, "method": "blik", "blik_code": "123456"}
    )
    await _drain(wallet_app)
    checkout = await anna.post(
        f"/api/trips/{trip_id}/contributions/top-up-and-pay",
        {"method": "blik", "blik_code": "654321"},
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["payment"] is None
    assert checkout.json()["top_up"]["amount_minor"] == share - 10_000
    await _drain(wallet_app)
    wallet = (await anna.get("/api/wallet")).json()
    assert wallet["balance_minor"] == 0
    assert [t["kind"] for t in wallet["transactions"]] == ["share_payment", "top_up", "top_up"]
    assert wallet["transactions"][0]["amount_minor"] == -share
    assert wallet["transactions"][0]["trip_title"] == TRIP["title"]

    # A declined BLIK pays nothing.
    declined = await kuba.post(
        f"/api/trips/{trip_id}/contributions/top-up-and-pay",
        {"method": "blik", "blik_code": "000000"},
    )
    assert declined.status_code == 200
    await _drain(wallet_app)
    room = (await kuba.get(f"/api/trips/{trip_id}")).json()
    assert room["my_contribution"]["paid_minor"] == 0

    # Kuba's wallet already covers it: paid at once.
    await kuba.post(
        "/api/wallet/top-ups", {"amount_minor": share, "method": "card", "card_last4": "4242"}
    )
    await _drain(wallet_app)
    paid = await kuba.post(
        f"/api/trips/{trip_id}/contributions/top-up-and-pay",
        {"method": "card", "card_last4": "4242"},
    )
    assert paid.json()["payment"]["all_paid"] is True
    assert paid.json()["top_up"] is None

    room = (await anna.get(f"/api/trips/{trip_id}")).json()
    assert room["trip"]["status"] == TripStatus.BOOKING
    total = room["trip"]["total_minor"]
    assert room["pot"] == {
        "collected_minor": total,
        "spent_minor": 0,
        "refunded_minor": 0,
        "held_minor": total,
    }


async def test_demo_pay_all_funds_seeded_members(
    wallet_app: FastAPI, browsers: list[Browser]
) -> None:
    anna = browsers[0]
    trip_id = (await anna.post("/api/trips", {**TRIP, "group_size": 3})).json()["trip_id"]
    await anna.post(f"/api/trips/{trip_id}/demo/seed-members", {"count": 2})
    await anna.post(f"/api/trips/{trip_id}/proposals/generate")
    await _drain(wallet_app)
    room = (await anna.get(f"/api/trips/{trip_id}")).json()
    pick = room["proposals"][0]["id"]
    await anna.post(f"/api/trips/{trip_id}/votes", {"proposal_id": pick})
    await anna.post(f"/api/trips/{trip_id}/demo/vote-all", {"proposal_id": pick})
    await anna.post(f"/api/trips/{trip_id}/voting/close")

    paid = await anna.post(f"/api/trips/{trip_id}/demo/pay-all")
    assert paid.json() == {"affected": 2}
    room = (await anna.get(f"/api/trips/{trip_id}")).json()
    assert room["paid_count"] == 2
    assert (
        room["pot"]["collected_minor"]
        == room["trip"]["total_minor"] - room["my_contribution"]["amount_minor"]
    )
