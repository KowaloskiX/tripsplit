"""Which airport code a trip's city flies from, for the flight suppliers — read off the city
catalogue (`app.core.domain.places`), the one place that knows cities.

A city with several airports maps to its IATA **city** code (`LON`, `PAR`, `ROM`, `MIL`,
`STO`): the airline APIs search all of its airports at once. `WAW` is both Warsaw Chopin and the
city code (it includes Modlin, WMI). A city without an airport flies from the nearest one
(Zakopane -> KRK). Any form the catalogue resolves works — "Warszawa", "Warsaw", "Sztokholmu",
"z Poznania" — and a bare three-letter code passes through as is.
"""

import re

from app.core.domain.places import City, all_cities, city_forms, resolve_city

_IATA = re.compile(r"^[A-Za-z]{3}$")


def _airports() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Every catalogue form of a city we fly to -> (search code, the airports it covers),
    plus the plain case-folded names with their diacritics. Multi-airport cities come last,
    so a reverse airport -> city mapping prefers them (BGY -> MIL, not Bergamo)."""
    forms: dict[City, list[str]] = {}
    for form, city in city_forms().items():
        forms.setdefault(city, []).append(form)
    table: dict[str, tuple[str, tuple[str, ...]]] = {}
    for city in sorted(
        (city for city in all_cities() if city.flies), key=lambda city: len(city.airports)
    ):
        names = (city.name, city.name_pl, city.local_name)
        for key in (*forms.get(city, ()), *(name.casefold() for name in names)):
            table[key] = (city.iata, city.airports)
    return table


# city -> (the code to search with, the airports it covers — for the docs and the feed)
AIRPORTS: dict[str, tuple[str, tuple[str, ...]]] = _airports()


def airport_code(place: str) -> str | None:
    """The code a flight search uses for `place`, or None for a city we do not fly from.
    "Warszawa Centralna" style names match on their first city."""
    city = resolve_city(place)
    if city is not None and city.flies:
        return city.iata
    if _IATA.fullmatch(place.strip()):
        return place.strip().upper()
    return None
