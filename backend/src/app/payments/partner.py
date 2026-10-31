"""The payment-partner port: everything a licensed EMI/PI (Mangopay, Stripe Connect + Issuing)
does for TripSplit, in the partner's own vocabulary — users with a KYC level, e-money wallets,
pay-ins, wallet-to-wallet transfers, payouts, refunds and single-use virtual cards.

TripSplit never holds client money: it instructs the partner and mirrors the outcome. Swapping
the simulated `FakePartner` for a real provider is one adapter behind this Protocol.

Every money call carries an idempotency key: replaying it returns the first result and moves
nothing twice — the same contract Mangopay and Stripe give for retried requests.

Domain-pure on purpose: no database or framework types cross this boundary.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from app.core.domain.escrow import CardStatus, KycLevel, KycStatus
from app.core.domain.result import Result


class WalletOwnerKind(StrEnum):
    USER = "user"  # a member's e-money wallet
    TRIP_ESCROW = "trip_escrow"  # held by the partner on the organizer's behalf, one per trip
    CARD = "card"  # the funding behind one virtual card


class LedgerKind(StrEnum):
    PAY_IN = "pay_in"  # BLIK / card -> user wallet
    TRANSFER = "transfer"  # wallet -> wallet (share payments, refunds)
    PAYOUT = "payout"  # escrow -> supplier bank account
    PAYOUT_REVERSAL = "payout_reversal"  # the supplier returns a payout (cancelled booking)
    CARD_FUNDING = "card_funding"  # escrow -> card (the card's limit is reserved)
    CARD_CAPTURE = "card_capture"  # card -> merchant (the agent paid on the site)
    CARD_RELEASE = "card_release"  # unused card funds -> back to the escrow
    CARD_REFUND = "card_refund"  # the merchant refunds a card charge into the escrow


class TransferTag(StrEnum):
    SHARE = "share"  # member wallet -> trip escrow
    REFUND = "refund"  # escrow -> member wallet (overpayment after a cheaper rebooking)
    DEADLINE_REFUND = "deadline_refund"  # escrow -> member wallet (funding deadline missed)
    LEFTOVER = "leftover"  # escrow -> member wallet (rounding left at BOOKED, pro rata)


class PayInMethod(StrEnum):
    BLIK = "blik"
    CARD = "card"
    # A demo/back-office credit (seeded money, migration of a pre-partner balance).
    ADJUSTMENT = "adjustment"


class PartnerError(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    KYC_REQUIRED = "kyc_required"
    DECLINED = "payment_declined"
    WALLET_NOT_FOUND = "wallet_not_found"
    CARD_NOT_FOUND = "card_not_found"
    # Rule #1 at the partner layer: an escrow releases nothing before it is 100% funded.
    ESCROW_NOT_FUNDED = "escrow_not_funded"
    CARD_DECLINED = "card_declined"
    UNAVAILABLE = "partner_unavailable"  # injected outage (harness)


class PartnerOp(StrEnum):
    """Operations the fake partner can be told to fail (failure injection)."""

    PAY_IN = "pay_in"
    TRANSFER = "transfer"
    PAYOUT = "payout"
    ISSUE_CARD = "issue_card"
    CHARGE_CARD = "charge_card"


@dataclass(frozen=True, slots=True)
class PartnerUser:
    owner_ref: str
    partner_user_id: str  # "usr_…"
    kyc_level: KycLevel
    kyc_status: KycStatus
    topped_up_minor: int  # cumulative pay-ins, for the KYC threshold
    kyc_limit_minor: int


@dataclass(frozen=True, slots=True)
class KycSubmission:
    """What "ID verification" sends. The document number is checked and forgotten — the
    partner keeps its last four digits only."""

    legal_name: str
    birth_date: date
    document_number: str | None = None


@dataclass(frozen=True, slots=True)
class PayInInstrument:
    """The payer's instrument for one pay-in. The BLIK code and the card digits are used for
    the authorization and never stored."""

    method: PayInMethod
    blik_code: str | None = None
    card_last4: str | None = None


@dataclass(frozen=True, slots=True)
class Movement:
    """One ledger entry at the partner, as the partner reports it."""

    id: str  # "txn_…", "po_…" for a payout
    kind: LedgerKind
    amount_minor: int
    debit_wallet_id: str | None  # None = money enters from outside (pay-in, reversal)
    credit_wallet_id: str | None  # None = money leaves to the outside (payout, capture)
    tag: str
    reference: str
    created_at: datetime
    # The wallets' balances right after this movement (for the caller's mirror).
    debit_balance_after_minor: int | None = None
    credit_balance_after_minor: int | None = None


@dataclass(frozen=True, slots=True)
class SupplierAccount:
    """Where a payout goes. A real partner needs the supplier's verified bank account; the
    simulation needs a name."""

    supplier_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class VirtualCard:
    card_id: str  # "card_…"
    pan_last4: str
    exp_month: int
    exp_year: int
    limit_minor: int
    spent_minor: int
    status: CardStatus
    merchant_hint: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CardSecrets:
    """The full card details — revealed once, straight into the agent's private vault (like
    Stripe Issuing's PCI-scoped retrieval). Never logged, never stored by TripSplit."""

    pan: str
    exp_month: int
    exp_year: int
    cvc: str


@dataclass(frozen=True, slots=True)
class CardCharge:
    """A merchant's charge on a virtual card (what the card network sends)."""

    pan: str
    exp_month: int
    exp_year: int
    cvc: str
    amount_minor: int
    merchant: str


class PaymentPartner(Protocol):
    # ---- users and KYC --------------------------------------------------------------------
    async def ensure_user(self, owner_ref: str) -> PartnerUser: ...

    async def submit_kyc(self, owner_ref: str, submission: KycSubmission) -> PartnerUser:
        """Starts ID verification; the user is verified shortly after (async at the partner)."""
        ...

    # ---- wallets --------------------------------------------------------------------------
    async def create_wallet(
        self, owner_kind: WalletOwnerKind, owner_ref: str, currency: str
    ) -> str:
        """Idempotent per owner: the same owner always gets the same "wlt_…" id."""
        ...

    async def balance(self, wallet_id: str) -> int: ...

    async def statement(self, wallet_id: str) -> list[Movement]:
        """Every movement touching the wallet, oldest first."""
        ...

    async def set_release_target(self, wallet_id: str, target_minor: int) -> None:
        """An escrow pays out / funds cards only once its net share transfers reach this."""
        ...

    # ---- money ----------------------------------------------------------------------------
    async def pay_in(
        self,
        wallet_id: str,
        amount_minor: int,
        instrument: PayInInstrument,
        *,
        owner_ref: str,
        idempotency_key: str,
    ) -> Result[Movement, PartnerError]:
        """BLIK / card into a user wallet. The authorization is asynchronous at the partner;
        this resolves once it is confirmed (or declined)."""
        ...

    async def transfer(
        self,
        from_wallet: str,
        to_wallet: str,
        amount_minor: int,
        tag: TransferTag,
        *,
        reference: str,
        idempotency_key: str,
    ) -> Result[Movement, PartnerError]: ...

    async def payout(
        self,
        from_wallet: str,
        supplier: SupplierAccount,
        amount_minor: int,
        *,
        reference: str,
        idempotency_key: str,
    ) -> Result[Movement, PartnerError]: ...

    async def reverse_payout(
        self, payout_id: str, *, idempotency_key: str
    ) -> Result[Movement, PartnerError]:
        """The supplier sends a payout back (the booking was cancelled by the supplier)."""
        ...

    # ---- virtual cards --------------------------------------------------------------------
    async def issue_virtual_card(
        self,
        from_wallet: str,
        amount_minor: int,
        merchant_hint: str,
        expires_in: timedelta,
        *,
        idempotency_key: str,
    ) -> Result[VirtualCard, PartnerError]:
        """A new single-use card with a limit of exactly `amount_minor`, INACTIVE: nothing is
        reserved and every charge is declined until `activate_card`."""
        ...

    async def activate_card(
        self, card_id: str, *, idempotency_key: str
    ) -> Result[VirtualCard, PartnerError]:
        """Funds the card from its escrow (Rule #1: only a 100% funded escrow) and activates it."""
        ...

    async def reveal_card(self, card_id: str) -> CardSecrets | None: ...

    async def charge_card(
        self, charge: CardCharge, *, idempotency_key: str
    ) -> Result[Movement, PartnerError]:
        """The card network: approves a charge within the limit of an active, unexpired card,
        then closes the card (single use) and releases what was not spent."""
        ...

    async def close_card(self, card_id: str) -> VirtualCard | None:
        """Closes the card (if still active) and releases its unused funds to the escrow."""
        ...

    async def card_status(self, card_id: str) -> VirtualCard | None: ...

    async def cards_funded_by(self, wallet_id: str) -> list[VirtualCard]:
        """Every card funded from `wallet_id` (an escrow), oldest first."""
        ...

    async def refund_card_charge(
        self, card_id: str, *, idempotency_key: str
    ) -> Result[Movement, PartnerError]:
        """The merchant refunds a captured card charge straight into the funding escrow."""
        ...
