"""The `duffel` flights supplier on recorded Duffel test-mode answers — no network.

The fixtures under `tests/fixtures/duffel/` are trimmed responses of the real test API (fake
travellers, test mode). `FakeDuffel` plays the API behind an `httpx.MockTransport` and records
every request, so request shapes are asserted as well as the parsing. The one live smoke test
runs only with `DUFFEL_LIVE=1` and a test key.
"""

import copy
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from pydantic import SecretStr

from app.core.config import Settings
from app.core.domain.result import Err, Ok
from app.core.domain.suppliers import TravellerField
from app.core.domain.travellers import Gender, TravellerDetails
from app.core.domain.trips import TransportMode
from app.suppliers.airports import airport_code
from app.suppliers.duffel import (
    CAPABILITIES,
    DuffelConfig,
    DuffelSupplier,
    ascii_name,
    notice_of,
    parse_offer,
    select_offers,
    to_pln_minor,
)
from app.suppliers.duffel_client import DuffelClient, check_key
from app.suppliers.ports import (
    BookingRef,
    DisruptionKind,
    OfferRef,
    SearchRequest,
    SupplierUnavailableError,
)
from app.suppliers.providers import build_registry, duffel_config, duffel_supplier
from tests.duffel_fake import FakeDuffel, error, fixture

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
# Not a credential: the prefix is all the guard looks at.
TEST_KEY = SecretStr("duffel_test_" + "x" * 20)
LIVE_KEY = "duffel_live_" + "y" * 20
NOW = datetime(2026, 10, 31, 3, 50, tzinfo=UTC)  # the fixture offers expire at 04:16
BARCELONA = SearchRequest(
    origin="Warszawa",
    destination="Barcelona",
    depart_date=date(2026, 11, 20),
    return_date=date(2026, 11, 23),
    party_size=6,
)
BA = "off_034pFsnX9PX88kQbdGhcky"
ZZ = "off_034pFsnWxK6eUZCnKFM1nU"


def traveller(index: int, *, gender: Gender | None = Gender.FEMALE) -> TravellerDetails:
    return TravellerDetails(
        full_name=[
            "Łucja Żółć",
            "Kuba Mazur",
            "Marta Lis",
            "Piotr Nowak",
            "Zosia Wrona",
            "Tomek Dudek",
        ][index],
        date_of_birth=date(1990, 1, 1 + index),
        nationality="PL",
        document_number=f"AB12345{index}7",
        document_expiry=date(2031, 6, 30),
        gender=gender,
    )


SIX = [traveller(i, gender=Gender.FEMALE if i % 2 == 0 else Gender.MALE) for i in range(6)]


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def api() -> FakeDuffel:
    return FakeDuffel()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def duffel(api: FakeDuffel, clock: Clock) -> DuffelSupplier:
    client = DuffelClient(TEST_KEY, transport=httpx.MockTransport(api.handle), backoff_s=0)
    return DuffelSupplier(client, DuffelConfig(api_key=TEST_KEY), clock=clock)


async def _searched(duffel: DuffelSupplier, offer_id: str = BA) -> OfferRef:
    offers = await duffel.search(BARCELONA)
    chosen = next(offer for offer in offers if offer.offer_ref == offer_id)
    return OfferRef(chosen.supplier_id, chosen.offer_ref, chosen.supplier_data)


# ---- the key guard and configuration ------------------------------------------------------


def test_only_test_keys_are_used_unless_live_is_explicitly_allowed() -> None:
    assert isinstance(check_key(TEST_KEY.get_secret_value(), allow_live=False), Ok)
    refused = check_key(LIVE_KEY, allow_live=False)
    assert isinstance(refused, Err)
    assert "DUFFEL_ALLOW_LIVE" in refused.error
    assert LIVE_KEY not in refused.error
    assert isinstance(check_key(LIVE_KEY, allow_live=True), Ok)
    assert isinstance(check_key("sk_live_whatever", allow_live=True), Err)


def test_the_client_refuses_a_live_key_without_naming_it() -> None:
    with pytest.raises(ValueError) as refused:
        DuffelClient(SecretStr(LIVE_KEY))
    assert LIVE_KEY not in str(refused.value)


def test_duffel_is_configured_only_with_a_usable_key() -> None:
    assert duffel_config(Settings(duffel_api_key=None)) is None
    assert duffel_config(Settings(duffel_api_key=SecretStr("  "))) is None
    assert duffel_config(Settings(duffel_api_key=SecretStr(LIVE_KEY))) is None
    config = duffel_config(Settings(duffel_api_key=TEST_KEY, duffel_fx_eur_pln=4.25))
    assert config is not None
    assert config.rates_to_pln()["EUR"] == Decimal("4.25")
    assert build_registry(["duffel", "sim_stay"], None, config).ids == ["duffel", "sim_stay"]
    assert build_registry(["duffel", "sim_stay"], None, None).ids == ["sim_stay"]
    assert duffel_supplier(config).display_name == "Duffel (airline API, test mode)"


def test_capabilities_say_what_an_airline_order_needs() -> None:
    assert CAPABILITIES.mode is TransportMode.FLIGHT
    assert CAPABILITIES.max_party_per_purchase == 9
    assert CAPABILITIES.supports_hold and CAPABILITIES.hold_needs_traveller_details
    assert CAPABILITIES.reports_disruptions
    assert TravellerField.GENDER in CAPABILITIES.required_traveller_fields
    assert TravellerField.DATE_OF_BIRTH in CAPABILITIES.required_traveller_fields


# ---- parsing, money, selection --------------------------------------------------------------


def test_an_offer_is_parsed_with_local_times_and_payment_terms() -> None:
    raw = fixture("offer_request_waw_bcn")["data"]["offers"][0]
    offer = parse_offer(raw)
    assert offer is not None
    assert offer.owner == "British Airways"
    assert offer.total_amount == Decimal("938.46") and offer.currency == "EUR"
    first = offer.slices[0][0]
    assert first.number == "BA 0107" and (first.origin, first.destination) == ("WAW", "BCN")
    assert first.departs_at.utcoffset() == timedelta(hours=1)  # Warsaw in November
    assert offer.direct and not offer.requires_instant_payment
    assert offer.hold_until == datetime(2026, 11, 2, 3, 46, 20, tzinfo=UTC)  # the guarantee
    assert len(offer.passenger_ids) == 6
    assert offer.itinerary[0] == "BA 0107@2026-11-20T14:42:00+01:00"


def test_a_malformed_offer_is_skipped() -> None:
    assert parse_offer({"id": "off_1", "total_amount": "abc"}) is None
    assert parse_offer({"id": "off_1", "total_amount": "10.00", "slices": []}) is None
    assert parse_offer("nonsense") is None


def test_eur_is_converted_to_grosze_with_the_configured_rate() -> None:
    rates = {"EUR": Decimal("4.30"), "PLN": Decimal(1)}
    assert to_pln_minor(Decimal("956.82"), "EUR", rates) == 411_433  # 4114.326 -> 4114.33
    assert to_pln_minor(Decimal("10.00"), "pln", rates) == 1_000
    assert to_pln_minor(Decimal("10.00"), "USD", rates) is None


def test_selection_keeps_the_cheapest_the_fastest_and_a_direct_flight_once_each() -> None:
    raw = fixture("offer_request_waw_bcn")["data"]["offers"]
    offers = [offer for offer in map(parse_offer, raw) if offer is not None]
    chosen = select_offers(offers, 5)
    assert len(chosen) == 5
    assert chosen[0].total_amount == min(offer.total_amount for offer in offers)
    assert len({offer.itinerary for offer in chosen}) == len({o.id for o in chosen})
    assert [o.total_amount for o in chosen] == sorted(o.total_amount for o in chosen)
    fastest = min(offers, key=lambda offer: offer.duration)
    assert any(offer.duration == fastest.duration for offer in chosen)
    assert select_offers([], 5) == []


def test_names_go_to_the_airline_in_ascii() -> None:
    assert ascii_name("Łucja Żółć-Ąę") == "Lucja Zolc-Ae"


def test_cities_map_to_airport_codes() -> None:
    assert airport_code("Warszawa") == "WAW"
    assert airport_code("warsaw") == "WAW"
    assert airport_code("Kraków") == "KRK"
    assert airport_code("Paris") == "PAR"
    assert airport_code("bcn") == "BCN"
    assert airport_code("Warszawa Centralna") == "WAW"
    assert airport_code("Atlantis City") is None


# ---- search -----------------------------------------------------------------------------------


async def test_search_returns_holdable_offers_for_the_whole_party_in_pln(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offers = await duffel.search(BARCELONA)

    body = api.bodies("POST", "/air/offer_requests")[0]
    assert body["slices"] == [
        {"origin": "WAW", "destination": "BCN", "departure_date": "2026-11-20"},
        {"origin": "BCN", "destination": "WAW", "departure_date": "2026-11-23"},
    ]
    assert body["passengers"] == [{"type": "adult"}] * 6
    assert body["cabin_class"] == "economy"
    request = api.requests[0]
    assert request.url.params["return_offers"] == "true"
    assert request.headers["Duffel-Version"] == "v2"
    assert request.headers["Authorization"] == f"Bearer {TEST_KEY.get_secret_value()}"

    assert 1 <= len(offers) <= 5
    assert "off_handmade_instant_only" not in {offer.offer_ref for offer in offers}
    ba = next(offer for offer in offers if offer.offer_ref == BA)
    assert ba.price_minor == 403_538  # 938.46 EUR x 4.30
    assert ba.currency == "PLN" and ba.seller == "British Airways"
    assert ba.title == "British Airways BA 0107 / BA 0107 WAW -> BCN (return)"
    assert "938.46 EUR" in ba.details and "4.30 PLN/EUR" in ba.details
    assert ba.segments[0].number == "BA 0107" and len(ba.segments) == 2
    assert ba.refundable
    data = ba.supplier_data
    assert data["original_amount"] == "938.46" and data["currency"] == "EUR"
    assert data["party_size"] == 6 and len(data["passenger_ids"]) == 6
    assert data["offer_request_id"] == "orq_0000BBxVQpWGTnV473ECQw"
    assert data["slices"] == body["slices"]


async def test_a_party_above_nine_is_priced_from_a_search_for_nine(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offers = await duffel.search(
        SearchRequest("Warszawa", "Barcelona", date(2026, 11, 20), date(2026, 11, 23), 12)
    )
    assert len(api.bodies("POST", "/air/offer_requests")[0]["passengers"]) == 9
    ba = next(offer for offer in offers if offer.offer_ref == BA)
    assert ba.price_minor == round(403_538 * 12 / 9)


async def test_search_skips_other_modes_and_unknown_cities(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    rail = SearchRequest("Warszawa", "Praha", date(2026, 11, 20), None, 2, mode=TransportMode.RAIL)
    assert await duffel.search(rail) == []
    assert (
        await duffel.search(SearchRequest("Atlantis", "Barcelona", date(2026, 11, 20), None, 2))
        == []
    )
    assert api.requests == []


async def test_an_outage_is_no_offers_after_retries(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    api.override = lambda request: httpx.Response(503)
    assert await duffel.search(BARCELONA) == []
    assert api.calls("POST", "/air/offer_requests") == 3  # a search is retried
    assert any("failed" in note for note in duffel.log.notes)


# ---- quote ----------------------------------------------------------------------------------


async def test_a_live_offer_is_quoted_by_reading_it(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offer = await _searched(duffel)
    quote = await duffel.quote(offer, 6)
    assert quote is not None and quote.price_minor == 403_538 and quote.currency == "PLN"
    assert api.calls("GET", f"/air/offers/{BA}") == 1
    assert api.calls("POST", "/air/offer_requests") == 1


async def test_an_expired_offer_is_found_again_by_its_flights(
    duffel: DuffelSupplier, api: FakeDuffel, clock: Clock
) -> None:
    offer = await _searched(duffel)
    clock.now += timedelta(hours=1)  # past the offer's expiry
    renewed = copy.deepcopy(api.offer_request)
    for raw in renewed["data"]["offers"]:
        raw["id"] = raw["id"] + "_new"
        if raw["id"] == BA + "_new":
            raw["total_amount"] = "940.00"
    api.offer_request = renewed

    quote = await duffel.quote(offer, 6)

    assert quote is not None and quote.price_minor == 404_200  # the same flights, new price
    assert api.calls("POST", "/air/offer_requests") == 2
    assert api.calls("GET", f"/air/offers/{BA}_new") == 1
    assert any("re-found" in note for note in duffel.log.notes)


async def test_flights_that_are_gone_quote_none(
    duffel: DuffelSupplier, api: FakeDuffel, clock: Clock
) -> None:
    offer = await _searched(duffel)
    clock.now += timedelta(hours=1)
    api.offer_request = copy.deepcopy(api.offer_request)
    api.offer_request["data"]["offers"] = api.offer_request["data"]["offers"][3:]
    assert await duffel.quote(offer, 6) is None


async def test_another_party_size_searches_again(duffel: DuffelSupplier, api: FakeDuffel) -> None:
    offer = await _searched(duffel)
    await duffel.quote(offer, 4)
    assert len(api.bodies("POST", "/air/offer_requests")[-1]["passengers"]) == 4


# ---- hold -------------------------------------------------------------------------------------


async def test_a_hold_is_a_named_hold_order(duffel: DuffelSupplier, api: FakeDuffel) -> None:
    offer = await _searched(duffel)

    hold = await duffel.hold(offer, SIX)

    assert hold is not None
    assert hold.ref == "ord_0000BBxVAkPCkSLAMvZP0y"
    assert hold.expires_at == datetime(2026, 11, 2, 3, 42, 52, tzinfo=UTC)  # the guarantee
    assert hold.price_minor == 403_538  # the order's 938.46 EUR x 4.30
    body = api.bodies("POST", "/air/orders")[0]
    assert body["type"] == "hold" and body["selected_offers"] == [BA]
    assert "payments" not in body
    first, second = body["passengers"][0], body["passengers"][1]
    assert first["id"] == "pas_0000BBxVQpWcSTme89OTyy"
    assert (first["given_name"], first["family_name"]) == ("Lucja", "Zolc")
    assert (first["gender"], first["title"]) == ("f", "ms")
    assert (second["gender"], second["title"]) == ("m", "mr")
    assert first["born_on"] == "1990-01-01"
    assert first["email"] == "trips@tripsplit.example" and first["phone_number"].startswith("+")
    assert "identity_documents" not in first  # this route does not need passports


async def test_passports_go_only_when_the_offer_requires_them(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    for raw in api.offer_request["data"]["offers"]:
        raw["passenger_identity_documents_required"] = True
    offer = await _searched(duffel)
    await duffel.hold(offer, SIX)
    document = api.bodies("POST", "/air/orders")[0]["passengers"][0]["identity_documents"][0]
    assert document == {
        "type": "passport",
        "unique_identifier": "AB1234507",
        "issuing_country_code": "PL",
        "expires_on": "2031-06-30",
    }


async def test_a_reprice_at_the_order_is_read_and_the_hold_retried(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offer = await _searched(duffel)
    attempts = {"orders": 0}

    def price_changed_once(request: httpx.Request) -> httpx.Response | None:
        if request.method == "POST" and request.url.path == "/air/orders":
            attempts["orders"] += 1
            if attempts["orders"] == 1:
                return httpx.Response(422, json=error("price_changed", None, "x", 422))
        return None

    api.override = price_changed_once
    hold = await duffel.hold(offer, SIX)
    assert hold is not None
    assert attempts["orders"] == 2
    assert api.calls("GET", f"/air/offers/{BA}") == 2  # before the hold, and after the reprice


async def test_an_offer_gone_at_the_order_cannot_be_held(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offer = await _searched(duffel)
    api.override = lambda request: (
        httpx.Response(422, json=error("offer_no_longer_available", None, "gone", 422))
        if request.url.path == "/air/orders"
        else None
    )
    assert await duffel.hold(offer, SIX) is None


async def test_a_refused_hold_names_fields_never_values(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offer = await _searched(duffel)
    secret = "AB1234507"
    api.override = lambda request: (
        httpx.Response(
            422,
            json=error("validation_format", "unique_identifier", f"{secret} is bad", 422),
        )
        if request.url.path == "/air/orders"
        else None
    )
    with pytest.raises(SupplierUnavailableError) as refused:
        await duffel.hold(offer, SIX)
    assert "unique_identifier" in str(refused.value)
    assert secret not in str(refused.value)
    assert all(secret not in line for line in [*duffel.log.calls, *duffel.log.notes])


async def test_a_traveller_without_gender_is_not_sent(duffel: DuffelSupplier) -> None:
    offer = await _searched(duffel)
    travellers = [*SIX[:5], traveller(5, gender=None)]
    with pytest.raises(SupplierUnavailableError, match="gender"):
        await duffel.hold(offer, travellers)


# ---- purchase -------------------------------------------------------------------------------


async def test_approving_pays_the_held_order_in_duffels_currency(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offer = await _searched(duffel)
    bought = await duffel.purchase(
        offer, SIX, price_minor=192_391, hold_ref="ord_0000BBxVAkPCkSLAMvZP0y"
    )
    assert bought == Ok("JCLCEN")
    assert api.bodies("POST", "/air/payments") == [
        {
            "order_id": "ord_0000BBxVAkPCkSLAMvZP0y",
            "payment": {"type": "balance", "amount": "447.42", "currency": "EUR"},
        }
    ]
    # A retried approval does not pay twice.
    again = await duffel.purchase(
        offer, SIX, price_minor=192_391, hold_ref="ord_0000BBxVAkPCkSLAMvZP0y"
    )
    assert again == Ok("JCLCEN")
    assert len(api.bodies("POST", "/air/payments")) == 1


async def test_a_hold_past_its_guarantee_is_not_paid(
    duffel: DuffelSupplier, api: FakeDuffel, clock: Clock
) -> None:
    offer = await _searched(duffel)
    clock.now = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)
    bought = await duffel.purchase(offer, SIX, price_minor=192_391, hold_ref="ord_x")
    assert isinstance(bought, Err) and "guaranteed" in bought.error
    assert api.bodies("POST", "/air/payments") == []


async def test_a_refused_payment_is_anerror(duffel: DuffelSupplier, api: FakeDuffel) -> None:
    offer = await _searched(duffel)
    api.override = lambda request: (
        httpx.Response(422, json=error("insufficient_balance", None, "no money", 422))
        if request.url.path == "/air/payments"
        else None
    )
    bought = await duffel.purchase(offer, SIX, price_minor=192_391, hold_ref="ord_x")
    assert isinstance(bought, Err) and "insufficient_balance" in bought.error


async def test_a_payment_outage_is_not_retried(duffel: DuffelSupplier, api: FakeDuffel) -> None:
    offer = await _searched(duffel)
    api.override = lambda request: (
        httpx.Response(502) if request.url.path == "/air/payments" else None
    )
    bought = await duffel.purchase(offer, SIX, price_minor=192_391, hold_ref="ord_x")
    assert isinstance(bought, Err) and "check the order" in bought.error
    assert api.calls("POST", "/air/payments") == 1


async def test_without_a_hold_an_instant_order_is_paid_at_most_the_approved_price(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offer = await _searched(duffel)
    cheaper = await duffel.purchase(offer, SIX, price_minor=403_537, hold_ref=None)
    assert isinstance(cheaper, Err) and "more than the approved" in cheaper.error
    assert api.bodies("POST", "/air/orders") == []

    bought = await duffel.purchase(offer, SIX, price_minor=403_538, hold_ref=None)
    assert bought == Ok("JCLCEN")
    body = api.bodies("POST", "/air/orders")[0]
    assert body["type"] == "instant"
    assert body["payments"] == [{"type": "balance", "amount": "938.46", "currency": "EUR"}]


# ---- disruptions ----------------------------------------------------------------------------


async def test_an_airline_schedule_change_is_a_delay(
    duffel: DuffelSupplier, api: FakeDuffel
) -> None:
    offer = await _searched(duffel)
    notice = await duffel.status(
        BookingRef(offer=offer, confirmation_ref="JCLCEN", party_size=6, hold_ref="ord_1")
    )
    assert notice is not None
    assert notice.kind is DisruptionKind.DELAY and notice.delay_minutes == 60
    assert notice.replacement is None
    assert api.requests[-1].url.params["order_id"] == "ord_1"
    assert await duffel.status(BookingRef(offer=offer, confirmation_ref="X", party_size=6)) is None


async def test_handled_changes_are_not_reported(duffel: DuffelSupplier, api: FakeDuffel) -> None:
    changes = fixture("airline_initiated_changes")
    changes["data"][0]["action_taken"] = "accepted"
    api.override = lambda request: (
        httpx.Response(200, json=changes)
        if request.url.path == "/air/airline_initiated_changes"
        else None
    )
    offer = await _searched(duffel)
    booking = BookingRef(offer=offer, confirmation_ref="X", party_size=6, hold_ref="ord_1")
    assert await duffel.status(booking) is None


def test_a_change_without_new_flights_is_a_cancellation() -> None:
    change = fixture("airline_initiated_changes")["data"][0]
    change["added"] = []
    notice = notice_of(change, "ZZ 7426")
    assert notice.kind is DisruptionKind.CANCELLATION


# ---- the client -----------------------------------------------------------------------------


async def test_a_rate_limit_is_retried_even_for_a_payment() -> None:
    answers = iter([httpx.Response(429), httpx.Response(201, json={"data": {"id": "pay_1"}})])
    client = DuffelClient(
        TEST_KEY, transport=httpx.MockTransport(lambda request: next(answers)), backoff_s=0
    )
    assert await client.post("/air/payments", {}) == Ok({"id": "pay_1"})


async def test_a_network_error_on_a_purchase_call_is_unavailable_at_once() -> None:
    calls: list[httpx.Request] = []

    def broken(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("boom")

    client = DuffelClient(TEST_KEY, transport=httpx.MockTransport(broken), backoff_s=0)
    with pytest.raises(SupplierUnavailableError):
        await client.post("/air/orders", {})
    assert len(calls) == 1


# ---- live (opt-in) --------------------------------------------------------------------------


@pytest.mark.skipif(os.environ.get("DUFFEL_LIVE") != "1", reason="set DUFFEL_LIVE=1 to call Duffel")
async def test_live_search_warsaw_to_barcelona() -> None:
    # The suite ignores .env (tests/conftest.py); this opt-in test reads the key from it.
    key = os.environ.get("DUFFEL_API_KEY") or dotenv_values(ROOT_ENV).get("DUFFEL_API_KEY") or ""
    config = duffel_config(Settings(duffel_api_key=SecretStr(key)))
    assert config is not None, "DUFFEL_API_KEY must hold a duffel_test_ key"
    offers = await duffel_supplier(config).search(BARCELONA)
    assert offers
    assert all(offer.currency == "PLN" and offer.price_minor > 0 for offer in offers)
