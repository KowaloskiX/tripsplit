"""Picks the `PaymentProvider` adapter from configuration."""

from app.core.config import Settings
from app.db.client import Database
from app.payments.fake import FakePayments
from app.payments.ports import PaymentProvider
from app.payments.wallet import WalletPayments
from app.services.wallet import WalletService


def build_payment_provider(settings: Settings, db: Database) -> PaymentProvider:
    match settings.payments:
        case "fake":
            return FakePayments()
        case "wallet":
            return WalletPayments(WalletService(db))
