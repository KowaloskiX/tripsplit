"""Traveller details: a member keeps their own, the trip flow checks what a supplier needs.

The document number never leaves this module except as `TravellerDetails` handed to a purchase
(the agent's private vault, a supplier API). Read models carry which fields are present and a
masked number; events and logs carry names and field names only.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from beanie import PydanticObjectId

from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import TravellerField, missing_traveller_fields
from app.core.domain.travellers import Gender, TravellerDetails, masked_document_number
from app.db.identifiers import to_object_id
from app.models.travellers import TravellerProfile
from app.models.trips import TripMember
from app.repositories.travellers import TravellerProfileRepository


@dataclass(frozen=True, slots=True)
class TravellerDetailsUpdate:
    """What a member sends about themselves; None leaves a field as it is."""

    full_name: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    document_number: str | None = None
    document_expiry: date | None = None
    gender: Gender | None = None


@dataclass(frozen=True, slots=True)
class MyTravellerDetailsView:
    full_name: str
    date_of_birth: date | None
    nationality: str | None
    document_number_masked: str | None
    document_expiry: date | None
    gender: Gender | None
    provided: tuple[TravellerField, ...]


def details_of(member: TripMember, profile: TravellerProfile | None) -> TravellerDetails:
    if profile is None:
        return TravellerDetails(full_name=member.display_name)
    return TravellerDetails(
        full_name=profile.full_name or member.display_name,
        date_of_birth=profile.date_of_birth,
        nationality=profile.nationality,
        document_number=profile.document_number,
        document_expiry=profile.document_expiry,
        gender=profile.gender,
    )


class TravellerService:
    def __init__(self) -> None:
        self.profiles = TravellerProfileRepository()

    async def details_for(
        self, members: Sequence[TripMember]
    ) -> dict[PydanticObjectId, TravellerDetails]:
        """Each member's details: their profile, with the trip display name as the fallback."""
        profiles = await self.profiles.for_users([member.user_id for member in members])
        return {
            member.user_id: details_of(member, profiles.get(member.user_id)) for member in members
        }

    async def missing(
        self, members: Iterable[TripMember], required: frozenset[TravellerField]
    ) -> dict[PydanticObjectId, frozenset[TravellerField]]:
        """Which user of `members` lacks which of the `required` fields."""
        listed = list(members)
        if not required:
            return {}
        details = await self.details_for(listed)
        provided = {user_id: found.provided_fields() for user_id, found in details.items()}
        return missing_traveller_fields(required, provided)

    async def mine(self, user_id: str) -> Result[MyTravellerDetailsView, TripError]:
        user_oid = to_object_id(user_id)
        if user_oid is None:
            return Err(TripError.NOT_FOUND)
        return Ok(_view(await self.profiles.get(user_oid)))

    async def update_mine(
        self, user_id: str, update: TravellerDetailsUpdate
    ) -> Result[MyTravellerDetailsView, TripError]:
        user_oid = to_object_id(user_id)
        if user_oid is None:
            return Err(TripError.NOT_FOUND)
        changes = {
            name: value
            for name, value in (
                ("full_name", update.full_name),
                ("date_of_birth", update.date_of_birth),
                ("nationality", update.nationality),
                ("document_number", update.document_number),
                ("document_expiry", update.document_expiry),
                ("gender", update.gender),
            )
            if value is not None
        }
        return Ok(_view(await self.profiles.upsert(user_oid, changes)))


def _view(profile: TravellerProfile | None) -> MyTravellerDetailsView:
    details = TravellerDetails(
        full_name=profile.full_name if profile else "",
        date_of_birth=profile.date_of_birth if profile else None,
        nationality=profile.nationality if profile else None,
        document_number=profile.document_number if profile else None,
        document_expiry=profile.document_expiry if profile else None,
        gender=profile.gender if profile else None,
    )
    return MyTravellerDetailsView(
        full_name=profile.full_name if profile else "",
        date_of_birth=details.date_of_birth,
        nationality=details.nationality,
        document_number_masked=masked_document_number(details.document_number),
        document_expiry=details.document_expiry,
        gender=details.gender,
        provided=tuple(sorted(details.provided_fields())),
    )
