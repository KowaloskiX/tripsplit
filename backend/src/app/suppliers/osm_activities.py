"""`osm_activities`: real things to do near a city centre, as free IDEAS — never a purchase.

The best-known sights within a few kilometres of the catalogue city's centre
(`app.core.domain.places`), from Wikipedia's geo search (`nearcoord:`, ranked by Wikipedia's
own relevance — popularity and links) with each article's photo, coordinates, short
description and Wikidata id. A description filter keeps museums, castles, churches, squares,
parks, bridges, towers, markets... and drops universities, stations, ministries, districts and
history articles. One HTTP call (~1 s); timeouts are short (`TIMEOUT_S`) and the answer is cached
per city in-process and on disk (`backend/var/places-cache`), so a demo city answers instantly.

Every offer costs 0 ("free or pay on site"): the research lists them as ideas, the trip flow
never buys one (channel `manual`, `purchase` refuses). `supplier_data` carries what an
itinerary needs: `lat`, `lon`, `kind`, `image_url`, `website`, `wikidata`, `rank`,
`duration_minutes`, `bookable=False`, `provenance="live"`.
"""

import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.domain.places import City, resolve_city
from app.core.domain.result import Err, Result
from app.core.domain.suppliers import SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import BookingKind, SupplierChannel
from app.core.domain.trust import (
    LinkKind,
    OfferLink,
    Provenance,
    ProvenanceSource,
    maps_search_url,
)
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
)

logger = logging.getLogger(__name__)

SUPPLIER_ID = "osm_activities"
DISPLAY_NAME = "Wikipedia sights (ideas)"
SELLER = "Wikipedia"
API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "TripSplit/0.1 (group-trip planner, hackathon demo; trips@tripsplit.example)"
TIMEOUT_S = 3.0
RADIUS_KM = 4
CANDIDATES = 50
MAX_IDEAS = 10
CACHE_TTL = timedelta(days=7)
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "var" / "places-cache"
type Clock = Callable[[], datetime]

CAPABILITIES = SupplierCapabilities(
    kind=BookingKind.ACTIVITY,
    mode=None,
    channel=SupplierChannel.MANUAL,
    max_party_per_purchase=None,
    quote_ttl=timedelta(days=7),
    required_traveller_fields=frozenset(),
)

# Description words of a sight -> its kind (first match wins), for an itinerary.
_KINDS: tuple[tuple[str, str], ...] = (
    ("museum", r"museum|gallery|exhibition"),
    ("viewpoint", r"tower|viewpoint|observation|observatory|hill|lookout"),
    ("food", r"market|food hall"),
    ("experience", r"theat(?:re|er)|opera|concert|zoo|aquarium|amusement|spa|bath"),
    (
        "landmark",
        r"palace|castle|cathedral|church|basilica|synagogue|mosque|monastery|abbey|chapel|"
        r"square|park|garden|bridge|monument|memorial|statue|sculpture|clock|old town|"
        r"historic|fort|citadel|wall|gate|fountain|landmark|island|beach|harbour|city hall|"
        r"town hall|building|cemetery",
    ),
)
_SIGHT = re.compile("|".join(pattern for _, pattern in _KINDS), re.IGNORECASE)
_NOT_A_SIGHT = re.compile(
    r"universit|college|school|conservator|academy|station|ministry|parliament|chamber|senate|"
    r"stadium|district|municipalit|neighbo|cadastral|company|hotel|airport|bank|hospital|"
    r"broadcaster|embassy|uprising|battle|siege|shooting|metropolitan|football|club|"
    r"office|headquarters|court|prison",
    re.IGNORECASE,
)
_DURATION_MINUTES: dict[str, int] = {
    "museum": 120,
    "viewpoint": 60,
    "food": 60,
    "experience": 120,
    "landmark": 45,
}


@dataclass(frozen=True, slots=True)
class Sight:
    title: str
    description: str
    latitude: float
    longitude: float
    rank: int  # 1 = the best known
    url: str
    image_url: str = ""
    wikidata: str = ""

    @property
    def kind(self) -> str:
        return next(
            (kind for kind, pattern in _KINDS if re.search(pattern, self.description, re.I)),
            "landmark",
        )


def search_params(city: City) -> dict[str, str]:
    return {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": f"nearcoord:{RADIUS_KM}km,{city.latitude:.4f},{city.longitude:.4f}",
        "gsrlimit": str(CANDIDATES),
        "gsrnamespace": "0",
        "prop": "pageimages|description|coordinates|pageprops|info",
        "inprop": "url",
        "piprop": "thumbnail",
        "pithumbsize": "800",
        "pilimit": str(CANDIDATES),
        "colimit": str(CANDIDATES),
        "ppprop": "wikibase_item",
    }


def _sight(page: Mapping[str, Any], city: City) -> Sight | None:
    title, description = str(page.get("title", "")), str(page.get("description", ""))
    coordinates = page.get("coordinates")
    if not title or not isinstance(coordinates, list) or not coordinates:
        return None
    if not _SIGHT.search(description) or _NOT_A_SIGHT.search(f"{title} {description}"):
        return None
    if title.casefold() in {city.name.casefold(), city.local_name.casefold()}:
        return None
    point = coordinates[0]
    thumbnail = page.get("thumbnail")
    props = page.get("pageprops")
    return Sight(
        title=title,
        description=description,
        latitude=float(point.get("lat", city.latitude)),
        longitude=float(point.get("lon", city.longitude)),
        rank=int(page.get("index", 0)),
        url=str(page.get("fullurl") or f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"),
        image_url=str(thumbnail.get("source", "")) if isinstance(thumbnail, dict) else "",
        wikidata=str(props.get("wikibase_item", "")) if isinstance(props, dict) else "",
    )


def parse_sights(payload: Any, city: City) -> list[Sight]:
    """The sights of a search answer, the best known first, at most `MAX_IDEAS`."""
    query = payload.get("query") if isinstance(payload, dict) else None
    pages = query.get("pages") if isinstance(query, dict) else None
    sights = [
        sight
        for page in (pages if isinstance(pages, list) else [])
        if isinstance(page, dict) and (sight := _sight(page, city)) is not None
    ]
    return sorted(sights, key=lambda sight: sight.rank)[:MAX_IDEAS]


def offer_of(sight: Sight, request: SearchRequest, city: City, now: datetime) -> Offer:
    kind = sight.kind
    where = f"{sight.latitude:.5f},{sight.longitude:.5f}"
    return Offer(
        supplier_id=SUPPLIER_ID,
        offer_ref=f"idea:{sight.wikidata or sight.title}",
        title=sight.title,
        price_minor=0,
        currency=request.currency,
        seller=SELLER,
        purchase_url=sight.url,
        details=f"{sight.description}. An idea in {city.name}: free or pay on site — "
        "TripSplit buys nothing for it.",
        links=(
            OfferLink(label=f"{sight.title} on Wikipedia", url=sight.url, kind=LinkKind.VERIFY),
            OfferLink(
                label=f"{sight.title} on Google Maps",
                url=maps_search_url(where),
                kind=LinkKind.MAP,
            ),
        ),
        images=(sight.image_url,) if sight.image_url else (),
        provenance=Provenance(ProvenanceSource.LIVE, SELLER, now),
        supplier_data={
            "lat": sight.latitude,
            "lon": sight.longitude,
            "kind": kind,
            "image_url": sight.image_url,
            "website": sight.url,
            "wikidata": sight.wikidata,
            "rank": sight.rank,
            "duration_minutes": _DURATION_MINUTES[kind],
            "price_per_person_minor": 0,
            "bookable": False,
            "provenance": "live",
            "city": city.name,
        },
    )


class OsmActivitiesSupplier:
    id = SUPPLIER_ID
    display_name = DISPLAY_NAME

    def __init__(
        self,
        *,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self.capabilities = CAPABILITIES
        self.cache_dir = cache_dir
        self.transport = transport
        self.clock = clock
        self._memory: dict[str, list[Sight]] = {}

    async def search(self, request: SearchRequest) -> list[Offer]:
        """Ideas for the destination; [] for a city outside the catalogue or when Wikipedia
        does not answer in time — never an exception."""
        city = resolve_city(request.destination)
        if city is None:
            return []
        sights = await self.sights(city)
        now = self.clock()
        return [offer_of(sight, request, city, now) for sight in sights]

    async def sights(self, city: City) -> list[Sight]:
        if city.name in self._memory:
            return self._memory[city.name]
        sights = self._read_cache(city)
        if sights is None:
            sights = await self._fetch(city)
            if sights:
                self._write_cache(city, sights)
        if sights:
            self._memory[city.name] = sights
        return sights

    async def _fetch(self, city: City) -> list[Sight]:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=TIMEOUT_S,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = await client.get(API_URL, params=search_params(city))
                response.raise_for_status()
                sights = parse_sights(response.json(), city)
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Wikipedia sights for %s failed: %s", city.name, error)
            return []
        logger.info(
            "Wikipedia sights for %s: %d in %.1f s",
            city.name,
            len(sights),
            time.monotonic() - started,
        )
        return sights

    def _cache_file(self, city: City) -> Path | None:
        if self.cache_dir is None:
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", city.name.casefold()).strip("-")
        return self.cache_dir / f"sights-{slug}-{city.country_code.lower()}.json"

    def _read_cache(self, city: City) -> list[Sight] | None:
        path = self._cache_file(city)
        if path is None or not path.is_file():
            return None
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            saved = datetime.fromisoformat(stored["saved_at"])
            if self.clock() - saved > CACHE_TTL:
                return None
            return [Sight(**sight) for sight in stored["sights"]]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_cache(self, city: City, sights: Sequence[Sight]) -> None:
        path = self._cache_file(city)
        if path is None:
            return
        stored = {
            "saved_at": self.clock().isoformat(),
            "sights": [
                {
                    "title": s.title,
                    "description": s.description,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                    "rank": s.rank,
                    "url": s.url,
                    "image_url": s.image_url,
                    "wikidata": s.wikidata,
                }
                for s in sights
            ],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(stored, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as error:
            logger.warning("could not cache the sights of %s: %s", city.name, error)

    # ---- an idea is never bought --------------------------------------------------------

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        return Quote(price_minor=0, currency="PLN", quoted_at=self.clock())

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        return None

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        return Err("an idea from Wikipedia: nothing to buy, pay on site if needed")

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return None
