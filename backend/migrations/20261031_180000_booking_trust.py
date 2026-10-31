"""Bookings gained trust data: `links`, `images` (and `provenance`, a nested model the
collection validator does not check).

Expand-contract:
1. Expand (shipped with this migration's code): `Booking` has the fields with defaults (empty
   lists, None), so the new code reads an old booking before any backfill.
2. Backfill (this file): the keys are written on every booking that lacks them, because the
   collection validators (`app.db.validation`) require every list field to be PRESENT and strict
   validation applies to updates of old documents too.
3. Contract: nothing to drop — `Backward` removes the keys again for the previous code.

    uv run beanie migrate -uri "$MONGODB_URL" -db "$MONGODB_DATABASE" -p migrations
"""

from typing import Any

from beanie import free_fall_migration
from pymongo.asynchronous.client_session import AsyncClientSession

from app.models.bookings import Booking

TRUST_DEFAULTS: dict[str, Any] = {"links": [], "images": [], "provenance": None}


class Forward:
    @free_fall_migration(document_models=[Booking])
    async def booking_trust(self, session: AsyncClientSession | None) -> None:
        # ONE update per document: strict validation checks the result of each update.
        await Booking.get_pymongo_collection().update_many(
            {"$or": [{name: {"$exists": False}} for name in TRUST_DEFAULTS]},
            [
                {
                    "$set": {
                        name: {"$ifNull": [f"${name}", {"$literal": default}]}
                        for name, default in TRUST_DEFAULTS.items()
                    }
                }
            ],
            session=session,
            hint=[("_id", 1)],
        )


class Backward:
    @free_fall_migration(document_models=[Booking])
    async def no_booking_trust(self, session: AsyncClientSession | None) -> None:
        # The validator in place is today's (it requires the keys); the previous code's own
        # validator, re-applied by its deploy, does not know them.
        await Booking.get_pymongo_collection().update_many(
            {"$or": [{name: {"$exists": True}} for name in TRUST_DEFAULTS]},
            {"$unset": dict.fromkeys(TRUST_DEFAULTS, "")},
            session=session,
            hint=[("_id", 1)],
            bypass_document_validation=True,
        )
