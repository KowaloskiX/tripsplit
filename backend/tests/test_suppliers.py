"""The supplier port: capabilities and the rules derived from them, the simulators, the PKP
adapter on recorded answers, the registry — no database, no network."""

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qsl

import pytest

from app.ai.places import destination_of, travel_modes
from app.core.domain.result import Err, Ok
from app.core.domain.suppliers import (
    NAME_ONLY,
    SupplierCapabilities,
    TravellerField,
    hold_is_live,
    missing_traveller_fields,
    price_is_guaranteed,
    purchase_sizes,
    quote_is_fresh,
)
from app.core.domain.travellers import TravellerDetails, describe_missing, masked_document_number
from app.core.domain.trips import BookingKind, SupplierChannel, TransportMode, TravelPreferences
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import BookingRef, DisruptionKind, OfferRef, SearchRequest
from app.suppliers.providers import build_registry
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SimBehaviour, SimDisruption, sim_supplier
from tests.test_intercity_client import RecordedTransport

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
PASSPORT = TravellerDetails(
    full_name="Anna Kowalska",
    date_of_birth=date(1990, 5, 1),
    nationality="PL",
    document_number="EH1234567",
    document_expiry=date(2031, 1, 1),
)
BARCELONA = SearchRequest(
    origin="Warszawa",
    destination="Barcelona",
    depart_date=date(2026, 11, 20),
    return_date=date(2026, 11, 23),
    party_size=6,
)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


# ---- capabilities ---------------------------------------------------------------------------


def _rail(cap: int | None = 5) -> SupplierCapabilities:
    return SupplierCapabilities(
        kind=BookingKind.TRANSPORT,
        mode=TransportMode.RAIL,
        channel=SupplierChannel.AGENT,
        max_party_per_purchase=cap,
    )


@pytest.mark.parametrize(
    ("travellers", "cap", "expected"),
    [(6, 5, [3, 3]), (8, 5, [4, 4]), (8, 9, [8]), (11, 5, [4, 4, 3]), (12, None, [12])],
)
def test_purchase_sizes_come_from_the_cap(
    travellers: int, cap: int | None, expected: list[int]
) -> None:
    assert purchase_sizes(travellers, _rail(cap)) == expected


@pytest.mark.parametrize(
    "broken",
    [
        {"mode": None},  # a transport without a mode
        {"kind": BookingKind.STAY},  # a stay with a mode
        {"max_party_per_purchase": 0},
        {"supports_hold": True},  # a hold without a TTL
        {"hold_ttl": timedelta(hours=1)},  # a TTL without holds
        {"quote_ttl": timedelta(0)},
    ],
)
def test_inconsistent_capabilities_are_rejected(broken: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "kind": BookingKind.TRANSPORT,
        "mode": TransportMode.FLIGHT,
        "channel": SupplierChannel.API,
        "max_party_per_purchase": 9,
        **broken,
    }
    with pytest.raises(ValueError):
        SupplierCapabilities(**fields)  # type: ignore[arg-type]  # deliberately ill-typed input


def test_missing_traveller_fields_name_only_who_lacks_what() -> None:
    required = frozenset({TravellerField.FULL_NAME, TravellerField.DOCUMENT_NUMBER})
    provided = {
        "anna": PASSPORT.provided_fields(),
        "kuba": TravellerDetails(full_name="Kuba Mazur").provided_fields(),
        "solo": TravellerDetails(full_name="Kuba").provided_fields(),
    }
    assert missing_traveller_fields(required, provided) == {
        "kuba": frozenset({TravellerField.DOCUMENT_NUMBER}),
        "solo": required,
    }
    assert missing_traveller_fields(NAME_ONLY, {"anna": PASSPORT.provided_fields()}) == {}


def test_holds_and_quotes_expire() -> None:
    assert hold_is_live(NOW + timedelta(seconds=1), NOW)
    assert not hold_is_live(NOW, NOW)
    assert not hold_is_live(None, NOW)
    assert quote_is_fresh(NOW - timedelta(minutes=30), timedelta(minutes=30), NOW)
    assert not quote_is_fresh(NOW - timedelta(minutes=31), timedelta(minutes=30), NOW)
    naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None)
    assert quote_is_fresh(naive, timedelta(minutes=30), NOW)  # Mongo's naive UTC
    caps = sim_supplier("sim_flight", Clock()).capabilities
    assert price_is_guaranteed(
        caps, hold_expires_at=NOW + timedelta(hours=1), quoted_at=None, now=NOW
    )
    assert not price_is_guaranteed(
        caps, hold_expires_at=NOW, quoted_at=NOW - timedelta(hours=2), now=NOW
    )


def test_document_numbers_never_print() -> None:
    assert masked_document_number("EH1234567") == "*******67"
    assert masked_document_number(None) is None
    assert "EH1234567" not in repr(PASSPORT)
    text = describe_missing({"Kuba Mazur": frozenset({TravellerField.DOCUMENT_NUMBER})})
    assert text == "Kuba Mazur (document number)"


# ---- the simulators -------------------------------------------------------------------------


async def test_sim_flights_are_deterministic_and_realistic() -> None:
    clock = Clock()
    first = await sim_supplier("sim_flight", clock).search(BARCELONA)
    again = await sim_supplier("sim_flight", clock).search(BARCELONA)
    assert first == again
    sellers = [offer.seller for offer in first]
    assert sellers == ["Ryanair", "Wizz Air", "LOT Polish Airlines"]
    ryanair = first[0]
    assert ryanair.segments[0].origin == "WMI" and ryanair.segments[0].destination == "BCN"
    assert [s.number.split()[0] for s in ryanair.segments] == ["FR", "FR"]
    per_person = ryanair.price_minor // 6
    assert 50_000 < per_person < 100_000  # a realistic Ryanair return to Barcelona in PLN
    assert first[2].price_minor > 2 * ryanair.price_minor  # LOT is the splurge


async def test_no_rail_to_barcelona_and_buses_to_budapest() -> None:
    clock = Clock()
    assert await sim_supplier("sim_rail", clock).search(BARCELONA) == []
    budapest = SearchRequest("Kraków", "Budapest", date(2026, 11, 20), None, 8)
    (flixbus, regiojet) = await sim_supplier("sim_bus", clock).search(budapest)
    assert flixbus.title.startswith("FlixBus N ")
    assert flixbus.segments[0].origin == "MDA"
    assert flixbus.price_minor < regiojet.price_minor


async def test_sim_quote_hold_purchase_and_expiry() -> None:
    clock = Clock()
    behaviour = SimBehaviour()
    flight = sim_supplier("sim_flight", clock, behaviour)
    offer = (await flight.search(BARCELONA))[0]
    ref = OfferRef(offer.supplier_id, offer.offer_ref, offer.supplier_data)
    quote = await flight.quote(ref, 6)
    assert quote is not None and quote.price_minor == offer.price_minor

    behaviour.price_change_percent = 8
    hold = await flight.hold(ref, [PASSPORT] * 6)
    assert hold is not None
    assert hold.price_minor == round(offer.price_minor * 1.08)
    assert hold.expires_at == NOW + timedelta(hours=24)
    again = await flight.quote(ref, 6)
    assert again is not None and again.price_minor == offer.price_minor  # one-shot

    bought = await flight.purchase(
        ref, [PASSPORT] * 6, price_minor=hold.price_minor, hold_ref=hold.ref
    )
    assert isinstance(bought, Ok) and bought.value.startswith("SIMFLIGHT-")
    clock.now += timedelta(hours=25)
    late = await flight.purchase(
        ref, [PASSPORT] * 6, price_minor=hold.price_minor, hold_ref=hold.ref
    )
    assert late == Err("the hold has expired")
    no_passport = await flight.purchase(
        ref, [TravellerDetails("Anna Kowalska")], price_minor=offer.price_minor, hold_ref=None
    )
    assert no_passport == Err("traveller details are incomplete")
    behaviour.sold_out = True
    assert await flight.quote(ref, 6) is None
    assert await flight.hold(ref, [PASSPORT]) is None


async def test_a_cancelled_flight_comes_with_another_carrier() -> None:
    behaviour = SimBehaviour(disruption=SimDisruption(replacement_price_percent=12))
    flight = sim_supplier("sim_flight", Clock(), behaviour)
    offer = (await flight.search(BARCELONA))[0]
    booking = BookingRef(OfferRef(offer.supplier_id, offer.offer_ref, offer.supplier_data), "X", 6)
    notice = await flight.status(booking)
    assert notice is not None and notice.kind is DisruptionKind.CANCELLATION
    assert notice.replacement is not None
    assert notice.replacement.seller == "Wizz Air"
    assert notice.replacement.price_minor == round(offer.price_minor * 1.12 / 6) * 6
    assert await flight.status(booking) is None  # reported once


async def test_agent_channel_sims_cannot_be_bought_through_an_api() -> None:
    rail = sim_supplier("sim_rail", Clock())
    ref = OfferRef("sim_rail", "x", {"price_per_person_minor": 100})
    assert isinstance(await rail.purchase(ref, [], price_minor=0, hold_ref=None), Err)
    assert await rail.hold(ref, []) is None


async def test_a_demo_rail_return_is_one_order_for_both_legs() -> None:
    """Regression: the site sold one leg per order, so a "return" offer was bought one way."""
    demo = build_registry(["demo_rail"], "http://localhost:8000").get("demo_rail")
    assert demo is not None
    request = SearchRequest("Warszawa", "Praha", date(2026, 11, 30), date(2026, 12, 3), 3)
    offer = (await demo.search(request))[0]
    assert offer.title == "EC 111 Praha · Warszawa → Praha · return"
    assert offer.price_minor == 18_900 * 2 * 3
    assert dict(parse_qsl(offer.purchase_url.split("?")[1])) == {
        "from": "Warszawa",
        "to": "Praha",
        "date": "2026-11-30",
        "return": "2026-12-03",
        "passengers": "3",  # the party is preselected: the agent buys for all of them
    }


# ---- PKP Intercity adapter, registry, brief reading ------------------------------------------


async def test_the_pkp_adapter_searches_whole_party_offers() -> None:
    transport = RecordedTransport()
    pkp = PkpIntercitySupplier(transport)
    request = SearchRequest("Warszawa", "Prague", date(2026, 11, 20), None, 6)
    (offer,) = await pkp.search(request)  # the recording only has 2nd class
    assert offer.price_minor == 15_565 * 6
    assert offer.seller == "PKP Intercity"
    assert "Sold as 3+3" in offer.details
    assert offer.purchase_url.startswith("https://ebilet.intercity.pl/")
    assert offer.supplier_data["legs"][0]["train_number"] == 131
    assert transport.fare_requests == [3]  # 3 + 3 is priced by one request
    assert (
        await pkp.search(
            SearchRequest(
                "Warszawa", "Prague", date(2026, 11, 20), None, 6, mode=TransportMode.FLIGHT
            )
        )
        == []
    )


def test_the_registry_looks_suppliers_up_by_id_and_capability() -> None:
    registry = build_registry(["sim_rail", "sim_flight", "sim_stay", "nope", "demo_rail"], None)
    assert registry.ids == ["sim_rail", "sim_flight", "sim_stay"]  # unknown and demo skipped
    assert [a.id for a in registry.of_kind(BookingKind.TRANSPORT)] == ["sim_rail", "sim_flight"]
    assert [a.id for a in registry.of_kind(BookingKind.TRANSPORT, TransportMode.FLIGHT)] == [
        "sim_flight"
    ]
    assert build_registry(["demo_rail"], "http://localhost:8000").ids == ["demo_rail"]
    with pytest.raises(ValueError):
        SupplierRegistry([sim_supplier("sim_rail", Clock()), sim_supplier("sim_rail", Clock())])


@pytest.mark.parametrize(
    ("preferred", "text", "expected"),
    [
        (None, "cheap, good food", (None, None)),
        (None, "Prague: fly there, train back", (TransportMode.FLIGHT, TransportMode.RAIL)),
        (None, "by coach please", (TransportMode.BUS, TransportMode.BUS)),
        (TransportMode.RAIL, "fly there, bus back", (TransportMode.RAIL, TransportMode.RAIL)),
        (None, "business trip", (None, None)),
    ],
)
def test_travel_modes_read_from_the_brief(
    preferred: TransportMode | None,
    text: str,
    expected: tuple[TransportMode | None, TransportMode | None],
) -> None:
    assert travel_modes(preferred, text) == expected


def test_destination_of() -> None:
    assert destination_of("Lisbon", "Weekend in Prague") == "Lisbon"
    assert destination_of("", "Long weekend in Barcelona") == "Barcelona"
    assert destination_of("", "somewhere") == "Prague"


def test_travel_preferences_limit_departure_hour_and_transfers() -> None:
    anything = TravelPreferences()
    assert anything.accepts(5, 3)
    picky = TravelPreferences(earliest_departure_hour=8, max_transfers=0)
    assert picky.accepts(8, 0)
    assert not picky.accepts(7, 0)
    assert not picky.accepts(9, 1)


async def test_pkp_honours_the_groups_preferences() -> None:
    """The recorded connection leaves at 07:52 and is direct."""
    pkp = PkpIntercitySupplier(RecordedTransport())

    def asking(preferences: TravelPreferences) -> SearchRequest:
        return SearchRequest(
            "Warszawa", "Prague", date(2026, 11, 20), None, 6, preferences=preferences
        )

    assert len(await pkp.search(asking(TravelPreferences(earliest_departure_hour=7)))) == 1
    assert len(await pkp.search(asking(TravelPreferences(max_transfers=0)))) == 1
    assert await pkp.search(asking(TravelPreferences(earliest_departure_hour=8))) == []


async def test_in_a_demo_pkp_trains_are_bought_on_the_fake_rail_site() -> None:
    """Prices from PKP, purchase on our own site: a demo never drives intercity.pl."""
    registry = build_registry(["pkp_intercity"], "http://localhost:8000", pkp=RecordedTransport())
    pkp = registry.get("pkp_intercity")
    assert pkp is not None
    request = SearchRequest("Warszawa", "Prague", date(2026, 11, 20), None, 6)
    (offer,) = await pkp.search(request)
    site, query = offer.purchase_url.split("?")
    assert site == "http://localhost:8000/api/demo-supplier/rail"
    # The site prices the journey at PKP's real per-person fare; the dates are filled in.
    assert dict(parse_qsl(query)) == {
        "from": offer.segments[0].origin,
        "to": offer.segments[0].destination,
        "date": "2026-11-20",
        "fare": "15565",
    }
