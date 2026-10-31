"""Pays shares from the member's platform wallet and refunds into it.

The money in the wallet arrives through dummy BLIK / card top-ups (`WalletService`), so no
real PSP is involved — but a share can only be paid with money the wallet really holds.
"""

from app.core.domain.result import Err, Ok, Result
from app.core.domain.wallet import InsufficientFunds, WalletTransactionKind
from app.payments.ports import PaymentReceipt, RefundReceipt
from app.services.wallet import WalletService


class WalletPayments:
    def __init__(self, wallet: WalletService) -> None:
        self.wallet = wallet

    async def charge(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> Result[PaymentReceipt, InsufficientFunds]:
        charged = await self.wallet.charge(user_id, trip_id, amount_minor)
        if isinstance(charged, Err):
            return charged
        return Ok(PaymentReceipt(provider_ref=f"wallet_{charged.value}", paid_minor=amount_minor))

    async def refund(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> RefundReceipt:
        entry_id = await self.wallet.credit(
            user_id,
            amount_minor,
            WalletTransactionKind.REFUND,
            trip_id=trip_id,
            reference="Trip refund",
        )
        return RefundReceipt(provider_ref=f"wallet_refund_{entry_id}", refunded_minor=amount_minor)
