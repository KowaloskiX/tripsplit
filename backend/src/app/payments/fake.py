"""A payment provider that always succeeds — the demo and the tests run without a PSP."""

import secrets

from app.payments.ports import PaymentReceipt, RefundReceipt


class FakePayments:
    async def charge(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> PaymentReceipt:
        return PaymentReceipt(provider_ref=f"fake_{secrets.token_hex(8)}", paid_minor=amount_minor)

    async def refund(
        self, trip_id: str, user_id: str, amount_minor: int, currency: str
    ) -> RefundReceipt:
        return RefundReceipt(
            provider_ref=f"fake_refund_{secrets.token_hex(8)}", refunded_minor=amount_minor
        )
