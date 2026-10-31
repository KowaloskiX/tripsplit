"""`uv run seed-demo`: the demo account and its 5 000 zł wallet, idempotently, dev/test only."""

import pytest

from app.core.config import Settings
from app.db.client import Database
from app.payments.partner import WalletOwnerKind
from app.services.demo_account import DEMO_WALLET_MINOR, SeedRefusedError, seed_demo
from app.services.wallet import WalletService


async def test_seed_demo_is_idempotent(database: Database, settings: Settings) -> None:
    first = await seed_demo(database, settings)
    assert first.created and first.topped_up_minor == DEMO_WALLET_MINOR
    assert first.balance_minor == DEMO_WALLET_MINOR

    wallet = WalletService(database)
    escrow = await wallet.partner.create_wallet(WalletOwnerKind.TRIP_ESCROW, "trip:seed", "PLN")
    await wallet.charge(first.user_id, "", 100_000, to_wallet=escrow, idempotency_key="seed:1")
    again = await seed_demo(database, settings)
    assert not again.created and again.user_id == first.user_id
    assert again.topped_up_minor == 100_000
    assert again.balance_minor == DEMO_WALLET_MINOR

    third = await seed_demo(database, settings)
    assert third.topped_up_minor == 0


async def test_seed_demo_refuses_outside_dev_and_test(
    database: Database, settings: Settings
) -> None:
    prod = settings.model_copy(update={"app_env": "prod"})
    with pytest.raises(SeedRefusedError):
        await seed_demo(database, prod)
