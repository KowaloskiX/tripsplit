"""Cassettes: supplier answers recorded once, replayed deterministically and for free.

`RecordingSupplier` wraps any `SupplierAdapter` and stores what `search(request)` and
`quote(offer, party)` answered under `<root>/<supplier>/<hash>.json`:

- `record` — answer from a recording when there is one, else ask the live supplier and record
  it (resumable: a second record run only asks what is still missing);
- `replay` — only recordings; a miss raises `CassetteMiss` (the eval reports it, it never
  silently asks a live supplier);
- `live` — always the live supplier, nothing is written.

What goes into a recording is the offer data only — search requests carry no traveller, and the
wrapper never records `hold` / `purchase` (it refuses them). The key deliberately leaves out two
request fields no adapter reads for a search: the budget, and a mode equal to the supplier's own
(`None` and `rail` ask a rail supplier the same thing), so briefs share recordings. Travel
preferences are part of a transport key only when set (a carrier filters by them).
"""

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.domain.result import Err, Result
from app.core.domain.suppliers import SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import NO_PREFERENCES, BookingKind, SupplierChannel, TransportMode
from app.core.domain.trust import LinkKind, OfferLink, Provenance, ProvenanceSource
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
    Segment,
    SupplierAdapter,
)

type Json = dict[str, Any]
MANIFEST = "suppliers.json"


class CassetteMode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"
    LIVE = "live"


class CassetteMiss(Exception):
    """Replay mode asked for something that was never recorded."""


# ---- (de)serialisation ------------------------------------------------------------------------


def _moment(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_moment(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def segment_json(segment: Segment) -> Json:
    return {
        "carrier": segment.carrier,
        "number": segment.number,
        "origin": segment.origin,
        "destination": segment.destination,
        "departs_at": segment.departs_at.isoformat(),
        "arrives_at": segment.arrives_at.isoformat(),
    }


def segment_of(raw: Mapping[str, Any]) -> Segment:
    return Segment(
        carrier=str(raw["carrier"]),
        number=str(raw["number"]),
        origin=str(raw["origin"]),
        destination=str(raw["destination"]),
        departs_at=datetime.fromisoformat(str(raw["departs_at"])),
        arrives_at=datetime.fromisoformat(str(raw["arrives_at"])),
    )


def offer_json(offer: Offer) -> Json:
    return {
        "supplier_id": offer.supplier_id,
        "offer_ref": offer.offer_ref,
        "title": offer.title,
        "price_minor": offer.price_minor,
        "currency": offer.currency,
        "seller": offer.seller,
        "segments": [segment_json(segment) for segment in offer.segments],
        "refundable": offer.refundable,
        "expires_at": _moment(offer.expires_at),
        "purchase_url": offer.purchase_url,
        "details": offer.details,
        "starts_at": _moment(offer.starts_at),
        # Adapter data is JSON already (it is stored in Mongo as is).
        "supplier_data": json.loads(json.dumps(dict(offer.supplier_data), default=str)),
        "links": [
            {"label": link.label, "url": link.url, "kind": link.kind.value} for link in offer.links
        ],
        "images": list(offer.images),
        "provenance": _provenance_json(offer.provenance),
    }


def _provenance_json(provenance: Provenance | None) -> Json | None:
    if provenance is None:
        return None
    return {
        "source": provenance.source.value,
        "supplier": provenance.supplier,
        "checked_at": provenance.checked_at.isoformat(),
    }


def _provenance_of(raw: Mapping[str, Any] | None) -> Provenance | None:
    if not raw:
        return None
    return Provenance(
        source=ProvenanceSource(str(raw["source"])),
        supplier=str(raw["supplier"]),
        checked_at=datetime.fromisoformat(str(raw["checked_at"])),
    )


def offer_of(raw: Mapping[str, Any]) -> Offer:
    return Offer(
        supplier_id=str(raw["supplier_id"]),
        offer_ref=str(raw["offer_ref"]),
        title=str(raw["title"]),
        price_minor=int(raw["price_minor"]),
        currency=str(raw["currency"]),
        seller=str(raw["seller"]),
        segments=tuple(segment_of(segment) for segment in raw.get("segments") or []),
        refundable=bool(raw.get("refundable", False)),
        expires_at=_parse_moment(raw.get("expires_at")),
        purchase_url=str(raw.get("purchase_url", "")),
        details=str(raw.get("details", "")),
        starts_at=_parse_moment(raw.get("starts_at")),
        supplier_data=dict(raw.get("supplier_data") or {}),
        links=tuple(
            OfferLink(label=str(link["label"]), url=str(link["url"]), kind=LinkKind(link["kind"]))
            for link in raw.get("links") or []
        ),
        images=tuple(str(image) for image in raw.get("images") or []),
        provenance=_provenance_of(raw.get("provenance")),
    )


def quote_json(quote: Quote | None) -> Json | None:
    if quote is None:
        return None
    return {
        "price_minor": quote.price_minor,
        "currency": quote.currency,
        "quoted_at": quote.quoted_at.isoformat(),
        "expires_at": _moment(quote.expires_at),
    }


def quote_of(raw: Mapping[str, Any] | None) -> Quote | None:
    if raw is None:
        return None
    return Quote(
        price_minor=int(raw["price_minor"]),
        currency=str(raw["currency"]),
        quoted_at=datetime.fromisoformat(str(raw["quoted_at"])),
        expires_at=_parse_moment(raw.get("expires_at")),
    )


def request_key(
    request: SearchRequest, own_mode: TransportMode | None, *, transport: bool = True
) -> Json:
    """What identifies a search for the cassette (see the module docstring)."""
    mode = request.mode if request.mode is not None else own_mode
    preferences = request.preferences
    extra: Json = {}
    if transport and preferences != NO_PREFERENCES:
        # Only when set and only for transport (a carrier filters its connections by them);
        # searches without preferences keep their key.
        extra["preferences"] = {
            "earliest_departure_hour": preferences.earliest_departure_hour,
            "max_transfers": preferences.max_transfers,
        }
    return {
        "origin": request.origin.strip().casefold(),
        "destination": request.destination.strip().casefold(),
        "depart_date": request.depart_date.isoformat(),
        "return_date": request.return_date.isoformat() if request.return_date else None,
        "party_size": request.party_size,
        "mode": mode.value if mode is not None else None,
        "currency": request.currency,
        **extra,
    }


def digest(payload: Json) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:20]


# ---- the store --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupplierInfo:
    """Enough of a supplier to replay it without its adapter (no key, no browser)."""

    id: str
    display_name: str
    kind: BookingKind
    mode: TransportMode | None
    channel: SupplierChannel
    max_party_per_purchase: int | None

    def capabilities(self) -> SupplierCapabilities:
        return SupplierCapabilities(
            kind=self.kind,
            mode=self.mode,
            channel=self.channel,
            max_party_per_purchase=self.max_party_per_purchase,
        )

    @classmethod
    def of(cls, adapter: SupplierAdapter) -> "SupplierInfo":
        caps = adapter.capabilities
        return cls(
            adapter.id,
            adapter.display_name,
            caps.kind,
            caps.mode,
            caps.channel,
            caps.max_party_per_purchase,
        )

    def json(self) -> Json:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "kind": self.kind.value,
            "mode": self.mode.value if self.mode else None,
            "channel": self.channel.value,
            "max_party_per_purchase": self.max_party_per_purchase,
        }

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "SupplierInfo":
        mode = raw.get("mode")
        cap = raw.get("max_party_per_purchase")
        return cls(
            id=str(raw["id"]),
            display_name=str(raw["display_name"]),
            kind=BookingKind(str(raw["kind"])),
            mode=TransportMode(str(mode)) if mode else None,
            channel=SupplierChannel(str(raw["channel"])),
            max_party_per_purchase=int(cap) if cap is not None else None,
        )


@dataclass
class CassetteStore:
    root: Path

    def path(self, supplier_id: str, key: str) -> Path:
        return self.root / supplier_id / f"{key}.json"

    def load(self, supplier_id: str, key: str) -> Json | None:
        path = self.path(supplier_id, key)
        if not path.is_file():
            return None
        loaded: Json = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def save(self, supplier_id: str, key: str, payload: Json) -> None:
        path = self.path(supplier_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    def suppliers(self) -> list[SupplierInfo]:
        path = self.root / MANIFEST
        if not path.is_file():
            return []
        return [SupplierInfo.parse(raw) for raw in json.loads(path.read_text(encoding="utf-8"))]

    def register(self, info: SupplierInfo) -> None:
        known = {existing.id: existing for existing in self.suppliers()}
        known[info.id] = info
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [entry.json() for entry in sorted(known.values(), key=lambda i: i.id)]
        (self.root / MANIFEST).write_text(json.dumps(payload, indent=1), encoding="utf-8")


# ---- the wrapper ------------------------------------------------------------------------------


@dataclass
class CallStats:
    """Per supplier: how many searches, how long they took now and when recorded."""

    searches: int = 0
    quotes: int = 0
    misses: int = 0
    live_calls: int = 0
    seconds: float = 0.0  # wall time in this run
    recorded_seconds: float = 0.0  # what the live supplier took when it was recorded
    offers: int = 0

    def json(self) -> Json:
        return {
            "searches": self.searches,
            "quotes": self.quotes,
            "misses": self.misses,
            "live_calls": self.live_calls,
            "seconds": round(self.seconds, 3),
            "recorded_seconds": round(self.recorded_seconds, 2),
            "offers": self.offers,
        }


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RecordingSupplier:
    """A `SupplierAdapter` that records / replays `search` and `quote` (module docstring)."""

    info: SupplierInfo
    store: CassetteStore
    mode: CassetteMode
    inner: SupplierAdapter | None = None
    refresh_empty: bool = False
    stats: CallStats = field(default_factory=CallStats)

    def __post_init__(self) -> None:
        self.id = self.info.id
        self.display_name = self.info.display_name
        self.capabilities = (
            self.inner.capabilities if self.inner is not None else self.info.capabilities()
        )
        if self.mode is not CassetteMode.REPLAY and self.inner is None:
            raise ValueError(f"{self.info.id}: {self.mode} needs the live adapter")

    def _live(self) -> SupplierAdapter:
        if self.inner is None:
            raise CassetteMiss(f"{self.id}: no live adapter in replay mode")
        return self.inner

    async def search(self, request: SearchRequest) -> list[Offer]:
        self.stats.searches += 1
        started = time.monotonic()
        try:
            offers = await self._search(request)
        finally:
            self.stats.seconds += time.monotonic() - started
        self.stats.offers += len(offers)
        return offers

    async def _search(self, request: SearchRequest) -> list[Offer]:
        described = request_key(
            request,
            self.capabilities.mode,
            transport=self.capabilities.kind is BookingKind.TRANSPORT,
        )
        key = digest({"call": "search", "supplier": self.id, **described})
        recorded = None if self.mode is CassetteMode.LIVE else self.store.load(self.id, key)
        if recorded is not None and self.refresh_empty and self.mode is CassetteMode.RECORD:
            recorded = recorded if recorded.get("offers") else None
        if recorded is not None:
            self.stats.recorded_seconds += float(recorded.get("seconds", 0.0))
            return [offer_of(raw) for raw in recorded.get("offers") or []]
        if self.mode is CassetteMode.REPLAY:
            self.stats.misses += 1
            raise CassetteMiss(f"{self.id}: search not recorded: {described}")
        started = time.monotonic()
        offers = await self._live().search(request)
        seconds = time.monotonic() - started
        self.stats.live_calls += 1
        self.stats.recorded_seconds += seconds
        if self.mode is CassetteMode.RECORD:
            self.store.save(
                self.id,
                key,
                {
                    "call": "search",
                    "supplier": self.id,
                    "request": described,
                    "recorded_at": _now().isoformat(),
                    "seconds": round(seconds, 2),
                    "offers": [offer_json(offer) for offer in offers],
                },
            )
        return offers

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        self.stats.quotes += 1
        described = {"offer_ref": offer.offer_ref, "party_size": party_size}
        key = digest({"call": "quote", "supplier": self.id, **described})
        recorded = None if self.mode is CassetteMode.LIVE else self.store.load(self.id, key)
        if recorded is not None:
            return quote_of(recorded.get("quote"))
        if self.mode is CassetteMode.REPLAY:
            self.stats.misses += 1
            raise CassetteMiss(f"{self.id}: quote not recorded: {described}")
        started = time.monotonic()
        quote = await self._live().quote(offer, party_size)
        self.stats.live_calls += 1
        if self.mode is CassetteMode.RECORD:
            self.store.save(
                self.id,
                key,
                {
                    "call": "quote",
                    "supplier": self.id,
                    "request": described,
                    "recorded_at": _now().isoformat(),
                    "seconds": round(time.monotonic() - started, 2),
                    "quote": quote_json(quote),
                },
            )
        return quote

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        return None  # an eval never holds: a hold names travellers

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        return Err("search evals never buy")

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return None
