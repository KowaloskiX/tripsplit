"""The city catalogue: every form people type resolves to one city."""

import pytest

from app.ai.places import destination_of, origin_of
from app.core.domain.places import (
    all_cities,
    cities_in,
    city_by_code,
    city_named,
    fold,
    polish_forms,
    resolve_city,
)
from app.suppliers.airports import AIRPORTS, airport_code
from app.suppliers.liteapi import find_city
from app.suppliers.pkp import station_query


@pytest.mark.parametrize(
    ("text", "city"),
    [
        ("Sztokholm", "Stockholm"),
        ("Sztokholmu", "Stockholm"),
        ("sztokholmie", "Stockholm"),
        ("Stockholm", "Stockholm"),
        ("Poznań", "Poznan"),
        ("Poznania", "Poznan"),
        ("poznaniu", "Poznan"),
        ("Wiedeń", "Vienna"),
        ("Wiednia", "Vienna"),
        ("WIEDEŃ", "Vienna"),
        ("Wien", "Vienna"),
        ("Praga", "Prague"),
        ("Pragi", "Prague"),
        ("w Pradze", "Prague"),
        ("Praha", "Prague"),
        ("Rzym", "Rome"),
        ("Rzymu", "Rome"),
        ("Roma", "Rome"),
        ("Londyn", "London"),
        ("Londynu", "London"),
        ("Mediolan", "Milan"),
        ("Mediolanu", "Milan"),
        ("Milano", "Milan"),
        ("Krakowa", "Krakow"),
        ("Kraków", "Krakow"),
        ("krakow", "Krakow"),
        ("Gdańsku", "Gdansk"),
        ("Łodzi", "Lodz"),
        ("Warszawy", "Warsaw"),
        ("Warsaw", "Warsaw"),
        ("Kopenhadze", "Copenhagen"),
        ("Barcelonie", "Barcelona"),
        ("Brukseli", "Brussels"),
        ("Walencji", "Valencia"),
        ("Lizbony", "Lisbon"),
        ("Budapesztu", "Budapest"),
        ("Budapeszcie", "Budapest"),
        ("Paryża", "Paris"),
        ("Madrycie", "Madrid"),
        ("Monachium", "Munich"),
        ("München", "Munich"),
        ("Zurychu", "Zurich"),
        ("Bratysławie", "Bratislava"),
        ("Rydze", "Riga"),
        ("Wilna", "Vilnius"),
        ("Stambułu", "Istanbul"),
        ("Ateny", "Athens"),
        ("Aten", "Athens"),
        ("Zielonej Góry", "Zielona Gora"),
        ("Bielsko-Białej", "Bielsko-Biala"),
        ("Frankfurt (Oder)", "Frankfurt (Oder)"),
        ("Frankfurtu nad Odrą", "Frankfurt (Oder)"),
        ("Frankfurt", "Frankfurt"),
        ("Warszawa Centralna", "Warsaw"),
        ("Praga Gł./Praha hl.n.", "Prague"),
        ("bcn", "Barcelona"),
        ("ARN", "Stockholm"),
        ("Split", "Split"),
    ],
)
def test_resolve_city(text: str, city: str) -> None:
    found = resolve_city(text)
    assert found is not None
    assert found.name == city


@pytest.mark.parametrize("text", ["", "   ", "Atlantis", "somewhere warm", "split the bill"])
def test_unknown_places_resolve_to_nothing(text: str) -> None:
    assert resolve_city(text) is None


def test_the_catalogue_is_complete_and_consistent() -> None:
    cities = all_cities()
    assert len(cities) >= 150
    assert len({city.name for city in cities}) == len(cities)
    for city in cities:
        assert len(city.country_code) == 2
        assert -90 <= city.latitude <= 90
        assert -180 <= city.longitude <= 180
        assert not city.iata or len(city.iata) == 3
        # Every name of a city resolves to that city, whatever the case and diacritics.
        for name in (city.name, city.name_pl, city.local_name, city.name_pl.upper()):
            assert resolve_city(name) == city, name
    eu_capitals = {"Warsaw", "Berlin", "Paris", "Madrid", "Rome", "Vienna", "Prague", "Lisbon"}
    assert eu_capitals <= {city.name for city in cities}


def test_fold_and_polish_forms() -> None:
    assert fold("Łódź") == "lodz"
    assert fold("İstanbul") == "istanbul"
    assert {"pragi", "pradze", "prage"} <= polish_forms("Praga")
    assert {"poznania", "poznaniu"} <= polish_forms("Poznań")
    assert {"sztokholmu", "sztokholmie"} <= polish_forms("Sztokholm")
    assert {"madrytu", "madrycie"} <= polish_forms("Madryt")
    assert polish_forms("Zielona Góra") == frozenset()


def test_cities_in_reads_the_word_before() -> None:
    mentions = cities_in("Jedziemy z Poznania do Sztokholmu, potem Warszawa-Praga")
    assert [(m.city.name, m.before) for m in mentions] == [
        ("Poznan", "z"),
        ("Stockholm", "do"),
        ("Warsaw", "potem"),
        ("Prague", "warszawa"),
    ]


def test_everyday_words_are_not_cities_unless_capitalised() -> None:
    assert cities_in("nice hotel, split the costs, wspólna pula, palma na plaży") == []
    assert [m.city.name for m in cities_in("Weekend in Split")] == ["Split"]


def test_destination_and_origin_from_a_brief() -> None:
    brief = "z Poznania do Sztokholmu w 4 osoby"
    assert destination_of("", brief) == "Stockholm"
    assert origin_of("", brief) == "Poznan"
    assert destination_of("", "mieszkamy w Poznaniu, lecimy do Rzymu", "Poznań") == "Rome"
    assert destination_of("", "Poznań - Stockholm weekend", "Poznań") == "Stockholm"
    assert destination_of("Sztokholmu", "anything") == "Stockholm"
    assert destination_of("Atlantis", "anything") == "Atlantis"
    assert origin_of("Warszawa", "z Poznania") == "Warszawa"


def test_suppliers_read_the_catalogue() -> None:
    assert airport_code("Sztokholmu") == "STO"
    assert airport_code("z Poznania") == "POZ"
    assert airport_code("Zakopane") == "KRK"
    assert airport_code("Kijów") is None
    assert AIRPORTS["stockholm"] == ("STO", ("ARN", "BMA", "NYO"))
    covered = {airport: code for code, airports in AIRPORTS.values() for airport in airports}
    assert covered["BGY"] == "MIL"
    stockholm = find_city("Sztokholm")
    assert stockholm is not None
    assert (stockholm.country_code, stockholm.name) == ("SE", "Stockholm")
    assert station_query("Poznania") == "Poznań Główny"
    assert station_query("Warszawa Wschodnia") == "Warszawa Wschodnia"
    assert station_query("Warsaw") == "Warszawa Centralna"
    assert city_named("Warszawa Wschodnia") is None
    stockholm_city = city_by_code("arn")
    assert stockholm_city is not None
    assert stockholm_city.name == "Stockholm"
