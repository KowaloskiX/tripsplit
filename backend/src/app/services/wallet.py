"""The member wallet: OUR mirror of the member's e-money wallet at the payment partner.

The partner (a licensed EMI, simulated by `FakePartner`) holds the money: pay-ins, transfers
into a trip escrow and refunds out of it all happen there first. This service then mirrors
each partner movement into `Wallet` / `WalletTransaction` — one ledger entry per movement, the
balance updated in the same transaction — so the UI reads fast and the harness can check that
our mirror equals the partner's ledger.

Top-ups stay asynchronous: PENDING here, confirmed (or declined) by the partner after a short
delay. Cumulative top-ups above the KYC-light threshold need ID verification first.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import DuplicateKeyError

from app.core.background import BackgroundRunner
from app.core.domain.escrow import (
    PARTNER_DISPLAY_NAME,
    KycLevel,
    KycStatus,
    kyc_remaining_minor,
    needs_kyc,
)
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
    shortfall,
    validate_top_up,
)
from app.db.client import Database
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.wallet import WalletTransaction
from app.payments.fake_partner import FakePartner
from app.payments.partner import (
    KycSubmission,
    Movement,
    PartnerError,
    PartnerUser,
    PayInInstrument,
    PayInMethod,
    PaymentPartner,
    TransferTag,
    WalletOwnerKind,
)
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

_TOP_UP_FAILURE: dict[PartnerError, TopUpFailure] = {
    PartnerError.DECLINED: TopUpFailure.DECLINED,
    PartnerError.KYC_REQUIRED: TopUpFailure.KYC_REQUIRED,
}


def owner_ref_of(user_id: str) -> str:
    """How TripSplit names a member at the partner (the partner never sees our user id)."""
    return f"user:{user_id}"


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
class KycView:
    level: KycLevel
    status: KycStatus
    limit_minor: int
    topped_up_minor: int
    # None = verified, no limit.
    remaining_minor: int | None
    # Echo of the last four digits of the document, masked ("•••• 1234"); never the number.
    document_masked: str | None = None


@dataclass(frozen=True, slots=True)
class WalletView:
    balance_minor: int
    currency: str
    transactions: tuple[WalletEntryView, ...]
    kyc: KycView
    # Who really holds the money (a simulated licensed partner).
    held_by: str = PARTNER_DISPLAY_NAME
    partner_wallet_id: str | None = None


@dataclass(frozen=True, slots=True)
class PotView:
    """The trip's money. With an escrow (PAYMENTS=wallet) it is read from the partner's
    escrow wallet; without one (PAYMENTS=fake) from our ledger and the bookings."""

    collected_minor: int
    spent_minor: int  # paid to suppliers (payouts + card spends)
    refunded_minor: int
    held_minor: int
    reserved_minor: int = 0  # on live virtual cards
    escrow_wallet_id: str | None = None
    pay_by: datetime | None = None
    funded_minor: int = 0
    target_minor: int = 0
    held_by: str = PARTNER_DISPLAY_NAME


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


def _instrument(request: TopUpRequest) -> PayInInstrument:
    method = PayInMethod.CARD if request.method is PaymentMethod.CARD else PayInMethod.BLIK
    return PayInInstrument(
        method=method, blik_code=request.blik_code, card_last4=request.card_last4
    )


def _kyc_view(user: PartnerUser, document_last4: str | None = None) -> KycView:
    return KycView(
        level=user.kyc_level,
        status=user.kyc_status,
        limit_minor=user.kyc_limit_minor,
        topped_up_minor=user.topped_up_minor,
        remaining_minor=kyc_remaining_minor(
            user.topped_up_minor, user.kyc_limit_minor, user.kyc_level
        ),
        document_masked=f"•••• {document_last4}" if document_last4 else None,
    )


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


async def ledger_pot(trip_id: PydanticObjectId) -> PotView:
    """The trip pot without an escrow (PAYMENTS=fake): share payments in, refunds out, and
    confirmed bookings as spent."""
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
        partner: PaymentPartner | None = None,
    ) -> None:
        self.db = db
        self.runner = runner
        self.confirm_delay_s = confirm_delay_s
        self.partner: PaymentPartner = (
            partner if partner is not None else FakePartner(db, latency_s=0)
        )
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
        kyc = await self.kyc(user_id)
        if user_oid is None:
            return WalletView(balance_minor=0, currency=WALLET_CURRENCY, transactions=(), kyc=kyc)
        entries = await self.entries.history(user_oid, HISTORY_LIMIT)
        entries = [await self._expire_if_stale(entry) for entry in entries]
        titles = await self._trip_titles(entries)
        mirror = await self.wallets.get(user_oid)
        return WalletView(
            balance_minor=await self.balance(user_id),
            currency=WALLET_CURRENCY,
            transactions=tuple(_entry_view(entry, titles) for entry in entries),
            kyc=kyc,
            partner_wallet_id=mirror.partner_wallet_id if mirror is not None else None,
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
        return await ledger_pot(trip_id)

    # ---- KYC ------------------------------------------------------------------------------

    async def kyc(self, user_id: str) -> KycView:
        return _kyc_view(await self.partner.ensure_user(owner_ref_of(user_id)))

    async def submit_kyc(
        self, user_id: str, legal_name: str, birth_date: date, document_number: str | None
    ) -> KycView:
        """ "ID verification": the partner verifies shortly after. The document number goes to
        the partner and is forgotten here — only its masked last four digits are echoed."""
        user = await self.partner.submit_kyc(
            owner_ref_of(user_id),
            KycSubmission(
                legal_name=legal_name, birth_date=birth_date, document_number=document_number
            ),
        )
        digits = (document_number or "").strip()
        return _kyc_view(user, digits[-4:] if digits else None)

    # ---- the partner wallet ---------------------------------------------------------------

    async def partner_wallet_id(self, user_id: str) -> str:
        """The member's e-money wallet at the partner, opened on first use. A mirror balance
        from before the partner existed is carried over once (a back-office credit)."""
        user_oid = to_object_id(user_id)
        if user_oid is None:
            raise LookupError("a wallet needs a valid user id")
        mirror = await self.wallets.get(user_oid)
        if mirror is not None and mirror.partner_wallet_id:
            return mirror.partner_wallet_id
        owner = owner_ref_of(user_id)
        await self.partner.ensure_user(owner)
        wallet_id = await self.partner.create_wallet(WalletOwnerKind.USER, owner, WALLET_CURRENCY)
        await self.wallets.link_partner(user_oid, wallet_id)
        legacy = mirror.balance_minor if mirror is not None else 0
        if legacy > 0 and await self.partner.balance(wallet_id) == 0:
            await self.partner.pay_in(
                wallet_id,
                legacy,
                PayInInstrument(method=PayInMethod.ADJUSTMENT),
                owner_ref=owner,
                idempotency_key=f"opening:{user_id}",
            )
        return wallet_id

    # ---- share payments and refunds (through the trip escrow) -----------------------------

    async def charge(
        self,
        user_id: str,
        trip_id: str,
        amount_minor: int,
        *,
        to_wallet: str,
        idempotency_key: str,
        reference: str = "Trip share",
    ) -> Result[str, InsufficientFunds]:
        """Transfers `amount_minor` from the member's wallet into `to_wallet` (the trip
        escrow) at the partner, then mirrors it. The ledger entry id, or the shortfall."""
        user_oid, trip_oid = to_object_id(user_id), to_object_id(trip_id)
        if user_oid is None or amount_minor <= 0:
            return Err(InsufficientFunds(shortfall_minor=max(amount_minor, 0)))
        source = await self.partner_wallet_id(user_id)
        moved = await self.partner.transfer(
            source,
            to_wallet,
            amount_minor,
            TransferTag.SHARE,
            reference=reference,
            idempotency_key=idempotency_key,
        )
        if isinstance(moved, Err):
            missing = shortfall(await self.partner.balance(source), amount_minor)
            return Err(InsufficientFunds(shortfall_minor=max(missing, 1)))
        movement = moved.value
        entry_id = await self._mirror(
            user_oid,
            WalletTransactionKind.SHARE_PAYMENT,
            -amount_minor,
            movement,
            movement.debit_balance_after_minor,
            trip_oid,
            reference,
        )
        return Ok(entry_id)

    async def receive(
        self,
        user_id: str,
        trip_id: str | None,
        amount_minor: int,
        *,
        from_wallet: str,
        tag: TransferTag,
        idempotency_key: str,
        reference: str,
    ) -> Result[str, PartnerError]:
        """A transfer from `from_wallet` (the trip escrow) back into the member's wallet — a
        refund — mirrored as a REFUND entry."""
        user_oid = to_object_id(user_id)
        if user_oid is None:
            return Err(PartnerError.WALLET_NOT_FOUND)
        target = await self.partner_wallet_id(user_id)
        moved = await self.partner.transfer(
            from_wallet,
            target,
            amount_minor,
            tag,
            reference=reference,
            idempotency_key=idempotency_key,
        )
        if isinstance(moved, Err):
            return moved
        movement = moved.value
        trip_oid = to_object_id(trip_id) if trip_id is not None else None
        return Ok(
            await self._mirror(
                user_oid,
                WalletTransactionKind.REFUND,
                amount_minor,
                movement,
                movement.credit_balance_after_minor,
                trip_oid,
                reference,
            )
        )

    async def credit(
        self,
        user_id: str,
        amount_minor: int,
        kind: WalletTransactionKind = WalletTransactionKind.ADJUSTMENT,
        *,
        trip_id: str | None = None,
        reference: str = "",
    ) -> str:
        """An instant back-office credit (demo seeding) — a pay-in at the partner that skips
        the bank and the KYC counter. The ledger entry id."""
        user_oid = to_object_id(user_id)
        if user_oid is None:
            raise LookupError("a wallet credit needs a valid user id")
        target = await self.partner_wallet_id(user_id)
        moved = await self.partner.pay_in(
            target,
            amount_minor,
            PayInInstrument(method=PayInMethod.ADJUSTMENT),
            owner_ref=owner_ref_of(user_id),
            idempotency_key=f"credit:{user_id}:{utc_now().timestamp()}:{amount_minor}",
        )
        if isinstance(moved, Err):
            raise RuntimeError(f"the partner refused a back-office credit: {moved.error}")
        trip_oid = to_object_id(trip_id) if trip_id is not None else None
        return await self._mirror(
            user_oid,
            kind,
            amount_minor,
            moved.value,
            moved.value.credit_balance_after_minor,
            trip_oid,
            reference or "Demo credit",
        )

    async def _mirror(
        self,
        user_oid: PydanticObjectId,
        kind: WalletTransactionKind,
        delta_minor: int,
        movement: Movement,
        balance_after: int | None,
        trip_oid: PydanticObjectId | None,
        reference: str,
    ) -> str:
        """One partner movement -> one completed ledger entry + the balance, atomically and
        exactly once (a replayed movement is already mirrored)."""

        async def write(session: AsyncClientSession) -> str:
            await self.wallets.credit(user_oid, delta_minor, session)
            entry = await self.entries.add(
                WalletTransaction(
                    user_id=user_oid,
                    kind=kind,
                    amount_minor=delta_minor,
                    balance_after_minor=balance_after,
                    trip_id=trip_oid,
                    method=PaymentMethod.WALLET,
                    status=WalletTransactionStatus.COMPLETED,
                    reference=reference,
                    partner_ref=movement.id,
                    completed_at=utc_now(),
                ),
                session=session,
            )
            return to_text(identifier_of(entry))

        try:
            return await self.db.in_transaction(write)
        except DuplicateKeyError:
            existing = await self.entries.by_partner_ref(movement.id)
            if existing is None:
                raise
            return to_text(identifier_of(existing))

    # ---- dummy top-ups --------------------------------------------------------------------

    async def start_top_up(
        self,
        user_id: str,
        request: TopUpRequest,
        *,
        trip_id: str | None = None,
        after: AfterTopUp | None = None,
    ) -> Result[WalletEntryView, TopUpFailure]:
        """Creates a PENDING top-up and hands it to the partner, which confirms (or declines)
        it after `confirm_delay_s`. `after` runs once it is credited. Refused up front when
        the cumulative top-ups would cross the KYC-light threshold unverified."""
        user_oid = to_object_id(user_id)
        if user_oid is None:
            return Err(TopUpFailure.NOT_FOUND)
        failure = validate_top_up(
            request.amount_minor, request.method, request.blik_code, request.card_last4
        )
        if failure is not None:
            return Err(failure)
        user = await self.partner.ensure_user(owner_ref_of(user_id))
        if needs_kyc(
            user.topped_up_minor, request.amount_minor, user.kyc_limit_minor, user.kyc_level
        ):
            return Err(TopUpFailure.KYC_REQUIRED)
        wallet_id = await self.partner_wallet_id(user_id)
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
        instrument = _instrument(request)
        job = self._process(identifier_of(entry), user_id, wallet_id, instrument, after=after)
        if self.runner is None:
            await job
        else:
            self.runner.spawn(job, name=f"wallet-top-up-{to_text(identifier_of(entry))}")
        return Ok(_entry_view(entry, await self._trip_titles([entry])))

    async def _process(
        self,
        entry_id: PydanticObjectId,
        user_id: str,
        wallet_id: str,
        instrument: PayInInstrument,
        *,
        after: AfterTopUp | None,
    ) -> None:
        if self.confirm_delay_s > 0:
            await asyncio.sleep(self.confirm_delay_s)
        entry = await self.entries.get(entry_id)
        if entry is None or entry.status is not WalletTransactionStatus.PENDING:
            return
        moved = await self.partner.pay_in(
            wallet_id,
            entry.amount_minor,
            instrument,
            owner_ref=owner_ref_of(user_id),
            idempotency_key=f"top_up:{to_text(entry_id)}",
        )
        if isinstance(moved, Err):
            reason = _TOP_UP_FAILURE.get(moved.error, TopUpFailure.DECLINED)
            await self.entries.fail_pending(entry_id, reason.value)
            return
        if await self._confirm(entry_id, moved.value) and after is not None:
            await after()

    async def _confirm(self, entry_id: PydanticObjectId, movement: Movement | None = None) -> bool:
        """pending -> completed and the balance credited, in one transaction, exactly once."""

        async def write(session: AsyncClientSession) -> bool:
            entry = await self.entries.get(entry_id, session=session)
            if entry is None or entry.status is not WalletTransactionStatus.PENDING:
                return False
            balance = await self.wallets.credit(entry.user_id, entry.amount_minor, session)
            partner_ref = movement.id if movement is not None else None
            if not await self.entries.complete_pending(
                entry_id, balance, utc_now(), session, partner_ref=partner_ref
            ):
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
