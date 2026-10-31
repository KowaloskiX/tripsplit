"""The money moved to a (simulated) licensed payment partner: member wallets mirror partner
e-money wallets, every trip gets an escrow wallet and a pay-by deadline, and every booking
records how the escrow paid it.

Expand-contract:
1. Expand (shipped with this migration's code): every new field defaults to None / 0, so the
   new code reads old documents before any backfill. A legacy wallet balance is carried over
   to the partner once, on first use (`WalletService.partner_wallet_id`).
2. Backfill (this file): the new keys are written on every document that lacks them, because
   the collection validators (`app.db.validation`) require every model field to be PRESENT and
   strict validation applies to updates of old documents too.
3. Contract: nothing to drop — `Backward` removes the keys again for the previous code.

    uv run beanie migrate -uri "$MONGODB_URL" -db "$MONGODB_DATABASE" -p migrations
"""

from typing import Any

from beanie import free_fall_migration
from pymongo.asynchronous.client_session import AsyncClientSession

from app.models.bookings import Booking
from app.models.trips import Trip
from app.models.wallet import Wallet, WalletTransaction

NEW_FIELDS: tuple[tuple[type[Any], dict[str, Any]], ...] = (
    (Trip, {"escrow_wallet_id": None, "pay_by": None}),
    (
        Booking,
        {"payment_kind": None, "payment_ref": None, "card_last4": None, "payment_attempts": 0},
    ),
    (Wallet, {"partner_wallet_id": None}),
    (WalletTransaction, {"partner_ref": None}),
)
MODELS = [model for model, _ in NEW_FIELDS]


class Forward:
    @free_fall_migration(document_models=MODELS)
    async def escrow_fields(self, session: AsyncClientSession | None) -> None:
        for model, defaults in NEW_FIELDS:
            # ONE update per document: strict validation checks the result of each update.
            await model.get_pymongo_collection().update_many(
                {"$or": [{name: {"$exists": False}} for name in defaults]},
                [
                    {
                        "$set": {
                            name: {"$ifNull": [f"${name}", {"$literal": default}]}
                            for name, default in defaults.items()
                        }
                    }
                ],
                session=session,
                hint=[("_id", 1)],
                # Only keys with their defaults are added. Without the bypass, an old document
                # still missing an EARLIER migration's keys would fail today's validator.
                bypass_document_validation=True,
            )


class Backward:
    @free_fall_migration(document_models=MODELS)
    async def no_escrow_fields(self, session: AsyncClientSession | None) -> None:
        for model, defaults in NEW_FIELDS:
            await model.get_pymongo_collection().update_many(
                {"$or": [{name: {"$exists": True}} for name in defaults]},
                {"$unset": dict.fromkeys(defaults, "")},
                session=session,
                hint=[("_id", 1)],
                bypass_document_validation=True,
            )
