"""Trust data on offers, packages and bookings: links to book / verify / find each item, where
the data came from, photos — and the research-time link check (404/410 dropped, og:image)."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import httpx
from fastapi import FastAPI

from app.ai.link_check import LinkInspector, og_image
from app.ai.research import PackageItemPlan, PackagePlan
from app.core.domain.trips import BookingKind
from app.core.domain.trust import (
    LinkKind,
    OfferLink,
    ProvenanceSource,
    flight_status_url,
    google_flights_url,
    maps_search_url,
)
from app.suppliers.duffel import flight_links, parse_offer
from app.suppliers.liteapi import Hotel, find_city, hotel_links, parse_hotels
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import SearchRequest
from app.suppliers.sim import sim_supplier
from tests.duffel_fake import fixture
from tests.test_intercity_client import RecordedTransport
from tests.test_trips_flow import (  # noqa: F401 — `member_factory` is a pytest fixture
    MemberFactory,
    _create_trip,
    _research,
    member_factory,
)

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def test_the_link_builders_make_plain_search_urls() -> None:
    assert google_flights_url("WAW", "BCN", date(2026, 11, 20), date(2026, 11, 23)) == (
        "https://www.google.com/travel/flights?q=Flights+from+WAW+to+BCN+on+2026-11-20"
        "+through+2026-11-23"
    )
    assert flight_status_url("LO 401") == "https://www.flightradar24.com/data/flights/lo401"
    assert maps_search_url("Mama Shelter, Prague") == (
        "https://www.google.com/maps/search/?api=1&query=Mama+Shelter%2C+Prague"
    )


async def test_pkp_offers_link_each_leg_to_its_e_ic_results_page() -> None:
    pkp = PkpIntercitySupplier(RecordedTransport())
    (offer,) = await pkp.search(SearchRequest("Warszawa", "Prague", date(2026, 11, 20), None, 6))
    assert offer.provenance is not None
    assert offer.provenance.source is ProvenanceSource.LIVE
    (book,) = offer.links
    assert book.kind is LinkKind.BOOK
    assert book.url.startswith("https://ebilet.intercity.pl/")
    assert "dwyj=2026-11-20" in book.url


def test_duffel_offers_verify_on_google_flights_and_never_offer_a_buy_link() -> None:
    offer = parse_offer(fixture("offer_request_waw_bcn")["data"]["offers"][0])
    assert offer is not None
    links = flight_links(offer)
    assert links[0].kind is LinkKind.VERIFY
    assert links[0].url.startswith("https://www.google.com/travel/flights?")
    assert all(link.kind in (LinkKind.VERIFY, LinkKind.STATUS) for link in links)
    for link in links[1:]:
        assert link.url.startswith("https://www.flightradar24.com/data/flights/")


def test_liteapi_hotels_get_a_map_link_and_their_photos() -> None:
    raw = [
        {
            "id": "lp5",
            "name": "The Julius Prague",
            "address": "Václavská 2",
            "city": "Prague",
            "main_photo": "https://static.cupid.travel/hotels/julius.jpg",
            "thumbnail": "http://insecure.example/thumb.jpg",
            "latitude": 50.0858,
            "longitude": 14.4304,
        }
    ]
    hotel = parse_hotels(raw, find_city("Prague"))["lp5"]
    assert hotel.photos == ("https://static.cupid.travel/hotels/julius.jpg",)
    (link,) = hotel_links(hotel)
    assert link.kind is LinkKind.MAP
    assert "The+Julius+Prague" in link.url
    assert hotel_links(Hotel(id="x", name="Nameless"))[0].url.endswith("query=Nameless")


async def test_simulated_offers_are_examples_without_real_looking_links() -> None:
    sim = sim_supplier("sim_flight", lambda: NOW)
    offers = await sim.search(SearchRequest("Warszawa", "Barcelona", date(2026, 11, 20), None, 2))
    assert offers
    for offer in offers:
        assert offer.links == ()
        assert offer.provenance is not None
        assert offer.provenance.source is ProvenanceSource.EXAMPLE


def _plan(*links: str, images: tuple[str, ...] = ()) -> PackagePlan:
    item = PackageItemPlan(
        kind=BookingKind.STAY,
        title="Hotel",
        supplier="Hotel",
        supplier_url="",
        price_minor=1,
        links=tuple(OfferLink(label=url, url=url, kind=LinkKind.BOOK) for url in links),
        images=images,
    )
    return PackagePlan(title="P", summary="", items=(item,))


def _site(request: httpx.Request) -> httpx.Response:
    match request.url.path:
        case "/gone":
            return httpx.Response(404)
        case "/removed":
            return httpx.Response(410)
        case "/blocked":
            return httpx.Response(403)
        case "/page":
            html = '<html><head><meta property="og:image" content="/img/front.jpg"></head></html>'
            return httpx.Response(200, text=html)
    return httpx.Response(500)


async def test_gone_links_are_dropped_and_photos_come_from_og_image() -> None:
    inspector = LinkInspector(transport=httpx.MockTransport(_site))
    links = ("https://hotel.example/gone", "https://hotel.example/removed")
    kept = ("https://hotel.example/blocked", "https://hotel.example/page")
    flights = "https://www.google.com/travel/flights?q=x"  # ours: never fetched
    (plan,) = await inspector.verify([_plan(*links, *kept, flights)])
    (item,) = plan.items
    assert [link.url for link in item.links] == [*kept, flights]
    assert item.images == ("https://hotel.example/img/front.jpg",)


async def test_an_item_with_photos_keeps_them() -> None:
    inspector = LinkInspector(transport=httpx.MockTransport(_site))
    (plan,) = await inspector.verify(
        [_plan("https://hotel.example/page", images=("https://cdn.example/a.jpg",))]
    )
    assert plan.items[0].images == ("https://cdn.example/a.jpg",)


async def test_a_slow_site_never_holds_the_research_up() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(404)

    inspector = LinkInspector(transport=httpx.MockTransport(slow), timeout_s=10, budget_s=0.2)
    started = asyncio.get_running_loop().time()
    (plan,) = await inspector.verify([_plan("https://slow.example/x")])
    assert asyncio.get_running_loop().time() - started < 1.0
    assert len(plan.items[0].links) == 1  # unfinished = live


def test_og_image_reads_both_attribute_orders_and_twitter() -> None:
    base = "https://site.example/p"
    assert og_image('<meta content="https://c.example/a.png" property="og:image">', base) == (
        "https://c.example/a.png"
    )
    assert og_image('<meta name="twitter:image" content="//c.example/b.png">', base) == (
        "https://c.example/b.png"
    )
    assert og_image("<html></html>", base) == ""


async def test_packages_and_bookings_carry_provenance_over_http(
    app: FastAPI,
    member_factory: MemberFactory,  # noqa: F811 — the fixture imported above
) -> None:
    organizer = await member_factory("trust@example.com")
    trip_id = await _create_trip(organizer)
    proposals: list[dict[str, Any]] = await _research(app, organizer, trip_id)
    item = proposals[0]["items"][0]
    assert item["provenance"]["source"] == "example"
    assert item["links"] == []
    assert item["images"] == []
    closed = await organizer.post(f"/api/trips/{trip_id}/voting/close")
    assert closed.status_code == 200, closed.text
    bookings = (await organizer.get(f"/api/trips/{trip_id}/bookings")).json()["bookings"]
    assert {b["provenance"]["source"] for b in bookings} == {"example"}
    assert all(b["links"] == [] for b in bookings)
