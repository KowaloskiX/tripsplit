"""The money model in production shape: a licensed payment partner (an EMI, Mangopay-style)
holds every zloty — members' e-money wallets, one escrow wallet per trip, payouts to suppliers
and single-use virtual cards for the agent. TripSplit itself never holds client money; it only
instructs the partner and mirrors what the partner reports.

Pure rules here: KYC thresholds, the funding deadline, card limits, pro-rata leftovers and the
escrow arithmetic the harness checks. No framework, no database.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

# Cumulative top-ups above this need "ID verification" (KYC light). 1 000 zł by default;
# overridden by `KYC_LIGHT_LIMIT_MINOR`.
DEFAULT_KYC_LIGHT_LIMIT_MINOR = 100_000
# The trip must be 100% funded this long after voting closed, unless the organizer sets
# another deadline.
DEFAULT_PAY_BY = timedelta(hours=48)
# A single-use virtual card for an agent purchase lives this long (it is issued when the agent
# starts and funded at the approval), then closes itself.
DEFAULT_CARD_TTL = timedelta(hours=24)
# The card limit is EXACTLY the purchase amount: +0% tolerance.
CARD_TOLERANCE_PERCENT = 0
# The legal entity shown in the UI: a simulated licensed partner.
PARTNER_DISPLAY_NAME = "Razor Trip Pay"


class KycLevel(StrEnum):
    NONE = "none"
    LIGHT = "light"  # name + date of birth checked ("ID verification")


class KycStatus(StrEnum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"


class PurchasePayment(StrEnum):
    """How the escrow paid one booking."""

    PAYOUT = "payout"  # API supplier: a payout from the escrow to the supplier
    VIRTUAL_CARD = "virtual_card"  # agent supplier: a single-use card funded from the escrow


class CardStatus(StrEnum):
    # Issued when the agent starts (its details go into the agent's vault), but unfunded:
    # every charge is declined until the human approves the purchase.
    INACTIVE = "inactive"
    ACTIVE = "active"  # approved: exactly the purchase amount is reserved on it
    USED = "used"  # charged once, then closed automatically
    CLOSED = "closed"  # closed unused (run over, rejected, expired)


class FundingExpiry(StrEnum):
    """Why a trip's escrow was unwound."""

    DEADLINE_MISSED = "deadline_missed"


def needs_kyc(topped_up_minor: int, amount_minor: int, limit_minor: int, level: KycLevel) -> bool:
    """Cumulative top-ups would cross the light-KYC threshold without verification."""
    return level is KycLevel.NONE and topped_up_minor + amount_minor > limit_minor


def kyc_remaining_minor(topped_up_minor: int, limit_minor: int, level: KycLevel) -> int | None:
    """How much more may be topped up before KYC; None = no limit (verified)."""
    if level is not KycLevel.NONE:
        return None
    return max(0, limit_minor - topped_up_minor)


def default_pay_by(voting_closed_at: datetime) -> datetime:
    return voting_closed_at + DEFAULT_PAY_BY


def deadline_missed(pay_by: datetime | None, now: datetime, fully_paid: bool) -> bool:
    return pay_by is not None and not fully_paid and now >= pay_by


def card_limit_minor(purchase_minor: int) -> int:
    """The card's spending limit for one purchase — never above its amount (+0%)."""
    return purchase_minor + purchase_minor * CARD_TOLERANCE_PERCENT // 100


def card_declines(
    limit_minor: int, amount_minor: int, status: CardStatus, expired: bool
) -> str | None:
    """Why the card network declines a charge; None = approved."""
    if status is CardStatus.INACTIVE:
        return "card_inactive"
    if status is not CardStatus.ACTIVE:
        return "card_closed"
    if expired:
        return "card_expired"
    if amount_minor <= 0 or amount_minor > limit_minor:
        return "amount_over_limit"
    return None


def pro_rata(total_minor: int, weights: list[int]) -> list[int]:
    """Splits `total_minor` in proportion to `weights` (largest remainder): the parts always
    sum exactly to the total. All-zero weights get nothing."""
    weight_sum = sum(weights)
    if total_minor <= 0 or weight_sum <= 0:
        return [0 for _ in weights]
    exact = [total_minor * weight for weight in weights]
    parts = [value // weight_sum for value in exact]
    remainders = sorted(
        range(len(weights)), key=lambda index: exact[index] % weight_sum, reverse=True
    )
    for index in remainders[: total_minor - sum(parts)]:
        parts[index] += 1
    return parts


@dataclass(frozen=True, slots=True)
class EscrowTotals:
    """The trip escrow from the partner's statement."""

    collected_minor: int  # share transfers in from member wallets
    paid_to_suppliers_minor: int  # payouts + card spends, net of supplier refunds
    refunded_minor: int  # transfers back to member wallets
    reserved_minor: int  # sitting on active virtual cards
    balance_minor: int  # the escrow wallet itself

    @property
    def held_minor(self) -> int:
        """What the partner still holds for the trip (wallet + live card reserves)."""
        return self.balance_minor + self.reserved_minor

    @property
    def expected_held_minor(self) -> int:
        return self.collected_minor - self.paid_to_suppliers_minor - self.refunded_minor
