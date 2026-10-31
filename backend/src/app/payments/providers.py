"""Builds the money adapters from configuration: the payment partner, the member wallet, the
trip escrow and the `PaymentProvider` the contribution flow pays through.

`PAYMENTS=wallet` (default): shares move member wallet -> trip escrow at the (simulated)
licensed partner. `PAYMENTS=fake`: every charge succeeds and there is no escrow.
"""

from app.core.background import BackgroundRunner
from app.core.config import Settings
from app.db.client import Database
from app.payments.fake import FakePayments
from app.payments.fake_partner import FakePartner
from app.payments.partner import PaymentPartner
from app.payments.ports import PaymentProvider
from app.payments.wallet import WalletPayments
from app.services.escrow import EscrowService
from app.services.wallet import WalletService


def build_partner(settings: Settings, db: Database) -> PaymentPartner:
    """Swapping in a real EMI (Mangopay, Stripe Connect + Issuing) is one adapter here."""
    return FakePartner(
        db,
        latency_s=settings.partner_latency_ms / 1000,
        kyc_limit_minor=settings.kyc_light_limit_minor,
    )


def build_wallet_service(
    settings: Settings, db: Database, runner: BackgroundRunner | None = None
) -> WalletService:
    return WalletService(
        db,
        runner,
        confirm_delay_s=settings.wallet_confirm_delay_s,
        partner=build_partner(settings, db),
    )


def build_escrow(settings: Settings, db: Database) -> EscrowService | None:
    if settings.payments != "wallet":
        return None
    wallet = build_wallet_service(settings, db)
    return EscrowService(wallet.partner, wallet)


def build_payment_provider(settings: Settings, db: Database) -> PaymentProvider:
    escrow = build_escrow(settings, db)
    return WalletPayments(escrow) if escrow is not None else FakePayments()
