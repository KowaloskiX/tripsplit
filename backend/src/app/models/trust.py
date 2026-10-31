"""How trust data (`app.core.domain.trust`) is stored inside package items and bookings."""

from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.domain.trust import (
    MAX_IMAGES,
    MAX_LINKS,
    LinkKind,
    OfferLink,
    Provenance,
    ProvenanceSource,
)

URL_MAX_LENGTH = 2000
LABEL_MAX_LENGTH = 120


class TrustLink(BaseModel):
    label: str = Field(max_length=LABEL_MAX_LENGTH)
    url: str = Field(max_length=URL_MAX_LENGTH)
    kind: LinkKind


class TrustProvenance(BaseModel):
    source: ProvenanceSource
    supplier: str = Field(max_length=LABEL_MAX_LENGTH)
    checked_at: datetime


def stored_links(links: Iterable[OfferLink | TrustLink]) -> list[TrustLink]:
    return [
        TrustLink(label=link.label[:LABEL_MAX_LENGTH], url=link.url, kind=link.kind)
        for link in links
        if len(link.url) <= URL_MAX_LENGTH
    ][:MAX_LINKS]


def stored_images(images: Iterable[str]) -> list[str]:
    return [image for image in images if len(image) <= URL_MAX_LENGTH][:MAX_IMAGES]


def stored_provenance(
    provenance: Provenance | TrustProvenance | None,
) -> TrustProvenance | None:
    if provenance is None:
        return None
    return TrustProvenance(
        source=provenance.source,
        supplier=provenance.supplier[:LABEL_MAX_LENGTH],
        checked_at=provenance.checked_at,
    )
