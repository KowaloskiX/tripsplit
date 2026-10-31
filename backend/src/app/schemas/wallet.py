"""Wallet schemas: the balance, the ledger and dummy top-ups.

A card never travels in full: the browser checks the (test) number and sends the last four
digits only. A BLIK code is checked and forgotten — neither is stored.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.domain.escrow import KycLevel, KycStatus
from app.core.domain.wallet import (
    MAX_TOP_UP_MINOR,
    MIN_TOP_UP_MINOR,
    PaymentMethod,
    WalletTransactionKind,
    WalletTransactionStatus,
)
from app.core.errors_http import ErrorResponse
from app.schemas.common import StrictRequest
from app.schemas.trips import PaymentResponse

type TopUpMethodField = Literal["blik", "card"]
BLIK_CODE = r"^\d{6}$"
CARD_LAST4 = r"^\d{4}$"


class _ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TopUpRequest(StrictRequest):
    amount_minor: int = Field(ge=MIN_TOP_UP_MINOR, le=MAX_TOP_UP_MINOR)
    method: TopUpMethodField
    blik_code: str | None = Field(default=None, pattern=BLIK_CODE)
    card_last4: str | None = Field(default=None, pattern=CARD_LAST4)


class TopUpAndPayRequest(StrictRequest):
    """Tops the wallet up by exactly what the share is missing, then pays the share."""

    method: TopUpMethodField
    blik_code: str | None = Field(default=None, pattern=BLIK_CODE)
    card_last4: str | None = Field(default=None, pattern=CARD_LAST4)


class WalletTransactionResponse(_ReadModel):
    id: str
    kind: WalletTransactionKind
    # Signed: credits positive, debits negative.
    amount_minor: int
    balance_after_minor: int | None
    trip_id: str | None
    trip_title: str | None
    method: PaymentMethod
    status: WalletTransactionStatus
    reference: str
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None


class KycResponse(_ReadModel):
    level: KycLevel
    status: KycStatus
    # Cumulative top-ups above this need ID verification (KYC light).
    limit_minor: int
    topped_up_minor: int
    # How much more may be topped up unverified; null once verified.
    remaining_minor: int | None
    # The document's last four digits, masked ("•••• 1234") — the number is never stored.
    document_masked: str | None = None


class KycRequest(StrictRequest):
    """ "ID verification" (simulated): verified about a second later. The document number is
    optional, passed to the partner, never stored by TripSplit."""

    legal_name: str = Field(min_length=2, max_length=120)
    birth_date: date
    document_number: str | None = Field(default=None, max_length=40)


class WalletResponse(_ReadModel):
    balance_minor: int
    currency: str
    # The newest 50, newest first.
    transactions: list[WalletTransactionResponse]
    kyc: KycResponse
    # Who really holds the money: the (simulated) licensed payment partner.
    held_by: str
    partner_wallet_id: str | None


class CheckoutResponse(_ReadModel):
    """`payment` when the wallet covered the share right away; otherwise `top_up` is pending
    and the share is paid as soon as the bank confirms it (poll the top-up, then the room)."""

    payment: PaymentResponse | None
    top_up: WalletTransactionResponse | None


class InsufficientFundsResponse(ErrorResponse):
    # Present with code `insufficient_funds`: how much the wallet is short.
    shortfall_minor: int | None = None
