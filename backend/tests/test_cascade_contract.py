"""Cascade-delete contract — Mongo has no `ON DELETE CASCADE`.

Without this test, adding a collection that points at a user would silently leave orphaned
documents behind after account deletion. That is a GDPR problem, not cosmetics: "delete my
data" has to delete all of it.

The test is behavioural and **self-extending**: it discovers every document with a `user_id`
field, so a new collection enters scope automatically and fails until
`AuthService.delete_user` handles it.
"""

from datetime import date
from typing import Any

from beanie import PydanticObjectId

from app.core.config import Settings
from app.core.domain.result import Ok
from app.db.client import Database
from app.db.identifiers import to_object_id
from app.documents import DOCUMENT_MODELS
from app.models.auth import User
from app.models.travellers import TravellerProfile
from app.models.trips import Contribution, Trip, TripMember, Vote
from app.services.auth import AuthService

EMAIL = "cascade@example.com"
PASSWORD = "correct-horse-battery-staple"


def _models_referencing_user() -> list[type[Any]]:
    return [model for model in DOCUMENT_MODELS if "user_id" in model.model_fields]


async def _join_a_trip(user_id: PydanticObjectId | None) -> None:
    """Registration does not create trip participation, so the fixture adds it: one trip
    joined, one vote cast, one share owed, traveller details kept — every collection that
    carries user_id."""
    assert user_id is not None
    trip = await Trip(
        title="Cascade trip",
        origin="Warszawa",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 22),
        group_size=2,
        organizer_id=user_id,
        invite_code="cascade-invite",
    ).insert()
    assert trip.id is not None
    await TripMember(trip_id=trip.id, user_id=user_id, display_name="Cascade").insert()
    await Vote(trip_id=trip.id, proposal_id=PydanticObjectId(), user_id=user_id).insert()
    await Contribution(trip_id=trip.id, user_id=user_id, amount_minor=10_000).insert()
    await TravellerProfile(user_id=user_id, document_number="EH1234567").insert()


async def test_delete_user_leaves_no_orphans(database: Database, settings: Settings) -> None:
    service = AuthService(database, settings)

    registered = await service.register(
        email=EMAIL, password=PASSWORD, organization_name="Cascade Ltd"
    )
    assert isinstance(registered, Ok), (
        "registration must succeed, otherwise the test checks nothing"
    )
    user_id = registered.value.user.id
    # The service speaks in strings, the database in ObjectId — a raw query has to convert, or
    # it silently matches nothing. See `app.db.identifiers`.
    stored_id = to_object_id(user_id)

    await _join_a_trip(stored_id)

    referencing = _models_referencing_user()
    assert referencing, "no collection carries user_id — the contract would be meaningless"

    # Registration has to populate each of these collections, otherwise the test would pass
    # against empty data.
    for model in referencing:
        count = await model.find({"user_id": stored_id}).count()
        assert count > 0, (
            f"'{model.get_settings().name}' has a user_id field, but registration creates "
            "nothing there. Add fixture data to this test so the cascade is really exercised."
        )

    await service.delete_user(user_id)

    for model in referencing:
        remaining = await model.find({"user_id": stored_id}).count()
        assert remaining == 0, (
            f"After deleting the account, {remaining} documents remain in "
            f"'{model.get_settings().name}'. Add this collection to AuthService.delete_user."
        )
    assert await User.get(stored_id) is None


async def test_deleted_user_cannot_use_old_session(database: Database, settings: Settings) -> None:
    """Deleting an account must revoke the session immediately, not merely remove the user."""
    service = AuthService(database, settings)
    registered = await service.register(
        email="cascade-session@example.com", password=PASSWORD, organization_name="Cascade Two"
    )
    assert isinstance(registered, Ok)

    token = registered.value.token
    assert isinstance(await service.resolve_session(token), Ok)

    await service.delete_user(registered.value.user.id)
    assert not isinstance(await service.resolve_session(token), Ok)
