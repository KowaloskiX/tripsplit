"""The `liteapi` stays adapter on answers shaped like the recorded sandbox ones (2026-10-31) —
no network: an `httpx.MockTransport` plays LiteAPI.

`LITEAPI_LIVE=1` (plus a sandbox `LITEAPI_KEY` in the environment) additionally runs one search
and quote against the real sandbox; it never prebooks or books.
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.domain.result import Err, Ok
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import BookingKind, SupplierChannel
from app.suppliers.liteapi import (
    CAPABILITIES,
    HOLD_TTL,
    Hotel,
    LiteApiConfig,
    LiteApiSupplier,
    RoomOffer,
    book_request,
    find_city,
    mask_names,
    match_offer,
    occupancies_for,
    parse_hotels,
    parse_rates,
    rates_request,
    rooms_of,
    select_offers,
    to_minor,
)
from app.suppliers.liteapi_client import (
    LiteApiClient,
    LiteApiFailure,
    check_key,
    outcome_of,
)
from app.suppliers.ports import BookingRef, DisruptionKind, OfferRef, SearchRequest
from app.suppliers.providers import build_registry, liteapi_config

NOW = datetime(2026, 10, 31, 4, 0, tzinfo=UTC)
SANDBOX_KEY = SecretStr("sand_00000000-test-only")
PRAGUE = SearchRequest(
    origin="Warszawa",
    destination="Prague",
    depart_date=date(2026, 11, 20),
    return_date=date(2026, 11, 22),
    party_size=6,
)
SIX = [
    TravellerDetails(full_name=name)
    for name in (
        "Anna Kowalska",
        "Kuba Mazur",
        "Marta Lis",
        "Piotr Nowak",
        "Zosia Wrona",
        "Tomek Dudek",
    )
]


# ---- recorded-shape payloads ------------------------------------------------------------------


def _hotel(hotel_id: str, name: str, stars: int, rating: float, lat: float, lon: float) -> Any:
    return {
        "id": hotel_id,
        "name": name,
        "stars": stars,
        "rating": rating,
        "reviewCount": 1000,
        "latitude": lat,
        "longitude": lon,
        "country": "CZ",
        "city": "Prague",
    }


HOTELS = [
    _hotel("lp1", "Hotel Duo & Wellness", 4, 8.6, 50.1160, 14.4980),  # ~6 km out
    _hotel("lp2", "Comfort Hotel Prague City", 4, 8.7, 50.0950, 14.4500),
    _hotel("lp3", "MOSAIC HOUSE Design Hotel", 4, 9.8, 50.0780, 14.4180),
    _hotel("lp4", "Mama Shelter Prague", 4, 8.9, 50.1000, 14.4300),
    _hotel("lp5", "The Julius Prague", 5, 9.8, 50.0858, 14.4304),  # 0.7 km
    _hotel("lp6", "Hostel Nowhere", 0, 0.0, 50.0, 14.3),
]


def _rate(occupancy: int, name: str, amount: float, tag: str, board: str = "RO") -> Any:
    return {
        "occupancyNumber": occupancy,
        "name": name,
        "boardType": board,
        "boardName": "Room Only" if board == "RO" else "Breakfast Included",
        "retailRate": {
            "total": [{"amount": amount, "currency": "PLN"}],
            "taxesAndFees": [
                {"included": True, "description": "Sales tax", "amount": 10.0, "currency": "PLN"},
                {"included": False, "description": "City Tax", "amount": 35.34, "currency": "PLN"},
            ],
        },
        "cancellationPolicies": {"refundableTag": tag},
    }


def _room(
    offer_id: str,
    room_type: str,
    name: str,
    per_room: float,
    tag: str = "NRFN",
    rooms: int = 3,
    board: str = "RO",
    currency: str = "PLN",
) -> Any:
    return {
        "roomTypeId": room_type,
        "offerId": offer_id,
        "offerRetailRate": {"amount": round(per_room * rooms, 2), "currency": currency},
        "rates": [_rate(n, name, per_room, tag, board) for n in range(rooms, 0, -1)],
    }


RATES: dict[str, list[Any]] = {
    "lp1": [_room("o1", "rt1", "Superior Twin/Double", 557.33)],
    "lp2": [_room("o2", "rt2", "Standard Double or Twin Room", 587.41, board="BI")],
    "lp3": [_room("o3", "rt3", "Standard Room", 650.00)],
    "lp4": [
        _room("o4b", "rt4b", "SMALL MAMA", 700.00),
        _room("o4", "rt4", "MEDIUM MAMA DOUBLE", 775.32, tag="RFN"),
    ],
    "lp5": [_room("o5", "rt5", "Studio, Deluxe", 1972.31)],
    "lp6": [_room("o6", "rt6", "Dorm", 100.0, currency="EUR")],  # wrong currency: skipped
}


@dataclass
class FakeLiteApi:
    """Plays LiteAPI: content, rates, prebook, book, retrieve. Records every request."""

    rates: dict[str, list[Any]] = field(default_factory=lambda: dict(RATES))
    # offerId -> price at prebook; missing = 400 code 2001 "no prebook availability".
    prebookable: dict[str, float] = field(default_factory=dict)
    book_status: int = 200
    book_error: Any = None
    booking_state: str = "CONFIRMED"
    requests: list[tuple[str, str, Any]] = field(default_factory=list)
    prebooks: int = 0
    fail_with: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/v3.0")
        self.requests.append((request.method, path, body))
        assert request.headers["X-API-Key"] == SANDBOX_KEY.get_secret_value()
        if self.fail_with is not None:
            return httpx.Response(self.fail_with, json={"error": {"code": 500}})
        if path == "/data/hotels":
            return httpx.Response(200, json={"data": HOTELS})
        if path == "/hotels/rates":
            data = [
                {"hotelId": hotel_id, "roomTypes": self.rates.get(hotel_id, [])}
                for hotel_id in body["hotelIds"]
                if self.rates.get(hotel_id)
            ]
            return httpx.Response(200, json={"data": data, "sandbox": True})
        if path == "/rates/prebook":
            price = self.prebookable.get(body["offerId"])
            if price is None:
                error = {"code": 2001, "description": "no prebook availability"}
                return httpx.Response(400, json={"error": error})
            self.prebooks += 1
            prebooked = {"prebookId": f"pb{self.prebooks}", "price": price, "currency": "PLN"}
            return httpx.Response(200, json={"data": prebooked})
        if path == "/rates/book":
            if self.book_error is not None:
                return httpx.Response(self.book_status, json={"error": self.book_error})
            booked = {
                "bookingId": f"BK-{body['prebookId']}",
                "status": "CONFIRMED",
                "price": 2325.96,
                "currency": "PLN",
                "sandbox": 1,
            }
            return httpx.Response(200, json={"data": booked})
        if path.startswith("/bookings/"):
            return httpx.Response(200, json={"data": {"status": self.booking_state}})
        return httpx.Response(404, json={"error": {"code": 404, "message": "not found"}})


def _supplier(
    fake: FakeLiteApi, *, verify: bool = False, clock: Callable[[], datetime] = lambda: NOW
) -> LiteApiSupplier:
    client = LiteApiClient(SANDBOX_KEY, transport=httpx.MockTransport(fake.handler), backoff_s=0.0)
    return LiteApiSupplier(
        client, LiteApiConfig(api_key=SANDBOX_KEY), clock, verify_availability=verify
    )


def _ref(offer: Any) -> OfferRef:
    return OfferRef(offer.supplier_id, offer.offer_ref, offer.supplier_data)


# ---- pure helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("party", "rooms"),
    [(0, ()), (1, (1,)), (2, (2,)), (3, (3,)), (5, (2, 3)), (6, (2, 2, 2)), (7, (2, 2, 3))],
)
def test_occupancies_pair_the_adults_and_put_an_odd_one_in_a_triple(
    party: int, rooms: tuple[int, ...]
) -> None:
    assert occupancies_for(party) == rooms
    assert sum(rooms) == party


def test_rooms_follow_the_traveller_order() -> None:
    rooms = rooms_of(SIX[:5])
    assert [[t.full_name for t in room] for room in rooms] == [
        ["Anna Kowalska", "Kuba Mazur"],
        ["Marta Lis", "Piotr Nowak", "Zosia Wrona"],
    ]


def test_money_is_converted_half_up() -> None:
    assert to_minor(1698.66) == 169866
    assert to_minor("3781.625") == 378163
    assert to_minor("n/a") is None
    assert to_minor(float("nan")) is None


def test_cities_map_to_liteapi_country_and_name() -> None:
    city = find_city(" Praha ")
    assert city is not None and (city.country_code, city.name) == ("CZ", "Prague")
    assert find_city("Atlantis") is None


def test_rates_parse_the_whole_party_price_and_the_terms() -> None:
    parsed = parse_rates([{"hotelId": "lp4", "roomTypes": RATES["lp4"]}], "PLN")
    cheap, refundable = parsed["lp4"]
    assert cheap.price_minor == 210000 and not cheap.refundable
    assert refundable.price_minor == 232596 and refundable.refundable
    assert refundable.rate_names == ("MEDIUM MAMA DOUBLE",) * 3
    assert refundable.excluded_fees_minor == 3 * 3534  # city tax per room, paid at the hotel
    assert parse_rates([{"hotelId": "lp6", "roomTypes": RATES["lp6"]}], "PLN") == {}


def test_hotels_parse_distance_from_the_centre() -> None:
    hotels = parse_hotels(HOTELS, find_city("Prague"))
    assert hotels["lp5"].km_from_centre is not None and hotels["lp5"].km_from_centre < 1.0
    assert hotels["lp1"].km_from_centre is not None and hotels["lp1"].km_from_centre > 4.0
    assert hotels["lp6"].stars is None and hotels["lp6"].rating is None


def test_selection_covers_cheapest_value_refundable_and_central_premium() -> None:
    hotels = parse_hotels(HOTELS, find_city("Prague"))
    rates = parse_rates([{"hotelId": h, "roomTypes": rooms} for h, rooms in RATES.items()], "PLN")
    picks = select_offers(hotels, rates)
    whys = {pick.why: pick.hotel.name for pick in picks}
    assert whys["cheapest"] == "Hotel Duo & Wellness"
    assert whys["a step up"] == "Comfort Hotel Prague City"
    assert whys["best value"] == "MOSAIC HOUSE Design Hotel"  # 9.8 at or under the median
    assert whys["free cancellation"] == "Mama Shelter Prague"
    assert whys["central premium"] == "The Julius Prague"
    assert len({pick.hotel.id for pick in picks}) == len(picks) == 5  # lp6: no PLN rates
    refundable = next(pick for pick in picks if pick.why == "free cancellation")
    assert refundable.offer.offer_id == "o4"  # the refundable room, not the hotel's cheapest


def test_selection_without_rates_is_empty() -> None:
    assert select_offers({"lp1": Hotel("lp1", "X")}, {}) == []


def _offer(**overrides: Any) -> RoomOffer:
    base: dict[str, Any] = {
        "hotel_id": "lp4",
        "offer_id": "new",
        "room_type_id": "rt4",
        "price_minor": 240000,
        "currency": "PLN",
        "rate_names": ("MEDIUM MAMA DOUBLE",) * 3,
        "board_type": "RO",
        "board_name": "Room Only",
        "refundable": True,
    }
    return RoomOffer(**{**base, **overrides})


def test_a_fresh_answer_is_matched_on_room_type_board_and_terms() -> None:
    original = {
        "room_type_id": "rt4",
        "board_type": "RO",
        "refundable_tag": "RFN",
        "rate_names": ["MEDIUM MAMA DOUBLE"] * 3,
    }
    same = _offer(price_minor=250000)
    cheaper_same = _offer(offer_id="cheaper", price_minor=230000)
    other_terms = _offer(offer_id="nrfn", refundable=False, price_minor=100)
    assert match_offer(original, [same, cheaper_same, other_terms]) is cheaper_same
    renamed = _offer(offer_id="renamed", room_type_id="rt9")
    assert match_offer(original, [renamed]) is renamed  # same names, board and terms
    assert match_offer(original, [other_terms]) is None


def test_request_bodies() -> None:
    body = rates_request(["lp1"], date(2026, 11, 20), date(2026, 11, 22), 5, "PLN", 15)
    assert body["occupancies"] == [{"adults": 2}, {"adults": 3}]
    assert body["maxRatesPerHotel"] == 15 and body["guestNationality"] == "PL"
    assert "maxRatesPerHotel" not in rates_request(["lp1"], "a", "b", 2, "PLN", None)

    book = book_request("pb1", SIX[:5], "trips@x.example", "+48500")
    assert book["prebookId"] == "pb1" and book["clientReference"] == "tripsplit-pb1"
    assert book["holder"] == {
        "firstName": "Anna",
        "lastName": "Kowalska",
        "email": "trips@x.example",
        "phone": "+48500",
    }
    assert [(g["occupancyNumber"], g["firstName"], g["lastName"]) for g in book["guests"]] == [
        (1, "Anna", "Kowalska"),
        (2, "Marta", "Lis"),
    ]
    assert book["payment"] == {"method": "ACC_CREDIT_CARD"}


def test_names_are_masked_in_supplier_text() -> None:
    assert mask_names("guest Anna Kowalska invalid", SIX[:1]) == "guest *** *** invalid"


# ---- the key guard, the client ----------------------------------------------------------------


def test_only_a_sandbox_key_is_accepted_unless_live_is_allowed() -> None:
    assert isinstance(check_key("sand_abc", allow_live=False), Ok)
    refused = check_key("prod_abc", allow_live=False)
    assert isinstance(refused, Err) and "prod_abc" not in refused.error
    assert isinstance(check_key("prod_abc", allow_live=True), Ok)
    assert isinstance(check_key("", allow_live=True), Err)
    with pytest.raises(ValueError, match="sandbox"):
        LiteApiClient(SecretStr("live_key"))


def test_settings_build_the_supplier_only_with_a_usable_key() -> None:
    def settings(key: SecretStr | None, *, allow_live: bool = False) -> Settings:
        return Settings(
            app_env="test",
            suppliers="sim_rail,liteapi",
            liteapi_key=key,
            liteapi_allow_live=allow_live,
        )

    assert liteapi_config(settings(None)) is None
    assert liteapi_config(settings(SecretStr("live_key"))) is None
    assert liteapi_config(settings(SecretStr("live_key"), allow_live=True)) is not None
    config = liteapi_config(settings(SANDBOX_KEY))
    assert config is not None
    assert build_registry(["sim_rail", "liteapi"], None).ids == ["sim_rail"]
    assert build_registry(["sim_rail", "liteapi"], None, liteapi=config).ids == [
        "sim_rail",
        "liteapi",
    ]


def test_answers_map_to_ok_err_and_empty() -> None:
    assert outcome_of(200, {"data": [1]}) == Ok([1])
    assert outcome_of(200, {"error": {"code": 2001, "message": "no availability found"}}) == Ok([])
    refused = outcome_of(400, {"error": {"code": 4002, "description": "invalid prebookId"}})
    assert refused == Err(LiteApiFailure(400, 4002, "invalid prebookId"))
    assert outcome_of(401, None) == Err(LiteApiFailure(401))


async def test_server_errors_are_retried_then_reported_unavailable() -> None:
    from app.suppliers.ports import SupplierUnavailableError

    fake = FakeLiteApi(fail_with=503)
    supplier = _supplier(fake)
    with pytest.raises(SupplierUnavailableError):
        await supplier.quote(OfferRef("liteapi", "x", {"hotel_id": "lp1"}), 6)
    assert len(fake.requests) == 3  # one call + two retries
    fake.requests.clear()
    assert await supplier.search(PRAGUE) == []  # a search never raises
    assert supplier.log.notes == ["the LiteAPI search failed"]


async def test_a_booking_is_never_retried() -> None:
    fake = FakeLiteApi(fail_with=502)
    supplier = _supplier(fake)
    bought = await supplier.purchase(
        OfferRef("liteapi", "x", {}), SIX, price_minor=1, hold_ref="pb1"
    )
    assert isinstance(bought, Err) and "client reference" in bought.error
    assert [path for _, path, _ in fake.requests] == ["/rates/book"]


# ---- the adapter end to end on the fake ------------------------------------------------------


def test_capabilities() -> None:
    assert CAPABILITIES.kind is BookingKind.STAY and CAPABILITIES.channel is SupplierChannel.API
    assert CAPABILITIES.supports_hold and CAPABILITIES.hold_ttl == HOLD_TTL
    assert CAPABILITIES.max_party_per_purchase is None


async def test_search_returns_whole_party_offers_with_supplier_data() -> None:
    supplier = _supplier(FakeLiteApi())
    offers = await supplier.search(PRAGUE)
    assert [o.seller for o in offers][:2] == ["Hotel Duo & Wellness", "Comfort Hotel Prague City"]
    duo = offers[0]
    assert duo.price_minor == 167199 and duo.currency == "PLN" and not duo.refundable
    assert duo.title == "Hotel Duo & Wellness — 3x Superior Twin/Double"
    assert "2 night(s) for 6 guests in 3 room(s)" in duo.details
    assert duo.supplier_data["occupancies"] == [2, 2, 2]
    assert duo.supplier_data["offer_id"] == "o1"
    assert (duo.supplier_data["stars"], duo.supplier_data["rating"]) == (4, 8.6)
    assert duo.supplier_data["review_count"] == 1000 and duo.supplier_data["why"] == "cheapest"
    assert duo.supplier_data["km_from_centre"] > 4.0
    assert duo.expires_at == NOW + CAPABILITIES.quote_ttl
    assert (
        await supplier.search(SearchRequest("Warszawa", "Atlantis", date(2026, 11, 20), None, 6))
        == []
    )


async def test_search_keeps_only_prebookable_picks_when_verifying() -> None:
    fake = FakeLiteApi(prebookable={"o1": 1671.99, "o4": 2325.96, "o5": 5916.93})
    offers = await _supplier(fake, verify=True).search(PRAGUE)
    assert {o.supplier_data["offer_id"] for o in offers} == {"o1", "o4", "o5"}


async def test_quote_matches_the_same_room_or_reports_it_gone() -> None:
    fake = FakeLiteApi()
    supplier = _supplier(fake)
    offers = await supplier.search(PRAGUE)
    mama = next(o for o in offers if o.supplier_data["hotel_id"] == "lp4")
    fake.rates["lp4"] = [_room("o4-new", "rt4", "MEDIUM MAMA DOUBLE", 800.0, tag="RFN")]
    quote = await supplier.quote(_ref(mama), 6)
    assert quote is not None and quote.price_minor == 240000
    fake.rates["lp4"] = [_room("o4-x", "rt4", "MEDIUM MAMA DOUBLE", 800.0, tag="NRFN")]
    assert await supplier.quote(_ref(mama), 6) is None


async def test_hold_prebooks_and_falls_back_to_an_equivalent_offer() -> None:
    fake = FakeLiteApi(prebookable={"o4": 2325.96})
    supplier = _supplier(fake)
    mama = next(o for o in await supplier.search(PRAGUE) if o.supplier_data["hotel_id"] == "lp4")

    hold = await supplier.hold(_ref(mama), SIX)
    assert hold is not None
    assert (hold.ref, hold.price_minor, hold.expires_at) == ("pb1", 232596, NOW + HOLD_TTL)

    # The stored offer went stale; the same room from a fresh search is prebooked instead.
    fake.prebookable = {"o4-fresh": 2330.0}
    fake.rates["lp4"] = [
        _room("o4-dead", "rt4", "MEDIUM MAMA DOUBLE", 770.0, tag="RFN"),
        _room("o4-fresh", "rt4", "MEDIUM MAMA DOUBLE", 776.67, tag="RFN"),
    ]
    again = await supplier.hold(_ref(mama), SIX)
    assert again is not None and again.price_minor == 233000

    fake.prebookable = {}
    assert await supplier.hold(_ref(mama), SIX) is None  # sold out


async def test_a_smaller_party_is_rerated_before_the_prebook() -> None:
    fake = FakeLiteApi(prebookable={"o4-five": 1900.0})
    supplier = _supplier(fake)
    mama = next(o for o in await supplier.search(PRAGUE) if o.supplier_data["hotel_id"] == "lp4")
    fake.rates["lp4"] = [_room("o4-five", "rt4", "MEDIUM MAMA DOUBLE", 950.0, "RFN", rooms=2)]
    hold = await supplier.hold(_ref(mama), SIX[:5])
    assert hold is not None and hold.price_minor == 190000
    rates_bodies = [body for _, path, body in fake.requests if path == "/hotels/rates"]
    assert rates_bodies[-1]["occupancies"] == [{"adults": 2}, {"adults": 3}]


async def test_purchase_books_on_the_hold_with_a_lead_guest_per_room() -> None:
    fake = FakeLiteApi(prebookable={"o4": 2325.96})
    supplier = _supplier(fake)
    mama = next(o for o in await supplier.search(PRAGUE) if o.supplier_data["hotel_id"] == "lp4")
    hold = await supplier.hold(_ref(mama), SIX)
    assert hold is not None

    bought = await supplier.purchase(_ref(mama), SIX, price_minor=232596, hold_ref=hold.ref)

    assert bought == Ok("BK-pb1")
    method, path, body = fake.requests[-1]
    assert (method, path) == ("POST", "/rates/book")
    assert [g["firstName"] for g in body["guests"]] == ["Anna", "Marta", "Zosia"]
    assert body["payment"] == {"method": "ACC_CREDIT_CARD"}
    assert not any("Kowalska" in note for note in supplier.log.notes)


async def test_purchase_without_a_hold_prebooks_then_books_at_the_approval() -> None:
    # HOLDS=off (the default): nothing was prebooked at voting close.
    fake = FakeLiteApi(prebookable={"o4": 2325.96})
    supplier = _supplier(fake)
    mama = next(o for o in await supplier.search(PRAGUE) if o.supplier_data["hotel_id"] == "lp4")
    calls = len(fake.requests)

    bought = await supplier.purchase(_ref(mama), SIX, price_minor=232596, hold_ref=None)

    assert bought == Ok("BK-pb1")
    steps = [(path, body) for _, path, body in fake.requests[calls:] if path.startswith("/rates")]
    assert [path for path, _ in steps] == ["/rates/prebook", "/rates/book"]
    assert steps[0][1]["offerId"] == "o4"
    assert steps[1][1]["prebookId"] == "pb1"
    assert any("placed at the approval" in note for note in supplier.log.notes)


async def test_purchase_without_a_hold_refuses_a_moved_price() -> None:
    fake = FakeLiteApi(prebookable={"o4": 2400.00})
    supplier = _supplier(fake)
    mama = next(o for o in await supplier.search(PRAGUE) if o.supplier_data["hotel_id"] == "lp4")

    moved = await supplier.purchase(_ref(mama), SIX, price_minor=232596, hold_ref=None)

    assert isinstance(moved, Err) and "instead of 2 325.96 PLN" in moved.error
    assert not any(path == "/rates/book" for _, path, _ in fake.requests)


async def test_an_expired_prebook_is_replaced_only_at_the_same_price() -> None:
    expired = {"code": 4002, "description": "invalid prebookId, rate not found"}
    fake = FakeLiteApi(prebookable={"o4": 2325.96}, book_status=400, book_error=expired)
    supplier = _supplier(fake)
    mama = next(o for o in await supplier.search(PRAGUE) if o.supplier_data["hotel_id"] == "lp4")

    fake.prebookable = {"o4": 2400.00}
    moved = await supplier.purchase(_ref(mama), SIX, price_minor=232596, hold_ref="old")
    assert isinstance(moved, Err) and "2 400.00 PLN instead of 2 325.96 PLN" in moved.error

    fake.prebookable = {"o4": 2325.96}
    fake.book_error = None
    calls = len(fake.requests)
    original = fake.handler

    def expire_first(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rates/book") and b'"old"' in request.content:
            return httpx.Response(400, json={"error": expired})
        return original(request)

    supplier.client.transport = httpx.MockTransport(expire_first)
    same = await supplier.purchase(_ref(mama), SIX, price_minor=232596, hold_ref="old")
    assert isinstance(same, Ok) and same.value.startswith("BK-pb")
    assert len(fake.requests) > calls


async def test_a_refused_booking_is_an_err_without_names() -> None:
    error = {"code": 4000, "description": "guest Anna Kowalska rejected"}
    fake = FakeLiteApi(book_status=400, book_error=error)
    bought = await _supplier(fake).purchase(
        OfferRef("liteapi", "x", {}), SIX, price_minor=1, hold_ref="pb1"
    )
    assert isinstance(bought, Err)
    assert "Kowalska" not in bought.error and "code 4000" in bought.error


async def test_purchase_needs_full_names() -> None:
    bought = await _supplier(FakeLiteApi()).purchase(
        OfferRef("liteapi", "x", {}), [TravellerDetails("Cher")], price_minor=1, hold_ref="pb"
    )
    assert isinstance(bought, Err) and "first and a last name" in bought.error


async def test_status_reports_a_cancelled_stay() -> None:
    fake = FakeLiteApi()
    supplier = _supplier(fake)
    booking = BookingRef(
        OfferRef("liteapi", "x", {"hotel_name": "Mama Shelter Prague"}), "BK-1", party_size=6
    )
    assert await supplier.status(booking) is None
    fake.booking_state = "CANCELLED"
    notice = await supplier.status(booking)
    assert notice is not None and notice.kind is DisruptionKind.CANCELLATION
    assert "Mama Shelter Prague" in notice.message and notice.replacement is None
    assert ("GET", "/bookings/BK-1", None) in fake.requests
    unbooked = BookingRef(OfferRef("liteapi", "x", {}), None, party_size=6)
    assert await supplier.status(unbooked) is None


def test_the_call_log_carries_no_booking_ids() -> None:
    fake = FakeLiteApi()
    client = LiteApiClient(SANDBOX_KEY, transport=httpx.MockTransport(fake.handler))

    import asyncio

    asyncio.run(client.booking("SECRET123"))
    assert client.calls[0].path == "/bookings/{id}"


# ---- the real sandbox (opt-in) ----------------------------------------------------------------


@pytest.mark.skipif(os.environ.get("LITEAPI_LIVE") != "1", reason="set LITEAPI_LIVE=1")
async def test_live_sandbox_search_and_quote() -> None:
    key = os.environ.get("LITEAPI_KEY", "").strip().strip('"')
    if not key.startswith("sand_"):
        pytest.skip("LITEAPI_KEY must be a sandbox key")
    config = LiteApiConfig(api_key=SecretStr(key))
    supplier = LiteApiSupplier(
        LiteApiClient(config.api_key), config, lambda: datetime.now(UTC), verify_availability=False
    )
    later = date.today() + timedelta(days=60)
    request = SearchRequest("Warszawa", "Prague", later, later + timedelta(days=2), 4)
    offers = await supplier.search(request)
    assert offers and all(o.price_minor > 0 and o.currency == "PLN" for o in offers)
    quote = await supplier.quote(_ref(offers[0]), 4)
    assert quote is None or quote.price_minor > 0
