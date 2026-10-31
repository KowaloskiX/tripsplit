"""The demo account, ready to log in (`uv run seed-demo`, dev/test only).

Idempotent: creates demo@tripsplit.app (organization "Łukasz Demo") through `AuthService` the
first time, signs in to prove the password on every later run, and tops the account's wallet
up to 5 000 zł (one ledger adjustment for the difference; nothing when it already holds that
much). Refuses to run outside dev/test — a known password must never exist in production.
"""

from dataclasses import dataclass
from datetime import date

from app.core.config import Settings
from app.core.domain.errors import AuthError
from app.core.domain.escrow import KycLevel
from app.core.domain.result import Err, Ok
from app.core.domain.wallet import WalletTransactionKind
from app.db.client import Database
from app.services.auth import AuthService
from app.services.wallet import WalletService

DEMO_EMAIL = "demo@tripsplit.app"
DEMO_PASSWORD = "TripSplitDemo2026!"
DEMO_ORGANIZATION = "Łukasz Demo"
DEMO_WALLET_MINOR = 500_000  # 5 000 zł
LOCAL_ENVS = frozenset({"dev", "test"})
DEMO_BIRTH_DATE = date(1990, 5, 4)


@dataclass(frozen=True, slots=True)
class SeededDemo:
    user_id: str
    created: bool
    topped_up_minor: int
    balance_minor: int


class SeedRefusedError(RuntimeError):
    pass


async def seed_demo(database: Database, settings: Settings) -> SeededDemo:
    if settings.app_env not in LOCAL_ENVS:
        raise SeedRefusedError(f"seed-demo runs on dev/test only, not on {settings.app_env}")
    auth = AuthService(database, settings)
    created = True
    issued = await auth.register(DEMO_EMAIL, DEMO_PASSWORD, DEMO_ORGANIZATION)
    if isinstance(issued, Err) and issued.error is AuthError.EMAIL_TAKEN:
        created = False
        issued = await auth.login(DEMO_EMAIL, DEMO_PASSWORD)
    if not isinstance(issued, Ok):
        raise SeedRefusedError(f"the demo account exists with another password: {issued.error}")
    user_id = issued.value.user.id
    wallet = WalletService(database)
    missing = DEMO_WALLET_MINOR - await wallet.balance(user_id)
    if missing > 0:
        await wallet.credit(
            user_id, missing, WalletTransactionKind.ADJUSTMENT, reference="Demo balance"
        )
    # The demo account has passed the partner's ID check, so a live top-up never hits KYC.
    if (await wallet.kyc(user_id)).level is KycLevel.NONE:
        await wallet.submit_kyc(user_id, DEMO_ORGANIZATION, DEMO_BIRTH_DATE, None)
    return SeededDemo(
        user_id=user_id,
        created=created,
        topped_up_minor=max(missing, 0),
        balance_minor=await wallet.balance(user_id),
    )
