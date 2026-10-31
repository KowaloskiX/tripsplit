"""Trips gained travel preferences: `earliest_departure_hour` and `max_transfers`.

Expand-contract:
1. Expand (shipped with this migration's code): `Trip` has both fields, defaulting to None
   ("no preference"), so the new code reads an old trip before any backfill.
2. Backfill (this file): both keys are written as null on every trip that lacks them, because
   the collection validators (`app.db.validation`) require every model field to be PRESENT and
   strict validation applies to updates of old documents too.
3. Contract: nothing to drop — `Backward` removes the keys again for the previous code.

    uv run beanie migrate -uri "$MONGODB_URL" -db "$MONGODB_DATABASE" -p migrations
"""

from typing import Any

from beanie import free_fall_migration
from pymongo.asynchronous.client_session import AsyncClientSession

from app.models.trips import Trip

PREFERENCE_DEFAULTS: dict[str, Any] = {"earliest_departure_hour": None, "max_transfers": None}


class Forward:
    @free_fall_migration(document_models=[Trip])
    async def trip_preferences(self, session: AsyncClientSession | None) -> None:
        # ONE update per document: strict validation checks the result of each update.
        await Trip.get_pymongo_collection().update_many(
            {"$or": [{name: {"$exists": False}} for name in PREFERENCE_DEFAULTS]},
            [
                {
                    "$set": {
                        name: {"$ifNull": [f"${name}", {"$literal": default}]}
                        for name, default in PREFERENCE_DEFAULTS.items()
                    }
                }
            ],
            session=session,
            hint=[("_id", 1)],
        )


class Backward:
    @free_fall_migration(document_models=[Trip])
    async def no_trip_preferences(self, session: AsyncClientSession | None) -> None:
        # The validator in place is today's (it requires both keys); the previous code's own
        # validator, re-applied by its deploy, does not know them.
        await Trip.get_pymongo_collection().update_many(
            {"$or": [{name: {"$exists": True}} for name in PREFERENCE_DEFAULTS]},
            {"$unset": dict.fromkeys(PREFERENCE_DEFAULTS, "")},
            session=session,
            hint=[("_id", 1)],
            bypass_document_validation=True,
        )
