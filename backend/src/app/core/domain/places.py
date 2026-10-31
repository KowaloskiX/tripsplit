"""The city catalogue: one place that knows every city a trip from Poland is likely to name.

Each `City` carries its English (canonical) name, Polish and local names, ISO country code,
centre coordinates, the IATA code a flight search uses, the airports it covers and the PKP
Intercity station query. The rows live in `places_data`; this module indexes them.

`resolve_city` reads a city out of whatever a person or a supplier wrote — "Sztokholmu",
"z Poznania", "WIEDEŃ", "Praga Gł./Praha hl.n.", "bcn" — case-, diacritics- and
declension-insensitively. Polish declensions are derived from the Polish name by a few
regular rules (`polish_forms`: Praga -> Pragi/Pradze/Pragę, Sztokholm -> Sztokholmu/
Sztokholmie, Poznań -> Poznania/Poznaniu); irregular ones (Wiedeń -> Wiednia) are listed in the
row. A derived form shared by two cities is dropped rather than guessed. `cities_in` lists
every city mentioned in a free text with the word before it ("z", "do", "w", "from", "to"),
for reading where a trip starts and where it goes.

Pure Python: suppliers and the brief parser depend on it, never the other way round.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from app.core.domain.places_data import ROWS, Row


@dataclass(frozen=True, slots=True)
class City:
    name: str  # canonical, English ("Stockholm", "Krakow")
    name_pl: str  # "Sztokholm", "Kraków"
    local_name: str  # "Stockholm", "Kraków", "Praha"
    country_code: str  # ISO 3166-1 alpha-2
    latitude: float  # the centre
    longitude: float
    iata: str  # the code a flight search uses; "" = no flights
    airports: tuple[str, ...]
    pkp_station: str  # the PKP Intercity station query; "" = none worth asking for
    extra_forms: tuple[str, ...] = ()

    @property
    def flies(self) -> bool:
        return bool(self.iata)


@dataclass(frozen=True, slots=True)
class Mention:
    """A city named in a text: where, and the (folded) word right before it."""

    city: City
    start: int
    end: int
    before: str


# Cities whose names are also everyday words ("nice", "split", Polish "pula", "palma",
# "kolonia"): in a free text they count only when written with a capital letter.
_CAPITALISED_ONLY: frozenset[str] = frozenset(
    {"Nice", "Split", "Pula", "Cork", "Palma", "Cologne", "Hel"}
)
_TRANSLITERATE = str.maketrans(
    {
        "ł": "l",
        "Ł": "l",
        "ø": "o",
        "Ø": "o",
        "æ": "ae",
        "Æ": "ae",
        "đ": "d",
        "Đ": "d",
        "\u0131": "i",  # dotless i (Turkish)
    }
)
_TOKEN = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_IATA = re.compile(r"[A-Za-z]{3}")
_MAX_WORDS = 4


def fold(text: str) -> str:
    """Case- and diacritics-insensitive form: "Łódź" -> "lodz", "MÜNCHEN" -> "munchen"."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_TRANSLITERATE))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def normalise(text: str) -> str:
    """Folded words joined by single spaces: "Frankfurt (Oder)" -> "frankfurt oder"."""
    return " ".join(_TOKEN.findall(fold(text)))


# ---- Polish declension ------------------------------------------------------------------------

# The locative of a feminine "-a" noun by the consonant before it: Praga -> Pradze.
_FEMININE_LOCATIVE: dict[str, str] = {
    "g": "dze",
    "k": "ce",
    "r": "rze",
    "t": "cie",
    "d": "dzie",
    "ch": "sze",
    "l": "li",
}
# The locative of a masculine noun by its final consonant: Madryt -> Madrycie.
_MASCULINE_LOCATIVE: dict[str, str] = {
    "t": "cie",
    "d": "dzie",
    "r": "rze",
    "l": "le",
    "st": "scie",
}
_SOFT = ("ń", "ś", "ć", "ź")
_VOWELS = "aeiouy"


def _ending(word: str, table: dict[str, str]) -> str | None:
    """The longest ending of `word` that `table` has a rule for."""
    return next((end for end in sorted(table, key=len, reverse=True) if word.endswith(end)), None)


def _feminine(stem: str) -> set[str]:
    forms = {stem + "y", stem + "i", stem + "e", stem + "a"}
    if stem.endswith("i"):  # Kolonia -> Kolonii, Gdynia -> Gdyni
        forms |= {stem + "i", stem[:-1] + "i"}
    elif stem.endswith("j"):  # Walencja -> Walencji
        forms.add(stem + "i")
    else:
        ending = _ending(stem, _FEMININE_LOCATIVE)
        forms.add(stem[: -len(ending)] + _FEMININE_LOCATIVE[ending] if ending else stem + "ie")
    return forms


def _masculine(word: str, soft: bool) -> set[str]:
    if soft:  # Poznań -> Poznania, Poznaniu; Toruń -> Torunia
        return {word + "ia", word + "iu", word + "iem"}
    forms = {word + "u", word + "a", word + "em"}
    ending = _ending(word, _MASCULINE_LOCATIVE)
    if ending:
        forms.add(word[: -len(ending)] + _MASCULINE_LOCATIVE[ending])
    elif not word.endswith(("k", "g", "ch", "sz", "cz", "rz", "z", "c")):
        forms.add(word + "ie")
    return forms


def polish_forms(nominative: str) -> frozenset[str]:
    """The regular case forms (genitive, dative-locative, accusative, instrumental) of a
    one-word Polish city name, folded. Over-generation is harmless: only these names are
    looked up, and a form two cities share is dropped from the index."""
    if " " in nominative.strip() or len(nominative.strip()) < 4:
        return frozenset()
    lower = nominative.strip().casefold()
    word = fold(lower)
    if word.endswith("a") and word[-2:-1] not in "aeouy":  # "-ia" is feminine too
        return frozenset(_feminine(word[:-1]))
    if word[-1] in _VOWELS:  # neuter, plural or foreign: irregular forms are in the row
        return frozenset()
    return frozenset(_masculine(word, soft=lower.endswith(_SOFT)))


# ---- the index --------------------------------------------------------------------------------


def _city(row: Row) -> City:
    name, name_pl, local, country, lat, lon, iata, airports, station, extra = row
    return City(
        name=name,
        name_pl=name_pl,
        local_name=local,
        country_code=country,
        latitude=lat,
        longitude=lon,
        iata=iata,
        airports=airports,
        pkp_station=station,
        extra_forms=tuple(form for form in extra.split("|") if form),
    )


def _primary_forms(city: City) -> set[str]:
    names = (city.name, city.name_pl, city.local_name, *city.extra_forms)
    return {normalise(name) for name in names} - {""}


@dataclass(frozen=True, slots=True)
class _Index:
    cities: tuple[City, ...]
    by_form: dict[str, City]
    by_code: dict[str, City]


def _index(cities: Iterable[City]) -> _Index:
    """Every form -> its city. Two cities claiming one primary form is a data error; a derived
    form that collides with anything is left out."""
    cities = tuple(cities)
    primary: dict[str, City] = {}
    for city in cities:
        for form in _primary_forms(city):
            other = primary.setdefault(form, city)
            if other is not city:
                raise ValueError(f"{form!r} names both {other.name} and {city.name}")
    derived: dict[str, City | None] = {}
    for city in cities:
        for form in polish_forms(city.name_pl) - set(primary):
            derived[form] = city if derived.get(form, city) is city else None
    by_form = {form: city for form, city in derived.items() if city is not None} | primary
    by_code: dict[str, City] = {}
    for city in cities:  # a city's own code first, then the airports it covers
        if city.iata:
            by_code.setdefault(city.iata, city)
    for city in cities:
        for airport in city.airports:
            by_code.setdefault(airport, city)
    return _Index(cities, by_form, by_code)


@cache
def _catalogue() -> _Index:
    return _index(_city(row) for row in ROWS)


def all_cities() -> tuple[City, ...]:
    return _catalogue().cities


def city_forms() -> dict[str, City]:
    """Every folded form the catalogue resolves (names, declensions, other spellings)."""
    return dict(_catalogue().by_form)


def city_named(text: str) -> City | None:
    """The city `text` is a name or form of as a whole ("Poznania"), else None — unlike
    `resolve_city`, "Warszawa Wschodnia" (a station) is not Warsaw here."""
    return _catalogue().by_form.get(normalise(text))


def city_by_code(code: str) -> City | None:
    """The city an IATA city or airport code belongs to ("ARN" -> Stockholm)."""
    return _catalogue().by_code.get(code.strip().upper())


def _tokens(text: str, forms: dict[str, City]) -> list[tuple[str, str, int, int]]:
    """(original, folded, start, end) per word; "Warszawa-Praga" is two words unless the
    hyphenated whole is a city ("Bielsko-Biała")."""
    tokens: list[tuple[str, str, int, int]] = []
    for match in _TOKEN.finditer(text):
        word = match.group(0)
        if "-" in word and fold(word) not in forms:
            offset = match.start()
            for part in word.split("-"):
                tokens.append((part, fold(part), offset, offset + len(part)))
                offset += len(part) + 1
        else:
            tokens.append((word, fold(word), match.start(), match.end()))
    return tokens


def cities_in(text: str) -> list[Mention]:
    """Every catalogue city named in `text`, in order (the longest name wins: "Frankfurt nad
    Odrą" is not Frankfurt am Main). Cities whose names are everyday words count only when
    capitalised."""
    forms = _catalogue().by_form
    tokens = _tokens(text, forms)
    mentions: list[Mention] = []
    index = 0
    while index < len(tokens):
        found = None
        for size in range(min(_MAX_WORDS, len(tokens) - index), 0, -1):
            words = tokens[index : index + size]
            city = forms.get(" ".join(folded for _, folded, _, _ in words))
            if city is not None and (
                city.name not in _CAPITALISED_ONLY or words[0][0][:1].isupper()
            ):
                found = (city, size)
                break
        if found is None:
            index += 1
            continue
        city, size = found
        before = tokens[index - 1][1] if index > 0 else ""
        mentions.append(Mention(city, tokens[index][2], tokens[index + size - 1][3], before))
        index += size
    return mentions


def resolve_city(text: str) -> City | None:
    """The catalogue city `text` names: the whole text as a name or form ("Sztokholmu"), a
    bare IATA code ("bcn", "ARN"), else the first city mentioned in it ("Warszawa
    Centralna", "Praga Gł./Praha hl.n.")."""
    key = normalise(text)
    if not key:
        return None
    index = _catalogue()
    if key in index.by_form:
        return index.by_form[key]
    if _IATA.fullmatch(text.strip()):
        by_code = index.by_code.get(text.strip().upper())
        if by_code is not None:
            return by_code
    mentions = cities_in(text)
    return mentions[0].city if mentions else None
