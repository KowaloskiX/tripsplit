"""The wallet documents: one balance per user and its append-only ledger.

Not tenant-owned: a wallet follows its user into trips of any organization, like
`traveller_profiles`. Every balance change is written together with its ledger entry in one
transaction (`WalletRepository`), so `balance_minor` always equals the sum of the completed
entries.
"""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import Field

from app.core.domain.wallet import (
    WALLET_CURRENCY,
    PaymentMethod,
    WalletTransactionKind,
    WalletTransactionStatus,
)
from app.db.documents import TimestampMixin, utc_now

REFERENCE_MAX_LENGTH = 120


class Wallet(TimestampMixin, Document):
    user_id: PydanticObjectId
    # Never negative: every debit is conditioned on `balance_minor >= amount`.
    balance_minor: int = Field(default=0, ge=0)
    currency: str = WALLET_CURRENCY
    # The member's e-money wallet at the payment partner ("wlt_…"); this document mirrors it.
    partner_wallet_id: str | None = None

    class Settings:
        name: ClassVar[str] = "wallets"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("user_id", 1)], unique=True, name="uq_wallets_user_id"),
        ]


class WalletTransaction(Document):
    user_id: PydanticObjectId
    kind: WalletTransactionKind
    # Signed: a credit (top-up, refund) is positive, a debit (share payment) negative.
    amount_minor: int
    # The balance right after this entry was applied; None while it is pending or if it failed.
    balance_after_minor: int | None = None
    trip_id: PydanticObjectId | None = None
    method: PaymentMethod
    status: WalletTransactionStatus
    # Human-readable: "BLIK", "Card •••• 4242", the trip title.
    reference: str = Field(default="", max_length=REFERENCE_MAX_LENGTH)
    # A pending top-up made to pay a share: once credited, that trip's share is paid.
    pay_trip_on_completion: bool = False
    failure_reason: str | None = None
    # The partner movement this entry mirrors ("txn_…"); unique, so a replay mirrors once.
    partner_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    class Settings:
        name: ClassVar[str] = "wallet_transactions"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel(
                [("user_id", 1), ("created_at", -1)], name="ix_wallet_transactions_history"
            ),
            pymongo.IndexModel(
                [("trip_id", 1), ("kind", 1)], name="ix_wallet_transactions_trip_kind"
            ),
            pymongo.IndexModel(
                [("partner_ref", 1)],
                unique=True,
                partialFilterExpression={"partner_ref": {"$type": "string"}},
                name="uq_wallet_transactions_partner_ref",
            ),
        ]
