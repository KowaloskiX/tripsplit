"""Picks the `PaymentProvider` adapter from configuration."""

from app.core.config import Settings
from app.payments.fake import FakePayments
from app.payments.ports import PaymentProvider


def build_payment_provider(settings: Settings) -> PaymentProvider:
    match settings.payments:
        case "fake":
            return FakePayments()
