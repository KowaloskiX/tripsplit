"""Traveller details a supplier may need per passenger. Pure Python.

A document number is personal data with real abuse potential: it travels only to where a
purchase needs it (the agent's private vault, a supplier's purchase API) and never into logs,
feed events, harness reports or LLM prompts. Everything else shows `masked_document_number` or
just which fields are present.
"""

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from app.core.domain.suppliers import TravellerField

_VISIBLE_DOCUMENT_CHARS = 2


class Gender(StrEnum):
    """As on the travel document; airlines ask for it (and derive the title from it)."""

    FEMALE = "female"
    MALE = "male"


@dataclass(frozen=True, slots=True)
class TravellerDetails:
    full_name: str
    date_of_birth: date | None = None
    nationality: str | None = None  # ISO 3166-1 alpha-2, e.g. "PL"
    document_number: str | None = None
    document_expiry: date | None = None
    gender: Gender | None = None

    def __repr__(self) -> str:
        # The dataclass default would print the document number into any log or traceback.
        return (
            f"TravellerDetails(full_name={self.full_name!r}, "
            f"fields={sorted(field.value for field in self.provided_fields())})"
        )

    def provided_fields(self) -> frozenset[TravellerField]:
        present = {
            TravellerField.FULL_NAME: has_full_name(self.full_name),
            TravellerField.DATE_OF_BIRTH: self.date_of_birth is not None,
            TravellerField.NATIONALITY: bool(self.nationality),
            TravellerField.DOCUMENT_NUMBER: bool(self.document_number),
            TravellerField.DOCUMENT_EXPIRY: self.document_expiry is not None,
            TravellerField.GENDER: self.gender is not None,
        }
        return frozenset(field for field, ok in present.items() if ok)


def has_full_name(name: str) -> bool:
    """A carrier needs a first AND a last name."""
    return len(name.split()) >= 2


def split_name(full_name: str) -> tuple[str, str]:
    first, _, last = full_name.strip().partition(" ")
    return first, last.strip()


def with_guests(travellers: list[TravellerDetails], party: int) -> list[TravellerDetails]:
    """`travellers` padded to `party`: the group is bigger than its members when the organizer
    books for friends who never joined. Each missing traveller travels as the lead's guest
    ("Guest2 Mazur") with the lead's other details, so a supplier that wants every
    passenger's fields gets them; nobody's real data is invented."""
    if not travellers or len(travellers) >= party:
        return travellers
    lead = travellers[0]
    first, last = split_name(lead.full_name)
    surname = last or first
    guests = [
        replace(lead, full_name=f"Guest{number} {surname}")
        for number in range(len(travellers) + 1, party + 1)
    ]
    return [*travellers, *guests]


def masked_document_number(number: str | None) -> str | None:
    """`"EH1234567"` -> `"*******67"`: enough to recognise your own document, no more."""
    if not number:
        return None
    visible = number[-_VISIBLE_DOCUMENT_CHARS:]
    return "*" * max(len(number) - _VISIBLE_DOCUMENT_CHARS, 0) + visible


def describe_missing(missing: dict[str, frozenset[TravellerField]]) -> str:
    """`{"Kuba Mazur": {document_number}}` -> "Kuba Mazur (document number)" — names and field
    names only, never values."""
    return "; ".join(
        f"{name} ({', '.join(sorted(field.value.replace('_', ' ') for field in fields))})"
        for name, fields in missing.items()
    )
