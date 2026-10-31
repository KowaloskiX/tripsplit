"""Suppliers became plugins: kind `train` -> kind `transport` + mode `rail`.

Expand-contract:
1. Expand (shipped with this migration's code): `Booking` / `ProposalItem` gained `mode`,
   `supplier_id`, `offer_ref`, `channel`, `supplier_data`, hold fields — all with defaults — and
   both READ the legacy kind `train` as transport + rail (`upgrade_legacy_kind`).
2. Backfill (this file): every new field is written with its default, because the collection
   validators (`app.db.validation`) require every model field to be PRESENT and Mongo's strict
   validation level applies them to updates of old documents too — without the backfill an old
   trip could not even change status. Then stored documents are rewritten to the new
   vocabulary: a PKP booking's `train_query` is copied into `supplier_data` in the shape the
   `pkp_intercity` adapter re-quotes from, and the booking points at that adapter.
3. Contract (a later deploy): drop `train_query` once no reader of it is left. It is NOT
   removed here, so `Backward` can restore the old shape exactly.

    uv run beanie migrate -uri "$MONGODB_URL" -db "$MONGODB_DATABASE" -p migrations
    uv run beanie migrate -uri "$MONGODB_URL" -db "$MONGODB_DATABASE" -p migrations \\
        --backward
"""

from datetime import datetime
from typing import Any

from beanie import free_fall_migration
from pymongo.asynchronous.client_session import AsyncClientSession

from app.models.bookings import Booking
from app.models.trips import Proposal, Trip

LEGACY_KIND = "train"
TRANSPORT = "transport"
RAIL = "rail"
PKP_SUPPLIER = "PKP Intercity"
PKP_ADAPTER = "pkp_intercity"
# The fields this change added, with the defaults the models read for a missing key.
BOOKING_DEFAULTS: dict[str, Any] = {
    "mode": None,
    "supplier_id": "",
    "offer_ref": "",
    "channel": "agent",
    "supplier_data": {},
    "hold_ref": None,
    "hold_expires_at": None,
    "quoted_at": None,
}
TRIP_DEFAULTS: dict[str, Any] = {"destination": "", "transport_mode": None}


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def booking_forward(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The `$set` that upgrades one stored booking, or None when it is already current."""
    if raw.get("kind") != LEGACY_KIND:
        return None
    changes: dict[str, Any] = {"kind": TRANSPORT, "mode": raw.get("mode") or RAIL}
    query = raw.get("train_query")
    if (
        raw.get("supplier") == PKP_SUPPLIER
        and isinstance(query, dict)
        and not raw.get("supplier_id")
    ):
        changes["supplier_id"] = PKP_ADAPTER
        changes["supplier_data"] = {
            "travel_class": query.get("travel_class", 2),
            "refundable": query.get("refundable", False),
            "legs": [
                {
                    "from_code": query["from_code"],
                    "to_code": query["to_code"],
                    "departs_at": _iso(query["departs_at"]),
                    "train_number": query["train_number"],
                }
            ],
        }
    return changes


def booking_backward(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The `$set` that brings one booking back to the old vocabulary. A flight or a bus has no
    old name: the old code only knew trains, so every transport reads as one. `mode` and the
    other added fields stay (the old code ignores them), which makes Forward after Backward
    exact."""
    if raw.get("kind") != TRANSPORT:
        return None
    return {"kind": LEGACY_KIND}


def items_forward(items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not any(item.get("kind") == LEGACY_KIND for item in items):
        return None
    return [
        {**item, "kind": TRANSPORT, "mode": item.get("mode") or RAIL}
        if item.get("kind") == LEGACY_KIND
        else item
        for item in items
    ]


def items_backward(items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not any(item.get("kind") == TRANSPORT for item in items):
        return None
    return [
        {**item, "kind": LEGACY_KIND} if item.get("kind") == TRANSPORT else item for item in items
    ]


async def _backfill(
    model: Any, defaults: dict[str, Any], session: AsyncClientSession | None
) -> None:
    """ONE update per document sets every missing field: strict validation checks the result
    of each update, so adding the fields one by one would fail on the first."""
    collection = model.get_pymongo_collection()
    await collection.update_many(
        {"$or": [{name: {"$exists": False}} for name in defaults]},
        [
            {
                "$set": {
                    name: {"$ifNull": [f"${name}", {"$literal": default}]}
                    for name, default in defaults.items()
                }
            }
        ],
        session=session,
        hint=[("_id", 1)],
    )


async def _rewrite_bookings(
    session: AsyncClientSession | None, wanted_kind: str, change: Any
) -> None:
    collection = Booking.get_pymongo_collection()
    # Hinted on `_id`: a migration walks the collection, but never as a bare collection scan
    # (the servers run with `notablescan` in tests).
    cursor = collection.find({"kind": wanted_kind}, session=session).hint([("_id", 1)])
    async for raw in cursor:
        changes = change(raw)
        if changes:
            await collection.update_one({"_id": raw["_id"]}, {"$set": changes}, session=session)


async def _rewrite_items(session: AsyncClientSession | None, wanted_kind: str, change: Any) -> None:
    collection = Proposal.get_pymongo_collection()
    cursor = collection.find({"items.kind": wanted_kind}, session=session).hint([("_id", 1)])
    async for raw in cursor:
        items = change(raw.get("items") or [])
        if items is not None:
            await collection.update_one(
                {"_id": raw["_id"]}, {"$set": {"items": items}}, session=session
            )


class Forward:
    @free_fall_migration(document_models=[Booking, Proposal, Trip])
    async def transport_with_modes(self, session: AsyncClientSession | None) -> None:
        await _backfill(Booking, BOOKING_DEFAULTS, session)
        await _backfill(Trip, TRIP_DEFAULTS, session)
        await _rewrite_bookings(session, LEGACY_KIND, booking_forward)
        await _rewrite_items(session, LEGACY_KIND, items_forward)


class Backward:
    @free_fall_migration(document_models=[Booking, Proposal])
    async def trains_again(self, session: AsyncClientSession | None) -> None:
        await _rewrite_bookings(session, TRANSPORT, booking_backward)
        await _rewrite_items(session, TRANSPORT, items_backward)
