"""`osm_activities`: real sights as free ideas, cached per city, never bought."""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.ai.catalog_research import CatalogResearcher
from app.ai.research import TripBrief
from app.core.domain.result import Err
from app.core.domain.suppliers import SupplierCapabilities
from app.core.domain.trips import BookingKind, SupplierChannel
from app.db.documents import utc_now
from app.suppliers.osm_activities import OsmActivitiesSupplier
from app.suppliers.ports import Offer, OfferRef, SearchRequest
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SimSupplier, sim_supplier

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _page(index: int, title: str, description: str, **extra: Any) -> dict[str, Any]:
    return {
        "index": index,
        "title": title,
        "description": description,
        "coordinates": [{"lat": 59.33, "lon": 18.07}],
        "fullurl": f"https://en.wikipedia.org/wiki/{title}",
        "pageprops": {"wikibase_item": f"Q{index}"},
        **extra,
    }


PAGES = [
    _page(1, "Stockholm", "Capital of Sweden"),
    _page(2, "Stockholm University", "Public university in Sweden"),
    _page(
        4,
        "Vasa Museum",
        "Maritime museum in Stockholm, Sweden",
        thumbnail={"source": "https://upload.wikimedia.org/vasa.jpg"},
    ),
    _page(3, "Stockholm Palace", "Royal palace in Stockholm"),
    _page(5, "Stockholm Central Station", "Railway station in Stockholm"),
    _page(6, "Kaknästornet", "TV tower in Stockholm"),
]


def _request(destination: str) -> SearchRequest:
    return SearchRequest(
        origin="Poznań",
        destination=destination,
        depart_date=date(2026, 11, 20),
        return_date=date(2026, 11, 22),
        party_size=4,
    )


class Wikipedia:
    def __init__(self, status: int = 200) -> None:
        self.calls = 0
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert "TripSplit" in request.headers["User-Agent"]
        assert request.url.params["gsrsearch"].startswith("nearcoord:4km,59.3293,18.0686")
        return httpx.Response(self.status, json={"query": {"pages": PAGES}})


async def test_sights_are_free_ranked_ideas(tmp_path: Path) -> None:
    wiki = Wikipedia()
    supplier = OsmActivitiesSupplier(
        cache_dir=tmp_path, transport=httpx.MockTransport(wiki.handler), clock=lambda: NOW
    )
    offers = await supplier.search(_request("Sztokholmu"))
    assert [offer.title for offer in offers] == ["Stockholm Palace", "Vasa Museum", "Kaknästornet"]
    assert all(offer.price_minor == 0 for offer in offers)
    vasa = offers[1].supplier_data
    assert vasa["kind"] == "museum"
    assert vasa["image_url"] == "https://upload.wikimedia.org/vasa.jpg"
    assert vasa["bookable"] is False
    assert vasa["provenance"] == "live"
    assert vasa["wikidata"] == "Q4"
    assert offers[2].supplier_data["kind"] == "viewpoint"
    assert supplier.capabilities.channel is SupplierChannel.MANUAL
    purchase = await supplier.purchase(
        OfferRef("osm_activities", "x"), [], price_minor=0, hold_ref=None
    )
    assert isinstance(purchase, Err)


async def test_sights_are_cached_in_memory_and_on_disk(tmp_path: Path) -> None:
    wiki = Wikipedia()
    transport = httpx.MockTransport(wiki.handler)
    first = OsmActivitiesSupplier(cache_dir=tmp_path, transport=transport, clock=lambda: NOW)
    await first.search(_request("Stockholm"))
    await first.search(_request("Sztokholm"))
    assert wiki.calls == 1
    again = OsmActivitiesSupplier(cache_dir=tmp_path, transport=transport, clock=lambda: NOW)
    assert len(await again.search(_request("Stockholm"))) == 3
    assert wiki.calls == 1


async def test_a_failure_or_an_unknown_city_means_no_ideas(tmp_path: Path) -> None:
    wiki = Wikipedia(status=503)
    supplier = OsmActivitiesSupplier(
        cache_dir=tmp_path, transport=httpx.MockTransport(wiki.handler), clock=lambda: NOW
    )
    assert await supplier.search(_request("Stockholm")) == []
    assert await supplier.search(_request("Atlantis")) == []


@dataclass
class RealStays:
    """A non-simulated stays supplier (plays LiteAPI): nothing, or the simulator's offers."""

    empty: bool
    id: str = "real_stays"
    display_name: str = "LiteAPI hotels"
    inner: SimSupplier = field(default_factory=lambda: sim_supplier("sim_stay", utc_now))

    @property
    def capabilities(self) -> SupplierCapabilities:
        return replace(self.inner.capabilities, simulated=False)

    async def search(self, request: SearchRequest) -> list[Offer]:
        if self.empty:
            return []
        return [replace(offer, supplier_id=self.id) for offer in await self.inner.search(request)]


def _prague_ideas(request: httpx.Request) -> httpx.Response:
    pages = [_page(1, "Charles Bridge", "Medieval stone arch bridge in Prague")]
    return httpx.Response(200, json={"query": {"pages": pages}})


def _researcher(real_stays_empty: bool, tmp_path: Path) -> CatalogResearcher:
    ideas = OsmActivitiesSupplier(cache_dir=tmp_path, transport=httpx.MockTransport(_prague_ideas))
    adapters: list[Any] = [
        sim_supplier("sim_rail", utc_now),
        RealStays(empty=real_stays_empty),
        sim_supplier("sim_stay", utc_now),
        sim_supplier("sim_activity", utc_now),
        ideas,
    ]
    return CatalogResearcher(SupplierRegistry(adapters))


BRIEF = TripBrief(
    title="Weekend",
    origin="Warszawa",
    brief="z Warszawy do Pragi",
    date_from=date(2026, 11, 20),
    date_to=date(2026, 11, 22),
    travellers=4,
)


async def test_example_stays_only_when_the_real_supplier_has_none(tmp_path: Path) -> None:
    plans = await _researcher(real_stays_empty=True, tmp_path=tmp_path).research(BRIEF)
    for plan in plans:
        assert "No hotels found from LiteAPI hotels for Prague" in plan.summary
        assert "Ideas in Prague (free or pay on site): Charles Bridge." in plan.summary
        stays = [item for item in plan.items if item.kind is BookingKind.STAY]
        assert stays
        assert {item.supplier_id for item in stays} == {"sim_stay"}
        # An idea is never an item to buy.
        assert all(item.price_minor > 0 for item in plan.items)


async def test_real_stays_win_over_examples(tmp_path: Path) -> None:
    plans = await _researcher(real_stays_empty=False, tmp_path=tmp_path).research(BRIEF)
    stays = {item.supplier_id for p in plans for item in p.items if item.kind is BookingKind.STAY}
    assert stays == {"real_stays"}
    assert all("No hotels found" not in plan.summary for plan in plans)
