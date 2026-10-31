"""Traveller details: a member sets their own. Input validated here; the document number is
write-only — responses carry a masked form."""

import re
from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.domain.suppliers import TravellerField
from app.schemas.common import StrictRequest, normalize_text

NAME_MAX_LENGTH = 120
EARLIEST_BIRTH = date(1900, 1, 1)
_NATIONALITY = re.compile(r"^[A-Z]{2}$")
_DOCUMENT_NUMBER = re.compile(r"^[A-Z0-9]{5,20}$")


class TravellerDetailsRequest(StrictRequest):
    """Only the fields sent are changed; null or absent leaves a field as it is."""

    full_name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=2)
    document_number: str | None = Field(default=None, max_length=20)
    document_expiry: date | None = None

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_text(value)
        if len(normalized.split()) < 2:
            raise ValueError("Enter a first and a last name, as on the document.")
        return normalized

    @field_validator("nationality")
    @classmethod
    def _nationality(cls, value: str | None) -> str | None:
        if value is None:
            return None
        upper = value.strip().upper()
        if not _NATIONALITY.fullmatch(upper):
            raise ValueError("Use a two-letter country code, e.g. PL.")
        return upper

    @field_validator("document_number")
    @classmethod
    def _document_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        compact = value.replace(" ", "").upper()
        if not _DOCUMENT_NUMBER.fullmatch(compact):
            # The rejected value is never echoed back: it is a document number.
            raise ValueError("A document number is 5-20 letters and digits.")
        return compact

    @model_validator(mode="after")
    def _dates_make_sense(self) -> Self:
        today = date.today()
        if self.date_of_birth is not None and not (EARLIEST_BIRTH <= self.date_of_birth < today):
            raise ValueError("The date of birth must be in the past.")
        if self.document_expiry is not None and self.document_expiry <= today:
            raise ValueError("The document has expired.")
        return self


class TravellerDetailsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    date_of_birth: date | None
    nationality: str | None
    # `*******67` — the full number is never sent back.
    document_number_masked: str | None
    document_expiry: date | None
    provided: list[TravellerField]
