"""Pays shares from the member's e-money wallet INTO the trip escrow, and refunds out of it.

Both wallets live at the payment partner (`PaymentPartner`, simulated by `FakePartner`): a
share is a partner transfer member wallet -> trip escrow, a refund the reverse. TripSplit only
instructs and mirrors — it never holds the money.
"""

from app.core.domain.result import Err, Ok, Result
from app.core.domain.wallet import InsufficientFunds
from app.payments.partner import TransferTag
from app.payments.ports import PaymentReceipt, RefundReceipt
from app.services.escrow import EscrowService


class WalletPayments:
    def __init__(self, escrow: EscrowService) -> None:
        self.escrow = escrow

    async def charge(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> Result[PaymentReceipt, InsufficientFunds]:
        charged = await self.escrow.collect(trip_id, user_id, amount_minor)
        if isinstance(charged, Err):
            return charged
        return Ok(PaymentReceipt(provider_ref=f"wallet_{charged.value}", paid_minor=amount_minor))

    async def refund(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> RefundReceipt:
        refunded = await self.escrow.refund(
            trip_id, user_id, amount_minor, TransferTag.REFUND, "Trip refund"
        )
        if isinstance(refunded, Err):
            # The escrow could not pay it back (it should always hold overpayments): nothing
            # moved, so nothing is reported as refunded.
            return RefundReceipt(provider_ref=f"refund_failed_{refunded.error}", refunded_minor=0)
        return RefundReceipt(
            provider_ref=f"wallet_refund_{refunded.value}", refunded_minor=amount_minor
        )
