"""Every database call of the wallet. Balance changes are conditional single-document updates
(`$inc` guarded by `balance_minor >= amount` for a debit, by `status: pending` for a top-up),
always run inside the caller's transaction together with the ledger write."""

from datetime import datetime

from beanie import PydanticObjectId, SortDirection
from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.wallet import (
    WALLET_CURRENCY,
    WalletTransactionKind,
    WalletTransactionStatus,
)
from app.db.documents import utc_now
from app.models.wallet import Wallet, WalletTransaction
from app.repositories.base import bounded_to_list


class WalletRepository:
    async def get(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> Wallet | None:
        return await Wallet.find_one(Wallet.user_id == user_id, session=session)

    async def credit(
        self, user_id: PydanticObjectId, amount_minor: int, session: AsyncClientSession
    ) -> int:
        """Adds to the balance (creating the wallet on first use); the new balance."""
        now = utc_now()
        document = await Wallet.get_pymongo_collection().find_one_and_update(
            {"user_id": user_id},
            {
                "$inc": {"balance_minor": amount_minor},
                "$set": {"updated_at": now},
                "$setOnInsert": {"currency": WALLET_CURRENCY, "created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if document is None:  # pragma: no cover - an upsert always returns the document
            raise LookupError("the wallet upsert returned nothing")
        return int(document["balance_minor"])

    async def debit(
        self, user_id: PydanticObjectId, amount_minor: int, session: AsyncClientSession
    ) -> int | None:
        """Takes from the balance only if it covers `amount_minor`; the new balance, or None
        when the funds are insufficient (nothing is written then)."""
        document = await Wallet.get_pymongo_collection().find_one_and_update(
            {"user_id": user_id, "balance_minor": {"$gte": amount_minor}},
            {"$inc": {"balance_minor": -amount_minor}, "$set": {"updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        return int(document["balance_minor"]) if document is not None else None

    async def delete_for_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await Wallet.find(Wallet.user_id == user_id, session=session).delete(session=session)


class WalletTransactionRepository:
    async def add(
        self, entry: WalletTransaction, session: AsyncClientSession | None = None
    ) -> WalletTransaction:
        return await entry.insert(session=session)

    async def get(
        self, transaction_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> WalletTransaction | None:
        return await WalletTransaction.get(transaction_id, session=session)

    async def complete_pending(
        self,
        transaction_id: PydanticObjectId,
        balance_after_minor: int,
        completed_at: datetime,
        session: AsyncClientSession,
    ) -> bool:
        """pending -> completed, exactly once (compare-and-set on the status)."""
        result = await WalletTransaction.get_pymongo_collection().update_one(
            {"_id": transaction_id, "status": WalletTransactionStatus.PENDING},
            {
                "$set": {
                    "status": WalletTransactionStatus.COMPLETED,
                    "balance_after_minor": balance_after_minor,
                    "completed_at": completed_at,
                }
            },
            session=session,
        )
        return result.modified_count == 1

    async def fail_pending(
        self,
        transaction_id: PydanticObjectId,
        reason: str,
        session: AsyncClientSession | None = None,
    ) -> bool:
        result = await WalletTransaction.get_pymongo_collection().update_one(
            {"_id": transaction_id, "status": WalletTransactionStatus.PENDING},
            {
                "$set": {
                    "status": WalletTransactionStatus.FAILED,
                    "failure_reason": reason,
                    "completed_at": utc_now(),
                }
            },
            session=session,
        )
        return result.modified_count == 1

    async def history(self, user_id: PydanticObjectId, limit: int) -> list[WalletTransaction]:
        """The newest `limit` entries — a page, not "everything", so no truncation warning."""
        query = (
            WalletTransaction.find(WalletTransaction.user_id == user_id)
            .sort([("created_at", SortDirection.DESCENDING)])
            .limit(limit)
        )
        return await query.to_list(limit)

    async def completed_for_trip(
        self, trip_id: PydanticObjectId, kinds: tuple[WalletTransactionKind, ...]
    ) -> list[WalletTransaction]:
        query = WalletTransaction.find(
            {
                "trip_id": trip_id,
                "kind": {"$in": list(kinds)},
                "status": WalletTransactionStatus.COMPLETED,
            }
        )
        return await bounded_to_list(query, what="trip wallet entries")

    async def delete_for_user(
        self, user_id: PydanticObjectId, session: AsyncClientSession | None = None
    ) -> None:
        await WalletTransaction.find(WalletTransaction.user_id == user_id, session=session).delete(
            session=session
        )
