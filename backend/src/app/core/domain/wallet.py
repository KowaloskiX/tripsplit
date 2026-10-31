"""The wallet: a member's balance and its ledger. Money movement is simulated (BLIK and card
rails are dummies), but the accounting is real: every balance change is one ledger entry, the
balance never goes below zero and a top-up is credited exactly once.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

WALLET_CURRENCY = "PLN"
# Per top-up: 1 zł .. 10 000 zł.
MIN_TOP_UP_MINOR = 100
MAX_TOP_UP_MINOR = 1_000_000
# How many ledger entries `GET /api/wallet` returns.
HISTORY_LIMIT = 50
# The dummy BLIK code that the "bank" declines — so a demo can show a failed top-up.
DECLINED_BLIK_CODE = "000000"
# The dummy card that is declined (Stripe's "generic decline" test card ends with 0002).
DECLINED_CARD_LAST4 = "0002"
BLIK_CODE_PATTERN = re.compile(r"^\d{6}$")
CARD_LAST4_PATTERN = re.compile(r"^\d{4}$")


class WalletTransactionKind(StrEnum):
    TOP_UP = "top_up"
    SHARE_PAYMENT = "share_payment"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class PaymentMethod(StrEnum):
    BLIK = "blik"
    CARD = "card"
    WALLET = "wallet"


class WalletTransactionStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class WalletError(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"


class TopUpFailure(StrEnum):
    """Why a top-up was refused before (or by) the dummy processor."""

    AMOUNT_OUT_OF_RANGE = "top_up_amount_out_of_range"
    INVALID_BLIK_CODE = "invalid_blik_code"
    INVALID_CARD = "invalid_card"
    DECLINED = "payment_declined"
    NOT_FOUND = "top_up_not_found"
    # Cumulative top-ups would cross the KYC-light threshold: verify your ID first.
    KYC_REQUIRED = "kyc_required"


@dataclass(frozen=True, slots=True)
class InsufficientFunds:
    """A wallet charge refused: the balance is `shortfall_minor` short of the amount.

    Carries `value` like the error enums, so code reading an error code works unchanged."""

    shortfall_minor: int
    value: str = WalletError.INSUFFICIENT_FUNDS.value


def top_up_in_range(amount_minor: int) -> bool:
    return MIN_TOP_UP_MINOR <= amount_minor <= MAX_TOP_UP_MINOR


def validate_top_up(
    amount_minor: int, method: PaymentMethod, blik_code: str | None, card_last4: str | None
) -> TopUpFailure | None:
    """The checks a real PSP would do before showing "confirm in your bank app"."""
    if not top_up_in_range(amount_minor):
        return TopUpFailure.AMOUNT_OUT_OF_RANGE
    if method is PaymentMethod.BLIK:
        if blik_code is None or not BLIK_CODE_PATTERN.match(blik_code):
            return TopUpFailure.INVALID_BLIK_CODE
        return None
    if method is PaymentMethod.CARD:
        if card_last4 is None or not CARD_LAST4_PATTERN.match(card_last4):
            return TopUpFailure.INVALID_CARD
        return None
    # The wallet cannot top itself up.
    return TopUpFailure.INVALID_CARD


def processor_declines(
    method: PaymentMethod, blik_code: str | None, card_last4: str | None
) -> bool:
    """The dummy bank's answer: one magic BLIK code and one magic card are declined."""
    if method is PaymentMethod.BLIK:
        return blik_code == DECLINED_BLIK_CODE
    return card_last4 == DECLINED_CARD_LAST4


def shortfall(balance_minor: int, due_minor: int) -> int:
    """How much is missing to pay `due_minor` from `balance_minor` (0 = enough)."""
    return max(0, due_minor - balance_minor)


def top_up_for_shortfall(missing_minor: int) -> int:
    """A top-up covering `missing_minor`, raised to the processor's minimum."""
    return max(missing_minor, MIN_TOP_UP_MINOR) if missing_minor > 0 else 0


def held_minor(collected_minor: int, spent_minor: int, refunded_minor: int) -> int:
    """What the trip pot still holds: collected, minus bought, minus paid back."""
    return collected_minor - spent_minor - refunded_minor
