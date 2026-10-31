"""The payment port. The domain asks for money and gets a receipt; who moves it is a detail.

Stripe arrives later behind this exact signature — the contribution service does not change.
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.domain.result import Result
from app.core.domain.wallet import InsufficientFunds


@dataclass(frozen=True, slots=True)
class PaymentReceipt:
    # The provider's reference ("fake_…" today, a Stripe id later), stored on the contribution.
    provider_ref: str
    paid_minor: int


@dataclass(frozen=True, slots=True)
class RefundReceipt:
    # The provider's reference of the refund ("fake_refund_…" today, a Stripe refund id later).
    provider_ref: str
    refunded_minor: int


class PaymentProvider(Protocol):
    async def charge(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> Result[PaymentReceipt, InsufficientFunds]:
        """Takes the money, or says how much is missing (a wallet that cannot cover it)."""
        ...

    async def refund(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> RefundReceipt: ...
