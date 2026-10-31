"""The simulated partner's OWN collections — as if they lived in the EMI's systems, not ours.

`partner_users`, `partner_wallets`, `partner_ledger`, `partner_cards`. TripSplit code never
queries them directly: it goes through `PaymentPartner`. They carry `owner_ref` strings, never
our `user_id`, because the partner keeps its records after a TripSplit account is deleted
(AML record retention is the licensed partner's obligation, not ours).
"""

from datetime import date, datetime
from typing import ClassVar

import pymongo
from beanie import Document
from pydantic import Field

from app.core.domain.escrow import CardStatus, KycLevel, KycStatus
from app.db.documents import utc_now
from app.payments.partner import LedgerKind, WalletOwnerKind


class PartnerUserRecord(Document):
    owner_ref: str
    partner_user_id: str
    kyc_level: KycLevel = KycLevel.NONE
    kyc_status: KycStatus = KycStatus.NOT_STARTED
    # Verification completes asynchronously at the partner: verified once this has passed.
    kyc_verifies_at: datetime | None = None
    legal_name: str | None = None
    birth_date: date | None = None
    # The document number is checked and forgotten; only its last four digits are kept.
    document_last4: str | None = None
    topped_up_minor: int = 0
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name: ClassVar[str] = "partner_users"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("owner_ref", 1)], unique=True, name="uq_partner_users_owner"),
        ]


class PartnerWalletRecord(Document):
    wallet_id: str
    owner_kind: WalletOwnerKind
    owner_ref: str
    currency: str
    # Never negative: every debit is a conditional `$inc` guarded by the balance.
    balance_minor: int = Field(default=0, ge=0)
    # Escrow only: payouts and card funding are refused until the net share transfers reach it.
    release_target_minor: int = 0
    funded_minor: int = 0
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name: ClassVar[str] = "partner_wallets"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("wallet_id", 1)], unique=True, name="uq_partner_wallets_id"),
            pymongo.IndexModel(
                [("owner_kind", 1), ("owner_ref", 1)],
                unique=True,
                name="uq_partner_wallets_owner",
            ),
        ]


class PartnerLedgerRecord(Document):
    entry_id: str
    kind: LedgerKind
    amount_minor: int = Field(gt=0)
    debit_wallet_id: str | None = None
    credit_wallet_id: str | None = None
    tag: str = ""
    reference: str = ""
    idempotency_key: str
    debit_balance_after_minor: int | None = None
    credit_balance_after_minor: int | None = None
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name: ClassVar[str] = "partner_ledger"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("entry_id", 1)], unique=True, name="uq_partner_ledger_id"),
            pymongo.IndexModel(
                [("idempotency_key", 1)], unique=True, name="uq_partner_ledger_idempotency"
            ),
            pymongo.IndexModel([("debit_wallet_id", 1)], name="ix_partner_ledger_debit"),
            pymongo.IndexModel([("credit_wallet_id", 1)], name="ix_partner_ledger_credit"),
        ]


class PartnerCardRecord(Document):
    card_id: str
    funding_wallet_id: str  # the escrow the card was funded from
    card_wallet_id: str  # the card's own reserve
    pan: str
    exp_month: int
    exp_year: int
    cvc: str
    limit_minor: int
    spent_minor: int = 0
    status: CardStatus = CardStatus.ACTIVE
    merchant_hint: str = ""
    expires_at: datetime
    idempotency_key: str
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name: ClassVar[str] = "partner_cards"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("card_id", 1)], unique=True, name="uq_partner_cards_id"),
            pymongo.IndexModel([("pan", 1)], unique=True, name="uq_partner_cards_pan"),
            pymongo.IndexModel(
                [("idempotency_key", 1)], unique=True, name="uq_partner_cards_idempotency"
            ),
            pymongo.IndexModel([("funding_wallet_id", 1)], name="ix_partner_cards_funding"),
        ]


PARTNER_DOCUMENTS = (PartnerUserRecord, PartnerWalletRecord, PartnerLedgerRecord, PartnerCardRecord)
