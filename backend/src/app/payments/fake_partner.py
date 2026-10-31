"""`FakePartner`: a simulated licensed payment partner behind `PaymentPartner`.

It behaves like the external system would: its own collections (`partner_*`), its own ids
(`usr_…`, `wlt_…`, `txn_…`, `po_…`, `card_…`), a latency on every call, idempotency keys on every
money call (a replay returns the first result and moves nothing), a KYC threshold on pay-ins,
conditional escrow release (Rule #1: no payout or card before the escrow is 100% funded) and
single-use virtual cards. `fail_next` injects failures for the harness.

Every movement is ONE transaction: the conditional debit, the credit and the ledger entry —
so a balance always equals its ledger and never goes below zero.
"""

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import DuplicateKeyError

from app.core.domain.escrow import (
    DEFAULT_KYC_LIGHT_LIMIT_MINOR,
    CardStatus,
    KycLevel,
    KycStatus,
    card_declines,
    needs_kyc,
)
from app.core.domain.result import Err, Ok, Result
from app.core.domain.wallet import PaymentMethod, processor_declines
from app.db.client import Database
from app.db.documents import utc_now
from app.payments.fake_partner_models import (
    PartnerCardRecord,
    PartnerLedgerRecord,
    PartnerUserRecord,
    PartnerWalletRecord,
)
from app.payments.partner import (
    CardCharge,
    CardSecrets,
    KycSubmission,
    LedgerKind,
    Movement,
    PartnerError,
    PartnerOp,
    PartnerUser,
    PayInInstrument,
    PayInMethod,
    SupplierAccount,
    TransferTag,
    VirtualCard,
    WalletOwnerKind,
)

type Clock = Callable[[], datetime]

# Realistic, but short: the UI shows a spinner, the tests set 0.
DEFAULT_LATENCY_S = 0.12
DEFAULT_KYC_DELAY = timedelta(seconds=1)
# Test PANs: Stripe's 4242… family, unique in the middle, so a charge finds its card.
_PAN_PREFIX = "4242"
_PAN_SUFFIX = "4242"
_REFUND_TAGS = frozenset({TransferTag.REFUND.value, TransferTag.DEADLINE_REFUND.value})


class _RefusedError(Exception):
    def __init__(self, error: PartnerError) -> None:
        super().__init__(error.value)
        self.error = error


@dataclass(frozen=True, slots=True)
class _Leg:
    kind: LedgerKind
    amount_minor: int
    debit: str | None
    credit: str | None
    tag: str
    reference: str
    idempotency_key: str
    # Escrow only: refuse unless the debited escrow is 100% funded.
    requires_funded: bool = False


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def movement_of(entry: PartnerLedgerRecord) -> Movement:
    return Movement(
        id=entry.entry_id,
        kind=entry.kind,
        amount_minor=entry.amount_minor,
        debit_wallet_id=entry.debit_wallet_id,
        credit_wallet_id=entry.credit_wallet_id,
        tag=entry.tag,
        reference=entry.reference,
        created_at=entry.created_at,
        debit_balance_after_minor=entry.debit_balance_after_minor,
        credit_balance_after_minor=entry.credit_balance_after_minor,
    )


def card_view(record: PartnerCardRecord) -> VirtualCard:
    return VirtualCard(
        card_id=record.card_id,
        pan_last4=record.pan[-4:],
        exp_month=record.exp_month,
        exp_year=record.exp_year,
        limit_minor=record.limit_minor,
        spent_minor=record.spent_minor,
        status=record.status,
        merchant_hint=record.merchant_hint,
        expires_at=record.expires_at,
    )


class FakePartner:
    def __init__(
        self,
        db: Database,
        *,
        latency_s: float = DEFAULT_LATENCY_S,
        kyc_limit_minor: int = DEFAULT_KYC_LIGHT_LIMIT_MINOR,
        kyc_delay: timedelta = DEFAULT_KYC_DELAY,
        clock: Clock = utc_now,
    ) -> None:
        self.db = db
        self.latency_s = latency_s
        self.kyc_limit_minor = kyc_limit_minor
        self.kyc_delay = kyc_delay
        self.clock = clock
        # Failure injection: the next call of an operation fails with this error.
        self._faults: dict[PartnerOp, PartnerError] = {}

    # ---- failure injection ----------------------------------------------------------------

    def fail_next(self, op: PartnerOp, error: PartnerError = PartnerError.UNAVAILABLE) -> None:
        self._faults[op] = error

    def _fault(self, op: PartnerOp) -> PartnerError | None:
        return self._faults.pop(op, None)

    async def _latency(self) -> None:
        if self.latency_s > 0:
            await asyncio.sleep(self.latency_s)

    # ---- users and KYC --------------------------------------------------------------------

    async def ensure_user(self, owner_ref: str) -> PartnerUser:
        record = await self._user_record(owner_ref)
        if (
            record.kyc_status is KycStatus.PENDING
            and record.kyc_verifies_at is not None
            and self.clock() >= record.kyc_verifies_at
        ):
            await PartnerUserRecord.get_pymongo_collection().update_one(
                {"owner_ref": owner_ref, "kyc_status": KycStatus.PENDING},
                {"$set": {"kyc_status": KycStatus.VERIFIED, "kyc_level": KycLevel.LIGHT}},
            )
            record = await self._user_record(owner_ref)
        return self._user(record)

    async def submit_kyc(self, owner_ref: str, submission: KycSubmission) -> PartnerUser:
        await self._latency()
        await self._user_record(owner_ref)
        document = (submission.document_number or "").strip()
        verified_now = self.kyc_delay <= timedelta(0)
        await PartnerUserRecord.get_pymongo_collection().update_one(
            {"owner_ref": owner_ref, "kyc_status": {"$ne": KycStatus.VERIFIED}},
            {
                "$set": {
                    "legal_name": submission.legal_name,
                    "birth_date": submission.birth_date.isoformat(),
                    "document_last4": document[-4:] if document else None,
                    "kyc_status": KycStatus.VERIFIED if verified_now else KycStatus.PENDING,
                    "kyc_level": KycLevel.LIGHT if verified_now else KycLevel.NONE,
                    "kyc_verifies_at": self.clock() + self.kyc_delay,
                }
            },
        )
        return await self.ensure_user(owner_ref)

    async def _user_record(self, owner_ref: str) -> PartnerUserRecord:
        collection = PartnerUserRecord.get_pymongo_collection()
        await collection.update_one(
            {"owner_ref": owner_ref},
            {
                "$setOnInsert": {
                    "partner_user_id": _new_id("usr"),
                    "kyc_level": KycLevel.NONE,
                    "kyc_status": KycStatus.NOT_STARTED,
                    "topped_up_minor": 0,
                    "kyc_verifies_at": None,
                    "legal_name": None,
                    "birth_date": None,
                    "document_last4": None,
                    "created_at": utc_now(),
                }
            },
            upsert=True,
        )
        record = await PartnerUserRecord.find_one(PartnerUserRecord.owner_ref == owner_ref)
        if record is None:  # pragma: no cover - just upserted
            raise LookupError("partner user upsert returned nothing")
        return record

    def _user(self, record: PartnerUserRecord) -> PartnerUser:
        return PartnerUser(
            owner_ref=record.owner_ref,
            partner_user_id=record.partner_user_id,
            kyc_level=record.kyc_level,
            kyc_status=record.kyc_status,
            topped_up_minor=record.topped_up_minor,
            kyc_limit_minor=self.kyc_limit_minor,
        )

    # ---- wallets --------------------------------------------------------------------------

    async def create_wallet(
        self, owner_kind: WalletOwnerKind, owner_ref: str, currency: str
    ) -> str:
        collection = PartnerWalletRecord.get_pymongo_collection()
        try:
            document = await collection.find_one_and_update(
                {"owner_kind": owner_kind, "owner_ref": owner_ref},
                {
                    "$setOnInsert": {
                        "wallet_id": _new_id("wlt"),
                        "currency": currency,
                        "balance_minor": 0,
                        "release_target_minor": 0,
                        "funded_minor": 0,
                        "created_at": utc_now(),
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:  # two concurrent creations: the other one won
            document = await collection.find_one({"owner_kind": owner_kind, "owner_ref": owner_ref})
        if document is None:  # pragma: no cover - just upserted
            raise LookupError("partner wallet upsert returned nothing")
        return str(document["wallet_id"])

    async def balance(self, wallet_id: str) -> int:
        wallet = await self._wallet(wallet_id)
        return wallet.balance_minor if wallet is not None else 0

    async def statement(self, wallet_id: str) -> list[Movement]:
        entries = (
            await PartnerLedgerRecord.find(
                {"$or": [{"debit_wallet_id": wallet_id}, {"credit_wallet_id": wallet_id}]}
            )
            .sort("created_at", "_id")
            .to_list()
        )
        return [movement_of(entry) for entry in entries]

    async def set_release_target(self, wallet_id: str, target_minor: int) -> None:
        await PartnerWalletRecord.get_pymongo_collection().update_one(
            {"wallet_id": wallet_id}, {"$set": {"release_target_minor": max(target_minor, 0)}}
        )

    async def _wallet(
        self, wallet_id: str, session: AsyncClientSession | None = None
    ) -> PartnerWalletRecord | None:
        return await PartnerWalletRecord.find_one(
            PartnerWalletRecord.wallet_id == wallet_id, session=session
        )

    # ---- money ----------------------------------------------------------------------------

    async def pay_in(
        self,
        wallet_id: str,
        amount_minor: int,
        instrument: PayInInstrument,
        *,
        owner_ref: str,
        idempotency_key: str,
    ) -> Result[Movement, PartnerError]:
        await self._latency()
        replay = await self._replay(idempotency_key)
        if replay is not None:
            return Ok(replay)
        if (fault := self._fault(PartnerOp.PAY_IN)) is not None:
            return Err(fault)
        adjustment = instrument.method is PayInMethod.ADJUSTMENT
        user = await self.ensure_user(owner_ref)
        if not adjustment:
            if needs_kyc(user.topped_up_minor, amount_minor, self.kyc_limit_minor, user.kyc_level):
                return Err(PartnerError.KYC_REQUIRED)
            method = PaymentMethod(instrument.method.value)
            if processor_declines(method, instrument.blik_code, instrument.card_last4):
                return Err(PartnerError.DECLINED)
        reference = "Back-office credit" if adjustment else instrument.method.value.upper()
        moved = await self._move(
            _Leg(
                LedgerKind.PAY_IN,
                amount_minor,
                None,
                wallet_id,
                instrument.method.value,
                reference,
                idempotency_key,
            )
        )
        if isinstance(moved, Ok) and not adjustment:
            await PartnerUserRecord.get_pymongo_collection().update_one(
                {"owner_ref": owner_ref}, {"$inc": {"topped_up_minor": amount_minor}}
            )
        return moved

    async def transfer(
        self,
        from_wallet: str,
        to_wallet: str,
        amount_minor: int,
        tag: TransferTag,
        *,
        reference: str,
        idempotency_key: str,
    ) -> Result[Movement, PartnerError]:
        await self._latency()
        if (fault := self._fault(PartnerOp.TRANSFER)) is not None:
            return Err(fault)
        return await self._move(
            _Leg(
                LedgerKind.TRANSFER,
                amount_minor,
                from_wallet,
                to_wallet,
                tag.value,
                reference,
                idempotency_key,
            )
        )

    async def payout(
        self,
        from_wallet: str,
        supplier: SupplierAccount,
        amount_minor: int,
        *,
        reference: str,
        idempotency_key: str,
    ) -> Result[Movement, PartnerError]:
        await self._latency()
        if (fault := self._fault(PartnerOp.PAYOUT)) is not None:
            return Err(fault)
        return await self._move(
            _Leg(
                LedgerKind.PAYOUT,
                amount_minor,
                from_wallet,
                None,
                supplier.supplier_id,
                f"{supplier.display_name}: {reference}"[:200],
                idempotency_key,
                requires_funded=True,
            ),
            prefix="po",
        )

    async def reverse_payout(
        self, payout_id: str, *, idempotency_key: str
    ) -> Result[Movement, PartnerError]:
        await self._latency()
        payout = await PartnerLedgerRecord.find_one(PartnerLedgerRecord.entry_id == payout_id)
        if payout is None or payout.kind is not LedgerKind.PAYOUT or payout.debit_wallet_id is None:
            return Err(PartnerError.WALLET_NOT_FOUND)
        return await self._move(
            _Leg(
                LedgerKind.PAYOUT_REVERSAL,
                payout.amount_minor,
                None,
                payout.debit_wallet_id,
                payout.tag,
                f"Returned {payout_id}",
                idempotency_key,
            )
        )

    # ---- virtual cards --------------------------------------------------------------------

    async def issue_virtual_card(
        self,
        from_wallet: str,
        amount_minor: int,
        merchant_hint: str,
        expires_in: timedelta,
        *,
        idempotency_key: str,
    ) -> Result[VirtualCard, PartnerError]:
        await self._latency()
        existing = await PartnerCardRecord.find_one(
            PartnerCardRecord.idempotency_key == idempotency_key
        )
        if existing is not None:
            return Ok(card_view(existing))
        if (fault := self._fault(PartnerOp.ISSUE_CARD)) is not None:
            return Err(fault)
        card_id = _new_id("card")
        card_wallet = await self.create_wallet(WalletOwnerKind.CARD, card_id, "PLN")
        if await self._wallet(from_wallet) is None:
            return Err(PartnerError.WALLET_NOT_FOUND)
        now = self.clock()
        printed = now + timedelta(days=730)
        record = PartnerCardRecord(
            card_id=card_id,
            funding_wallet_id=from_wallet,
            card_wallet_id=card_wallet,
            pan=f"{_PAN_PREFIX}{secrets.randbelow(10**8):08d}{_PAN_SUFFIX}",
            exp_month=printed.month,
            exp_year=printed.year,
            cvc=f"{secrets.randbelow(1000):03d}",
            limit_minor=amount_minor,
            status=CardStatus.INACTIVE,
            merchant_hint=merchant_hint[:120],
            expires_at=now + expires_in,
            idempotency_key=idempotency_key,
        )
        await record.insert()
        return Ok(card_view(record))

    async def activate_card(
        self, card_id: str, *, idempotency_key: str
    ) -> Result[VirtualCard, PartnerError]:
        await self._latency()
        record = await self._card_record(card_id)
        if record is None:
            return Err(PartnerError.CARD_NOT_FOUND)
        if record.status is CardStatus.ACTIVE:
            return Ok(card_view(record))
        if record.status is not CardStatus.INACTIVE or self.clock() >= record.expires_at:
            return Err(PartnerError.CARD_DECLINED)
        funded = await self._move(
            _Leg(
                LedgerKind.CARD_FUNDING,
                record.limit_minor,
                record.funding_wallet_id,
                record.card_wallet_id,
                card_id,
                record.merchant_hint,
                idempotency_key,
                requires_funded=True,
            )
        )
        if isinstance(funded, Err):
            return funded
        await PartnerCardRecord.get_pymongo_collection().update_one(
            {"card_id": card_id, "status": CardStatus.INACTIVE},
            {"$set": {"status": CardStatus.ACTIVE}},
        )
        fresh = await self._card_record(card_id)
        return Ok(card_view(fresh if fresh is not None else record))

    async def reveal_card(self, card_id: str) -> CardSecrets | None:
        record = await self._card_record(card_id)
        if record is None:
            return None
        return CardSecrets(
            pan=record.pan, exp_month=record.exp_month, exp_year=record.exp_year, cvc=record.cvc
        )

    async def charge_card(
        self, charge: CardCharge, *, idempotency_key: str
    ) -> Result[Movement, PartnerError]:
        await self._latency()
        replay = await self._replay(idempotency_key)
        if replay is not None:
            return Ok(replay)
        if (fault := self._fault(PartnerOp.CHARGE_CARD)) is not None:
            return Err(fault)
        record = await PartnerCardRecord.find_one(PartnerCardRecord.pan == charge.pan)
        if (
            record is None
            or record.cvc != charge.cvc
            or (record.exp_month, record.exp_year) != (charge.exp_month, charge.exp_year)
        ):
            return Err(PartnerError.CARD_DECLINED)
        expired = self.clock() >= record.expires_at
        if expired and record.status in (CardStatus.ACTIVE, CardStatus.INACTIVE):
            await self.close_card(record.card_id)
        if card_declines(record.limit_minor, charge.amount_minor, record.status, expired):
            return Err(PartnerError.CARD_DECLINED)
        # Single use: claim the card first (compare-and-set), so two charges cannot both pass.
        claimed = await PartnerCardRecord.get_pymongo_collection().update_one(
            {"card_id": record.card_id, "status": CardStatus.ACTIVE},
            {"$set": {"status": CardStatus.USED, "spent_minor": charge.amount_minor}},
        )
        if claimed.modified_count != 1:
            return Err(PartnerError.CARD_DECLINED)
        captured = await self._move(
            _Leg(
                LedgerKind.CARD_CAPTURE,
                charge.amount_minor,
                record.card_wallet_id,
                None,
                record.card_id,
                charge.merchant[:120],
                idempotency_key,
            )
        )
        unused = record.limit_minor - charge.amount_minor
        if unused > 0:
            await self._move(
                _Leg(
                    LedgerKind.CARD_RELEASE,
                    unused,
                    record.card_wallet_id,
                    record.funding_wallet_id,
                    record.card_id,
                    "Unused card funds",
                    f"{record.card_id}:release",
                )
            )
        return captured

    async def close_card(self, card_id: str) -> VirtualCard | None:
        record = await self._card_record(card_id)
        if record is None:
            return None
        if record.status is CardStatus.INACTIVE:
            # Never funded: nothing to release.
            await PartnerCardRecord.get_pymongo_collection().update_one(
                {"card_id": card_id, "status": CardStatus.INACTIVE},
                {"$set": {"status": CardStatus.CLOSED}},
            )
            return await self.card_status(card_id)
        closed = await PartnerCardRecord.get_pymongo_collection().update_one(
            {"card_id": card_id, "status": CardStatus.ACTIVE},
            {"$set": {"status": CardStatus.CLOSED}},
        )
        if closed.modified_count == 1 and record.limit_minor > 0:
            await self._move(
                _Leg(
                    LedgerKind.CARD_RELEASE,
                    record.limit_minor,
                    record.card_wallet_id,
                    record.funding_wallet_id,
                    card_id,
                    "Card closed unused",
                    f"{card_id}:release",
                )
            )
        return await self.card_status(card_id)

    async def card_status(self, card_id: str) -> VirtualCard | None:
        record = await self._card_record(card_id)
        if record is None:
            return None
        live = record.status in (CardStatus.ACTIVE, CardStatus.INACTIVE)
        if live and self.clock() >= record.expires_at:
            return await self.close_card(card_id)
        return card_view(record)

    async def cards_funded_by(self, wallet_id: str) -> list[VirtualCard]:
        records = (
            await PartnerCardRecord.find(PartnerCardRecord.funding_wallet_id == wallet_id)
            .sort("created_at")
            .to_list()
        )
        return [card_view(record) for record in records]

    async def refund_card_charge(
        self, card_id: str, *, idempotency_key: str
    ) -> Result[Movement, PartnerError]:
        await self._latency()
        record = await self._card_record(card_id)
        if record is None or record.status is not CardStatus.USED or record.spent_minor <= 0:
            return Err(PartnerError.CARD_NOT_FOUND)
        return await self._move(
            _Leg(
                LedgerKind.CARD_REFUND,
                record.spent_minor,
                None,
                record.funding_wallet_id,
                card_id,
                f"Merchant refund of {card_id}",
                idempotency_key,
            )
        )

    async def _card_record(self, card_id: str) -> PartnerCardRecord | None:
        return await PartnerCardRecord.find_one(PartnerCardRecord.card_id == card_id)

    # ---- the ledger -----------------------------------------------------------------------

    async def _replay(self, idempotency_key: str) -> Movement | None:
        entry = await PartnerLedgerRecord.find_one(
            PartnerLedgerRecord.idempotency_key == idempotency_key
        )
        return movement_of(entry) if entry is not None else None

    async def _move(self, leg: _Leg, *, prefix: str = "txn") -> Result[Movement, PartnerError]:
        """Debit (conditional), credit and ledger entry in one transaction; a replayed key
        returns the first movement."""
        if leg.amount_minor <= 0:
            return Err(PartnerError.INSUFFICIENT_FUNDS)
        replay = await self._replay(leg.idempotency_key)
        if replay is not None:
            return Ok(replay)

        async def write(session: AsyncClientSession) -> PartnerLedgerRecord:
            debit_after = await self._debit(leg, session) if leg.debit is not None else None
            credit_after = await self._credit(leg, session) if leg.credit is not None else None
            entry = PartnerLedgerRecord(
                entry_id=_new_id(prefix),
                kind=leg.kind,
                amount_minor=leg.amount_minor,
                debit_wallet_id=leg.debit,
                credit_wallet_id=leg.credit,
                tag=leg.tag,
                reference=leg.reference,
                idempotency_key=leg.idempotency_key,
                debit_balance_after_minor=debit_after,
                credit_balance_after_minor=credit_after,
                created_at=utc_now(),
            )
            return await entry.insert(session=session)

        try:
            entry = await self.db.in_transaction(write)
        except _RefusedError as refused:
            return Err(refused.error)
        except DuplicateKeyError:  # a concurrent replay of the same key won
            replay = await self._replay(leg.idempotency_key)
            if replay is None:
                raise
            return Ok(replay)
        return Ok(movement_of(entry))

    async def _debit(self, leg: _Leg, session: AsyncClientSession) -> int:
        collection = PartnerWalletRecord.get_pymongo_collection()
        if leg.requires_funded:
            wallet = await self._wallet(leg.debit or "", session)
            if wallet is None:
                raise _RefusedError(PartnerError.WALLET_NOT_FOUND)
            if wallet.owner_kind is WalletOwnerKind.TRIP_ESCROW and (
                wallet.release_target_minor <= 0
                or wallet.funded_minor < wallet.release_target_minor
            ):
                raise _RefusedError(PartnerError.ESCROW_NOT_FUNDED)
        changes: dict[str, Any] = {"balance_minor": -leg.amount_minor}
        if leg.kind is LedgerKind.TRANSFER and leg.tag in _REFUND_TAGS:
            changes["funded_minor"] = -leg.amount_minor
        document = await collection.find_one_and_update(
            {"wallet_id": leg.debit, "balance_minor": {"$gte": leg.amount_minor}},
            {"$inc": changes},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if document is None:
            exists = await self._wallet(leg.debit or "", session)
            raise _RefusedError(
                PartnerError.INSUFFICIENT_FUNDS if exists else PartnerError.WALLET_NOT_FOUND
            )
        return int(document["balance_minor"])

    async def _credit(self, leg: _Leg, session: AsyncClientSession) -> int:
        changes: dict[str, Any] = {"balance_minor": leg.amount_minor}
        if leg.kind is LedgerKind.TRANSFER and leg.tag == TransferTag.SHARE.value:
            changes["funded_minor"] = leg.amount_minor
        document = await PartnerWalletRecord.get_pymongo_collection().find_one_and_update(
            {"wallet_id": leg.credit},
            {"$inc": changes},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if document is None:
            raise _RefusedError(PartnerError.WALLET_NOT_FOUND)
        return int(document["balance_minor"])
