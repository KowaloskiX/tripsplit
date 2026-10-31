"""The wallet: balance, ledger and dummy top-ups.

Money movement is simulated — BLIK and card are fake rails confirmed by an in-process
"processor" after a short delay — but the accounting is not: every balance change and its
ledger entry are written in ONE transaction through conditional updates, so the balance never
goes negative, a share is never paid twice from one balance and a top-up is credited once.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.background import BackgroundRunner
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import BookingStatus
from app.core.domain.wallet import (
    HISTORY_LIMIT,
    WALLET_CURRENCY,
    InsufficientFunds,
    PaymentMethod,
    TopUpFailure,
    WalletTransactionKind,
    WalletTransactionStatus,
    held_minor,
    processor_declines,
    shortfall,
    validate_top_up,
)
from app.db.client import Database
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.wallet import WalletTransaction
from app.repositories.bookings import BookingRepository
from app.repositories.trips import TripRepository
from app.repositories.wallet import WalletRepository, WalletTransactionRepository

logger = logging.getLogger(__name__)

# How long the dummy bank takes to confirm ("Confirm in your bank app…").
DEFAULT_CONFIRM_DELAY_S = 1.5
# A top-up still pending after this long lost its processor (a restart): it is failed on read.
PENDING_EXPIRY = timedelta(minutes=2)
EXPIRED_REASON = "expired"

# What happens once a top-up is credited (e.g. "now pay my share"); runs in the background.
type AfterTopUp = Callable[[], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class WalletEntryView:
    id: str
    kind: WalletTransactionKind
    amount_minor: int
    balance_after_minor: int | None
    trip_id: str | None
    trip_title: str | None
    method: PaymentMethod
    status: WalletTransactionStatus
    reference: str
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class WalletView:
    balance_minor: int
    currency: str
    transactions: tuple[WalletEntryView, ...]


@dataclass(frozen=True, slots=True)
class PotView:
    """The trip's money: paid in from wallets, spent on confirmed bookings, paid back."""

    collected_minor: int
    spent_minor: int
    refunded_minor: int
    held_minor: int


@dataclass(frozen=True, slots=True)
class TopUpRequest:
    amount_minor: int
    method: PaymentMethod
    blik_code: str | None = None
    card_last4: str | None = None


def _reference(request: TopUpRequest) -> str:
    if request.method is PaymentMethod.CARD:
        return f"Card •••• {request.card_last4}"
    return "BLIK"


def _entry_view(entry: WalletTransaction, titles: dict[PydanticObjectId, str]) -> WalletEntryView:
    return WalletEntryView(
        id=to_text(identifier_of(entry)),
        kind=entry.kind,
        amount_minor=entry.amount_minor,
        balance_after_minor=entry.balance_after_minor,
        trip_id=to_text(entry.trip_id) if entry.trip_id is not None else None,
        trip_title=titles.get(entry.trip_id) if entry.trip_id is not None else None,
        method=entry.method,
        status=entry.status,
        reference=entry.reference,
        failure_reason=entry.failure_reason,
        created_at=entry.created_at,
        completed_at=entry.completed_at,
    )


async def trip_pot(trip_id: PydanticObjectId) -> PotView:
    """The trip pot from the ledger (share payments in, refunds out) and the bookings (spent)."""
    entries = await WalletTransactionRepository().completed_for_trip(
        trip_id, (WalletTransactionKind.SHARE_PAYMENT, WalletTransactionKind.REFUND)
    )
    collected = -sum(
        e.amount_minor for e in entries if e.kind is WalletTransactionKind.SHARE_PAYMENT
    )
    refunded = sum(e.amount_minor for e in entries if e.kind is WalletTransactionKind.REFUND)
    spent = sum(
        booking.amount_minor
        for booking in await BookingRepository().for_trip(trip_id)
        if booking.status is BookingStatus.CONFIRMED
    )
    return PotView(
        collected_minor=collected,
        spent_minor=spent,
        refunded_minor=refunded,
        held_minor=held_minor(collected, spent, refunded),
    )


class WalletService:
    def __init__(
        self,
        db: Database,
        runner: BackgroundRunner | None = None,
        *,
        confirm_delay_s: float = DEFAULT_CONFIRM_DELAY_S,
    ) -> None:
        self.db = db
        self.runner = runner
        self.confirm_delay_s = confirm_delay_s
        self.wallets = WalletRepository()
        self.entries = WalletTransactionRepository()
        self.trips = TripRepository()

    # ---- reads ----------------------------------------------------------------------------

    async def balance(self, user_id: str) -> int:
        user_oid = to_object_id(user_id)
        wallet = await self.wallets.get(user_oid) if user_oid is not None else None
        return wallet.balance_minor if wallet is not None else 0

    async def wallet(self, user_id: str) -> WalletView:
        user_oid = to_object_id(user_id)
        if user_oid is None:
            return WalletView(balance_minor=0, currency=WALLET_CURRENCY, transactions=())
        entries = await self.entries.history(user_oid, HISTORY_LIMIT)
        entries = [await self._expire_if_stale(entry) for entry in entries]
        titles = await self._trip_titles(entries)
        return WalletView(
            balance_minor=await self.balance(user_id),
            currency=WALLET_CURRENCY,
            transactions=tuple(_entry_view(entry, titles) for entry in entries),
        )

    async def top_up_status(
        self, user_id: str, transaction_id: str
    ) -> Result[WalletEntryView, TopUpFailure]:
        entry = await self._own_entry(user_id, transaction_id)
        if entry is None or entry.kind is not WalletTransactionKind.TOP_UP:
            return Err(TopUpFailure.NOT_FOUND)
        entry = await self._expire_if_stale(entry)
        return Ok(_entry_view(entry, await self._trip_titles([entry])))

    async def pot(self, trip_id: PydanticObjectId) -> PotView:
        return await trip_pot(trip_id)

    # ---- share payments and refunds (the `WalletPayments` adapter) ------------------------

    async def charge(
        self, user_id: str, trip_id: str, amount_minor: int, reference: str = "Trip share"
    ) -> Result[str, InsufficientFunds]:
        """Debits `amount_minor` for a trip share; the ledger entry id, or the shortfall."""
        user_oid, trip_oid = to_object_id(user_id), to_object_id(trip_id)
        if user_oid is None or amount_minor <= 0:
            return Err(InsufficientFunds(shortfall_minor=max(amount_minor, 0)))

        async def write(session: AsyncClientSession) -> str | None:
            balance = await self.wallets.debit(user_oid, amount_minor, session)
            if balance is None:
                return None
            entry = await self.entries.add(
                WalletTransaction(
                    user_id=user_oid,
                    kind=WalletTransactionKind.SHARE_PAYMENT,
                    amount_minor=-amount_minor,
                    balance_after_minor=balance,
                    trip_id=trip_oid,
                    method=PaymentMethod.WALLET,
                    status=WalletTransactionStatus.COMPLETED,
                    reference=reference,
                    completed_at=utc_now(),
                ),
                session=session,
            )
            return to_text(identifier_of(entry))

        entry_id = await self.db.in_transaction(write)
        if entry_id is None:
            missing = shortfall(await self.balance(user_id), amount_minor)
            return Err(InsufficientFunds(shortfall_minor=max(missing, 1)))
        return Ok(entry_id)

    async def credit(
        self,
        user_id: str,
        amount_minor: int,
        kind: WalletTransactionKind,
        *,
        trip_id: str | None = None,
        reference: str = "",
    ) -> str:
        """An instant credit — a refund, or an adjustment (demo seeding). The ledger entry id."""
        user_oid = to_object_id(user_id)
        if user_oid is None:
            raise LookupError("a wallet credit needs a valid user id")
        trip_oid = to_object_id(trip_id) if trip_id is not None else None

        async def write(session: AsyncClientSession) -> str:
            balance = await self.wallets.credit(user_oid, amount_minor, session)
            entry = await self.entries.add(
                WalletTransaction(
                    user_id=user_oid,
                    kind=kind,
                    amount_minor=amount_minor,
                    balance_after_minor=balance,
                    trip_id=trip_oid,
                    method=PaymentMethod.WALLET,
                    status=WalletTransactionStatus.COMPLETED,
                    reference=reference,
                    completed_at=utc_now(),
                ),
                session=session,
            )
            return to_text(identifier_of(entry))

        return await self.db.in_transaction(write)

    # ---- dummy top-ups --------------------------------------------------------------------

    async def start_top_up(
        self,
        user_id: str,
        request: TopUpRequest,
        *,
        trip_id: str | None = None,
        after: AfterTopUp | None = None,
    ) -> Result[WalletEntryView, TopUpFailure]:
        """Creates a PENDING top-up and hands it to the dummy processor, which confirms (or
        declines) it after `confirm_delay_s`. `after` runs once it is credited."""
        user_oid = to_object_id(user_id)
        if user_oid is None:
            return Err(TopUpFailure.NOT_FOUND)
        failure = validate_top_up(
            request.amount_minor, request.method, request.blik_code, request.card_last4
        )
        if failure is not None:
            return Err(failure)
        entry = await self.entries.add(
            WalletTransaction(
                user_id=user_oid,
                kind=WalletTransactionKind.TOP_UP,
                amount_minor=request.amount_minor,
                trip_id=to_object_id(trip_id) if trip_id is not None else None,
                method=request.method,
                status=WalletTransactionStatus.PENDING,
                reference=_reference(request),
                pay_trip_on_completion=after is not None,
            )
        )
        # The code and card digits stay in this closure only; nothing of them is stored.
        declined = processor_declines(request.method, request.blik_code, request.card_last4)
        job = self._process(identifier_of(entry), declined=declined, after=after)
        if self.runner is None:
            await job
        else:
            self.runner.spawn(job, name=f"wallet-top-up-{to_text(identifier_of(entry))}")
        return Ok(_entry_view(entry, await self._trip_titles([entry])))

    async def _process(
        self, entry_id: PydanticObjectId, *, declined: bool, after: AfterTopUp | None
    ) -> None:
        if self.confirm_delay_s > 0:
            await asyncio.sleep(self.confirm_delay_s)
        if declined:
            await self.entries.fail_pending(entry_id, TopUpFailure.DECLINED.value)
            return
        if await self._confirm(entry_id) and after is not None:
            await after()

    async def _confirm(self, entry_id: PydanticObjectId) -> bool:
        """pending -> completed and the balance credited, in one transaction, exactly once."""

        async def write(session: AsyncClientSession) -> bool:
            entry = await self.entries.get(entry_id, session=session)
            if entry is None or entry.status is not WalletTransactionStatus.PENDING:
                return False
            balance = await self.wallets.credit(entry.user_id, entry.amount_minor, session)
            if not await self.entries.complete_pending(entry_id, balance, utc_now(), session):
                # Somebody settled it in between: abort, so the credit above rolls back.
                raise _AlreadySettledError
            return True

        try:
            return await self.db.in_transaction(write)
        except _AlreadySettledError:
            return False

    # ---- helpers --------------------------------------------------------------------------

    async def _own_entry(self, user_id: str, transaction_id: str) -> WalletTransaction | None:
        user_oid, entry_oid = to_object_id(user_id), to_object_id(transaction_id)
        if user_oid is None or entry_oid is None:
            return None
        entry = await self.entries.get(entry_oid)
        # Somebody else's transaction is reported as missing — no existence oracle.
        return entry if entry is not None and entry.user_id == user_oid else None

    async def _expire_if_stale(self, entry: WalletTransaction) -> WalletTransaction:
        if entry.status is not WalletTransactionStatus.PENDING:
            return entry
        if utc_now() - entry.created_at < PENDING_EXPIRY:
            return entry
        await self.entries.fail_pending(identifier_of(entry), EXPIRED_REASON)
        fresh = await self.entries.get(identifier_of(entry))
        return fresh if fresh is not None else entry

    async def _trip_titles(self, entries: list[WalletTransaction]) -> dict[PydanticObjectId, str]:
        titles: dict[PydanticObjectId, str] = {}
        for trip_id in {e.trip_id for e in entries if e.trip_id is not None}:
            trip = await self.trips.get(trip_id)
            if trip is not None:
                titles[trip_id] = trip.title
        return titles


class _AlreadySettledError(Exception):
    """Aborts a top-up confirmation transaction that lost the race."""
