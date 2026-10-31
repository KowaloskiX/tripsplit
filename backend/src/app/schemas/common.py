"""Building blocks shared by every request schema."""

import unicodedata

from pydantic import BaseModel, ConfigDict


class StrictRequest(BaseModel):
    """Base for input: trims whitespace and rejects unknown fields.

    `extra="forbid"` is deliberate — a typo in a field name should be a 422, not a silently
    ignored field that somebody assumes was saved.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


def normalize_text(value: str) -> str:
    """NFKC plus removal of control and format characters.

    Without it `"\u200b\u200b"` (two zero-width spaces) passes as a two-character organization
    name, and a name starting with a Cyrillic A (U+0410) impersonates the Latin "Acme" — when
    inviting people to an organization that is a ready-made impersonation vector.
    """
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in normalized if unicodedata.category(ch) not in {"Cc", "Cf"}).strip()
