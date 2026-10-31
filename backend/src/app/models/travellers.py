"""Traveller details a user keeps for bookings that need more than a name.

One document per USER (not per trip): a passport does not change between trips. It points at a
user, so `AuthService.delete_user` deletes it (tests/test_cascade_contract.py). The document
number is personal data: it is read only to fill a booking's vault or a supplier purchase, and
every other reader sees which fields are present (see `app.core.domain.travellers`).
"""

from datetime import date
from typing import ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import Field

from app.core.domain.travellers import Gender
from app.db.documents import TimestampMixin

NAME_MAX_LENGTH = 120


class TravellerProfile(TimestampMixin, Document):
    user_id: PydanticObjectId
    # The name exactly as on the document; empty = the trip display name is used.
    full_name: str = Field(default="", max_length=NAME_MAX_LENGTH)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=2)
    document_number: str | None = Field(default=None, max_length=20)
    document_expiry: date | None = None
    gender: Gender | None = None

    def __repr__(self) -> str:
        return f"TravellerProfile(user_id={self.user_id!s})"

    class Settings:
        name: ClassVar[str] = "traveller_profiles"
        indexes: ClassVar[list[pymongo.IndexModel]] = [
            pymongo.IndexModel([("user_id", 1)], unique=True, name="uq_traveller_profiles_user"),
        ]
