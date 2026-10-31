"""Reading a one-line trip brief ("weekend w Pradze dla 6, 20-22.11, do 700 zł/os, pociągiem")
into the fields of a trip, and asking for whatever is missing.

Deterministic text rules in Polish and English first, so the same sentence always gives the
same trip; a `BriefReader` adapter may then fill what the rules missed and word the reply. The
idea follows Boscart's heuristic path (`heuristicRefine` + `heuristicQuestions`): understand
what is there, and turn each missing essential into one question with tappable answers.
Essentials are where (destination), when (dates) and how many (party); the origin defaults to
Warszawa, budget and mode are optional.
"""

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from typing import Protocol

from app.core.domain.places import city_named
from app.core.domain.trips import TransportMode

DEFAULT_ORIGIN = "Warszawa"
DEFAULT_NIGHTS = 2
MAX_PARTY = 20
MAX_NIGHTS = 30
PARTY_OPTIONS = (2, 4, 6, 8)
EN_DASH = "\u2013"


class QuickField(StrEnum):
    """A field a question asks for; the answer comes back in the request field of that name."""

    DESTINATION = "destination"
    DATES = "dates"
    GROUP_SIZE = "group_size"


@dataclass(frozen=True, slots=True)
class QuickOption:
    label: str  # what the chip says: "Next weekend (20-22 Nov)"
    value: str  # what the client sends back in the field: "2026-11-20/2026-11-22"


@dataclass(frozen=True, slots=True)
class QuickQuestion:
    field: QuickField
    question: str
    options: tuple[QuickOption, ...]


@dataclass(frozen=True, slots=True)
class QuickDraft:
    """What the brief says so far. None = not found (yet)."""

    text: str
    origin: str = DEFAULT_ORIGIN
    destination: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    group_size: int | None = None
    budget_per_person_minor: int | None = None
    # A total budget waiting for the party size ("3000 zł łącznie" before "how many?").
    budget_total_minor: int | None = None
    transport_mode: TransportMode | None = None

    @property
    def missing(self) -> tuple[QuickField, ...]:
        found = {
            QuickField.DESTINATION: self.destination is not None,
            QuickField.DATES: self.date_from is not None and self.date_to is not None,
            QuickField.GROUP_SIZE: self.group_size is not None,
        }
        return tuple(field for field, ok in found.items() if not ok)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def title(self) -> str:
        place = self.destination or "Trip"
        if self.date_from is not None and self.date_to is not None:
            nights = (self.date_to - self.date_from).days
            return f"Weekend in {place}" if nights <= 3 else f"{place} trip"
        return f"Trip to {place}"


# ---- places -------------------------------------------------------------------------------

# Canonical name -> the forms people type (Polish cases included). Foreign cities keep the
# English name the suppliers and `app.ai.places` use; Polish ones their Polish name.
PLACES: dict[str, tuple[str, ...]] = {
    "Prague": ("prague", "praha", "praga", "pragi", "pradze", "prag"),
    "Berlin": ("berlin", "berlina", "berlinie"),
    "Vienna": ("vienna", "wien", "wiedeń", "wieden", "wiednia", "wiedniu"),
    "Budapest": ("budapest", "budapeszt", "budapesztu", "budapeszcie"),
    "Barcelona": ("barcelona", "barcelony", "barcelonie", "barcelonę", "barcelone"),
    "Lisbon": ("lisbon", "lisboa", "lizbona", "lizbony", "lizbonie", "lizbonę"),
    "Rome": ("rome", "roma", "rzym", "rzymu", "rzymie"),
    "Madrid": ("madrid", "madryt", "madrytu", "madrycie"),
    "Paris": ("paris", "paryż", "paryz", "paryża", "paryza", "paryżu", "paryzu"),
    "London": ("london", "londyn", "londynu", "londynie"),
    "Amsterdam": ("amsterdam", "amsterdamu", "amsterdamie"),
    "Milan": ("milan", "milano", "mediolan", "mediolanu", "mediolanie"),
    "Athens": ("athens", "ateny", "aten", "atenach"),
    "Copenhagen": ("copenhagen", "kopenhaga", "kopenhagi", "kopenhadze", "kopenhagę"),
    "Munich": ("munich", "münchen", "monachium"),
    "Brussels": ("brussels", "bruksela", "brukseli", "brukselę"),
    "Dublin": ("dublin", "dublina", "dublinie"),
    "Porto": ("porto",),
    "Naples": ("naples", "napoli", "neapol", "neapolu"),
    "Malaga": ("malaga", "málaga", "malagi", "maladze"),
    "Valencia": ("valencia", "walencja", "walencji", "walencję"),
    "Warszawa": ("warszawa", "warszawy", "warszawie", "warszawę", "warsaw", "waw"),
    "Kraków": ("kraków", "krakow", "krakowa", "krakowie", "cracow"),
    "Gdańsk": ("gdańsk", "gdansk", "gdańska", "gdanska", "gdańsku", "gdansku"),
    "Wrocław": ("wrocław", "wroclaw", "wrocławia", "wroclawia", "wrocławiu", "wroclawiu"),
    "Poznań": ("poznań", "poznan", "poznania", "poznaniu"),
    "Katowice": ("katowice", "katowic", "katowicach"),
    "Zakopane": ("zakopane", "zakopanego", "zakopanem"),
}
_ALIAS_TO_PLACE = {alias: name for name, aliases in PLACES.items() for alias in aliases}
# Catalogue cities whose names are also everyday words: only the brief's own aliases count.
_EVERYDAY_WORDS = frozenset({"nice", "split", "pula", "cork", "palma", "kolonia", "hel", "bar"})
_FROM_WORDS = frozenset({"z", "ze", "from"})
_TO_WORDS = frozenset({"do", "to", "w", "we", "in", "into"})
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _known_place(word: str) -> str | None:
    """A word as a place: the brief's own aliases first, then the city catalogue
    ("sztokholmu" -> "Stockholm") — except names that are everyday words in lower case."""
    found = _ALIAS_TO_PLACE.get(word)
    if found is not None or word in _EVERYDAY_WORDS:
        return found
    city = city_named(word)
    return city.name if city is not None else None


def place_of(text: str) -> str | None:
    """The canonical name of a place typed by a person ("Pradze" -> "Prague"), else None."""
    return _known_place(_fold(text).strip())


def _places(folded: str) -> tuple[str | None, str | None]:
    """(origin, destination) from the cities mentioned. "z Krakowa" / "from X" marks the
    origin, "do X" / "w X" / "to X" the destination; two unmarked cities read as "origin -
    destination" ("Warszawa - Praga"), a single one as the destination."""
    marked_from: list[str] = []
    marked_to: list[str] = []
    unmarked: list[str] = []
    previous = ""
    for match in _WORD.finditer(folded):
        word = match.group(0)
        place = _known_place(word)
        if place is not None:
            if previous in _FROM_WORDS:
                marked_from.append(place)
            elif previous in _TO_WORDS:
                marked_to.append(place)
            else:
                unmarked.append(place)
        previous = word
    origin = marked_from[0] if marked_from else None
    destination = marked_to[0] if marked_to else None
    rest = [place for place in unmarked if place not in (origin, destination)]
    if origin is None and destination is None and len(rest) >= 2:
        origin, destination = rest[0], rest[1]
    elif destination is None and rest:
        destination = rest[0]
    if destination is not None and destination == origin:
        destination = None
    return origin, destination


# ---- transport mode -----------------------------------------------------------------------

_MODES: dict[TransportMode, str] = {
    TransportMode.RAIL: r"pociąg\w*|pociag\w*|kolej\w*|trains?|rail|by train",
    TransportMode.FLIGHT: r"samolot\w*|lot|lotem|fly|flying|flights?|planes?",
    TransportMode.BUS: r"autobus\w*|bus|busem|buses|flixbus\w*|coach(?:es)?",
    TransportMode.FERRY: r"prom\w*|ferry|ferries",
}


def _mode(folded: str) -> TransportMode | None:
    """The one mode the brief names; None for none or several ("fly there, train back" is
    left to the researcher, which reads the brief text)."""
    found = {mode for mode, words in _MODES.items() if re.search(rf"\b(?:{words})\b", folded)}
    return found.pop() if len(found) == 1 else None


# ---- party --------------------------------------------------------------------------------

_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "dwie": 2,
    "dwóch": 2,
    "dwoch": 2,
    "dwoje": 2,
    "dwojga": 2,
    "trzy": 3,
    "trzech": 3,
    "troje": 3,
    "trojga": 3,
    "cztery": 4,
    "czterech": 4,
    "czworo": 4,
    "pięć": 5,
    "piec": 5,
    "pięciu": 5,
    "pieciu": 5,
    "sześć": 6,
    "szesc": 6,
    "sześciu": 6,
    "szesciu": 6,
    "siedem": 7,
    "siedmiu": 7,
    "osiem": 8,
    "ośmiu": 8,
    "osmiu": 8,
}
_N = rf"(\d{{1,2}}|{'|'.join(_NUMBER_WORDS)})"
_PARTY_PATTERNS = (
    re.compile(rf"\bdla\s+{_N}\b(?!\s*(?:zł|zl|pln|%|\.\d))"),
    re.compile(
        rf"\b{_N}\s*(?:osób|osob|osoby|os\b|os\.|people|persons|pax|friends|znajomych|ludzi)"
    ),
    re.compile(rf"\bfor\s+{_N}\b(?!\s*(?:zł|zl|pln|nights?|days?|nocy|noce|dni|%))"),
    re.compile(rf"\b(?:party|group) of\s+{_N}\b"),
    re.compile(rf"\b(?:we are|we're|nas jest|jest nas)\s+{_N}\b"),
)
_SOLO = re.compile(r"\b(?:solo|alone|just me|sam|sama|tylko ja)\b")
_COUPLE = re.compile(r"\b(?:couple|we dwoje|we dwójkę|we dwojke|para|dla pary)\b")


def _number(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def _party(folded: str) -> int | None:
    for pattern in _PARTY_PATTERNS:
        match = pattern.search(folded)
        if match is not None:
            size = _number(match.group(1))
            if 1 <= size <= MAX_PARTY:
                return size
    if _COUPLE.search(folded):
        return 2
    if _SOLO.search(folded):
        return 1
    return None


# ---- budget -------------------------------------------------------------------------------

_AMOUNT = r"(\d+(?:[.,]\d+)?)\s*(k|tys\.?)?\s*"
_CURRENCY = r"(?:zł|zl|złotych|zlotych|pln)"
_BUDGET = re.compile(rf"{_AMOUNT}{_CURRENCY}(?P<after>[^,;]{{0,24}})")
_PER_PERSON = re.compile(
    r"^\s*(?:/\s*(?:os|osobę|osobe|osoba|person|pp)|na (?:osobę|osobe|głowę|glowe|łeb|leb)"
    r"|per (?:person|head)|pp\b|each|od osoby|za osobę|za osobe)"
)
_TOTAL = re.compile(
    r"^\s*(?:łącznie|lacznie|razem|w sumie|total|in total|altogether|all in|na wszystkich"
    r"|za wszystko|for everyone|for all)"
)
_TOTAL_BEFORE = re.compile(r"(?:łącznie|lacznie|razem|w sumie|total|altogether)\s*(?:do|max)?\s*$")


def _budget(folded: str) -> tuple[int | None, int | None]:
    """(per person, total) in minor units; at most one of them is set."""
    for match in _BUDGET.finditer(folded):
        amount = float(match.group(1).replace(",", "."))
        if match.group(2):
            amount *= 1000
        minor = round(amount * 100)
        if minor <= 0:
            continue
        after = match.group("after")
        before = folded[max(0, match.start() - 16) : match.start()]
        if _TOTAL.match(after) or _TOTAL_BEFORE.search(before):
            return None, minor
        return minor, None  # "/os", "na osobę" — and a bare "do 700 zł" reads per person
    return None, None


# ---- dates --------------------------------------------------------------------------------

_MONTHS: dict[str, int] = {}
for _number_of_month, _names in enumerate(
    (
        ("jan", "january", "styczeń", "styczen", "stycznia"),
        ("feb", "february", "luty", "lutego"),
        ("mar", "march", "marzec", "marca"),
        ("apr", "april", "kwiecień", "kwiecien", "kwietnia"),
        ("may", "maj", "maja"),
        ("jun", "june", "czerwiec", "czerwca"),
        ("jul", "july", "lipiec", "lipca"),
        ("aug", "august", "sierpień", "sierpien", "sierpnia"),
        ("sep", "sept", "september", "wrzesień", "wrzesien", "września", "wrzesnia"),
        ("oct", "october", "październik", "pazdziernik", "października", "pazdziernika"),
        ("nov", "november", "listopad", "listopada"),
        ("dec", "december", "grudzień", "grudzien", "grudnia"),
    ),
    start=1,
):
    for _name in _names:
        _MONTHS[_name] = _number_of_month
_MONTH = rf"({'|'.join(sorted(_MONTHS, key=len, reverse=True))})\b\.?"
_DASH = r"\s*(?:-|\u2013|\u2014|do|to|until|till)\s*"  # hyphen, en dash, em dash
_YEAR = r"(?:[ .](\d{4}))?"

_ISO_RANGE = re.compile(rf"(\d{{4}})-(\d{{2}})-(\d{{2}})(?:{_DASH}|/)(\d{{4}})-(\d{{2}})-(\d{{2}})")
_ISO_DAY = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# 20-22.11 / 20-22.11.2026
_NUM_SHORT_RANGE = re.compile(rf"\b(\d{{1,2}}){_DASH}(\d{{1,2}})\.(\d{{1,2}})(?:\.(\d{{4}}))?\b")
# 20.11-22.11 / 30.11-2.12.2026
_NUM_FULL_RANGE = re.compile(
    rf"\b(\d{{1,2}})\.(\d{{1,2}})(?:\.(\d{{4}}))?{_DASH}(\d{{1,2}})\.(\d{{1,2}})(?:\.(\d{{4}}))?\b"
)
# 20-22 listopada / 20-22 November
_WORD_SHORT_RANGE = re.compile(rf"\b(\d{{1,2}}){_DASH}(\d{{1,2}})\s+{_MONTH}{_YEAR}")
# 30 listopada - 2 grudnia / 30 Nov - 2 Dec
_WORD_FULL_RANGE = re.compile(rf"\b(\d{{1,2}})\s+{_MONTH}{_DASH}(\d{{1,2}})\s+{_MONTH}{_YEAR}")
# Nov 20-22 / November 20-22
_MONTH_FIRST_RANGE = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}}){_DASH}(\d{{1,2}})\b{_YEAR}")
_WORD_DAY = re.compile(rf"\b(\d{{1,2}})\s+{_MONTH}{_YEAR}")
_NUM_DAY = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b(?!\s*(?:zł|zl|pln|k\b))")
_NIGHTS = re.compile(
    r"\b(\d{1,2})\s*(?:nights?|nocy|noce|noc|nocleg\w*)|\b(\d{1,2})\s*(?:days?|dni)\b"
)
_THIS_WEEKEND = re.compile(r"\b(?:this weekend|ten weekend|w ten weekend|najbliższy weekend)\b")
_NEXT_WEEKEND = re.compile(
    r"\b(?:next weekend|przyszły weekend|przyszly weekend|w przyszły weekend|"
    r"w przyszly weekend|za tydzień|za tydzien)\b"
)
_LONG = re.compile(r"\b(?:long weekend|długi weekend|dlugi weekend)\b")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _upcoming(month: int, day: int, today: date) -> date | None:
    """The next `day.month` on or after today (this year, else next year)."""
    for year in (today.year, today.year + 1):
        found = _safe_date(year, month, day)
        if found is not None and found >= today:
            return found
    return None


def _dated(month: int, day: int, year: str | None, today: date) -> date | None:
    return _safe_date(int(year), month, day) if year else _upcoming(month, day, today)


def _range(start: date | None, end: date | None) -> tuple[date, date] | None:
    if start is None or end is None:
        return None
    if end < start:  # "30.12-2.01": the end is in the next year
        end = _safe_date(end.year + 1, end.month, end.day) or end
    if end <= start or (end - start).days > MAX_NIGHTS:
        return None
    return start, end


def coming_friday(today: date) -> date:
    """The Friday of "this weekend": today when it is Friday, else the next one."""
    return today + timedelta(days=(4 - today.weekday()) % 7)


def _explicit_range(folded: str, today: date) -> tuple[date, date] | None:
    if m := _ISO_RANGE.search(folded):
        iso = [int(group) for group in m.groups()]
        return _range(_safe_date(*iso[:3]), _safe_date(*iso[3:]))
    if m := _NUM_FULL_RANGE.search(folded):
        d1, m1, y1, d2, m2, y2 = m.groups()
        year = y1 or y2
        start = _dated(int(m1), int(d1), year, today)
        return _range(start, _dated(int(m2), int(d2), y2 or year, start or today))
    if m := _NUM_SHORT_RANGE.search(folded):
        d1, d2, month, year = m.groups()
        start = _dated(int(month), int(d1), year, today)
        return _range(start, _dated(int(month), int(d2), year, start or today))
    if m := _WORD_FULL_RANGE.search(folded):
        d1, m1, d2, m2, year = m.groups()
        start = _dated(_MONTHS[m1], int(d1), year, today)
        return _range(start, _dated(_MONTHS[m2], int(d2), year, start or today))
    if m := _WORD_SHORT_RANGE.search(folded):
        d1, d2, month, year = m.groups()
        start = _dated(_MONTHS[month], int(d1), year, today)
        return _range(start, _dated(_MONTHS[month], int(d2), year, start or today))
    if m := _MONTH_FIRST_RANGE.search(folded):
        month, d1, d2, year = m.groups()
        start = _dated(_MONTHS[month], int(d1), year, today)
        return _range(start, _dated(_MONTHS[month], int(d2), year, start or today))
    return None


def _single_day(folded: str, today: date) -> date | None:
    if m := _ISO_DAY.search(folded):
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := _WORD_DAY.search(folded):
        return _dated(_MONTHS[m.group(2)], int(m.group(1)), m.group(3), today)
    if m := _NUM_DAY.search(folded):
        day, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return _dated(month, day, m.group(3), today)
    return None


def _nights(folded: str, *, long: bool) -> int:
    if m := _NIGHTS.search(folded):
        nights = int(m.group(1)) if m.group(1) else max(int(m.group(2)) - 1, 1)
        if 1 <= nights <= MAX_NIGHTS:
            return nights
    return DEFAULT_NIGHTS + 1 if long else DEFAULT_NIGHTS


def dates_of(text: str, today: date) -> tuple[date, date] | None:
    """(first day, last day) from the brief, or None when it names no dates."""
    folded = _fold(text)
    explicit = _explicit_range(folded, today)
    if explicit is not None:
        return explicit
    nights = _nights(folded, long=bool(_LONG.search(folded)))
    start = _single_day(folded, today)
    if start is None and _NEXT_WEEKEND.search(folded):
        start = coming_friday(today) + timedelta(days=7)
    elif start is None and (_THIS_WEEKEND.search(folded) or _LONG.search(folded)):
        start = coming_friday(today)
    if start is None:
        return None
    return start, start + timedelta(days=nights)


# ---- the whole brief ----------------------------------------------------------------------


def parse_quick_brief(text: str, today: date) -> QuickDraft:
    folded = _fold(text)
    origin, destination = _places(folded)
    dates = dates_of(text, today)
    per_person, total = _budget(folded)
    draft = QuickDraft(
        text=text.strip(),
        origin=origin or DEFAULT_ORIGIN,
        destination=destination,
        date_from=dates[0] if dates else None,
        date_to=dates[1] if dates else None,
        group_size=_party(folded),
        budget_per_person_minor=per_person,
        budget_total_minor=total,
        transport_mode=_mode(folded),
    )
    return settle_budget(draft)


def settle_budget(draft: QuickDraft) -> QuickDraft:
    """A total budget becomes per person once the party size is known."""
    if draft.budget_total_minor is None or draft.group_size is None:
        return draft
    return replace(
        draft,
        budget_per_person_minor=draft.budget_total_minor // draft.group_size,
        budget_total_minor=None,
    )


@dataclass(frozen=True, slots=True)
class QuickAnswers:
    """The client's answers to earlier questions (and any explicit overrides)."""

    destination: str | None = None
    origin: str | None = None
    dates: str | None = None  # "2026-11-20/2026-11-22", or any phrase `dates_of` reads
    group_size: int | None = None
    budget_per_person_minor: int | None = None
    transport_mode: TransportMode | None = None


def apply_answers(draft: QuickDraft, answers: QuickAnswers, today: date) -> QuickDraft:
    """Answers win over what the text said."""
    dates = dates_of(answers.dates, today) if answers.dates else None
    budget_answered = answers.budget_per_person_minor is not None
    return settle_budget(
        replace(
            draft,
            destination=_place_answer(answers.destination) or draft.destination,
            origin=_place_answer(answers.origin) or draft.origin,
            date_from=dates[0] if dates else draft.date_from,
            date_to=dates[1] if dates else draft.date_to,
            group_size=answers.group_size or draft.group_size,
            budget_per_person_minor=answers.budget_per_person_minor
            if budget_answered
            else draft.budget_per_person_minor,
            budget_total_minor=None if budget_answered else draft.budget_total_minor,
            transport_mode=answers.transport_mode or draft.transport_mode,
        )
    )


def _place_answer(answer: str | None) -> str | None:
    if answer is None or not answer.strip():
        return None
    return place_of(answer) or answer.strip()


def _span(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.day}{EN_DASH}{end.day} {end:%b}"
    return f"{start.day} {start:%b} {EN_DASH} {end.day} {end:%b}"


def _date_option(label: str, start: date, nights: int) -> QuickOption:
    end = start + timedelta(days=nights)
    return QuickOption(label=f"{label} ({_span(start, end)})", value=f"{start}/{end}")


POPULAR_DESTINATIONS = ("Prague", "Berlin", "Vienna", "Budapest", "Barcelona")


def questions_for(draft: QuickDraft, today: date) -> tuple[QuickQuestion, ...]:
    """One question per missing essential, each with chips the client can send back."""
    asked: list[QuickQuestion] = []
    for missing in draft.missing:
        match missing:
            case QuickField.DESTINATION:
                asked.append(
                    QuickQuestion(
                        field=missing,
                        question="Where to?",
                        options=tuple(
                            QuickOption(label=name, value=name)
                            for name in POPULAR_DESTINATIONS
                            if name != draft.origin
                        ),
                    )
                )
            case QuickField.DATES:
                friday = coming_friday(today + timedelta(days=1))
                asked.append(
                    QuickQuestion(
                        field=missing,
                        question="When?",
                        options=(
                            _date_option("This weekend", friday, DEFAULT_NIGHTS),
                            _date_option("Next weekend", friday + timedelta(days=7), 2),
                            _date_option("Long weekend", friday + timedelta(days=14), 3),
                        ),
                    )
                )
            case QuickField.GROUP_SIZE:
                asked.append(
                    QuickQuestion(
                        field=missing,
                        question="How many people?",
                        options=tuple(
                            QuickOption(label=str(size), value=str(size)) for size in PARTY_OPTIONS
                        ),
                    )
                )
    return tuple(asked)


# ---- the reader port and the agent's reply ------------------------------------------------


@dataclass(frozen=True, slots=True)
class BriefReading:
    draft: QuickDraft
    reply: str  # the agent's chat message about this draft


class BriefReader(Protocol):
    """Reads a draft the rules produced: may fill its missing fields, always writes a reply."""

    async def read(self, draft: QuickDraft, today: date) -> BriefReading: ...


class RulesBriefReader:
    """No LLM: the draft as the rules read it, with a reply built from its fields."""

    async def read(self, draft: QuickDraft, today: date) -> BriefReading:
        return BriefReading(draft=draft, reply=reply_for(draft))


_MODE_WORDS = {
    TransportMode.RAIL: "by train",
    TransportMode.FLIGHT: "by plane",
    TransportMode.BUS: "by bus",
    TransportMode.FERRY: "by ferry",
}
_ASKS = {
    QuickField.DESTINATION: "where to",
    QuickField.DATES: "when",
    QuickField.GROUP_SIZE: "how many people",
}


def _understood(draft: QuickDraft) -> list[str]:
    parts: list[str] = []
    if draft.destination is not None:
        parts.append(draft.destination)
    if draft.date_from is not None and draft.date_to is not None:
        parts.append(_span(draft.date_from, draft.date_to))
    if draft.group_size is not None:
        parts.append(f"{draft.group_size} people" if draft.group_size > 1 else "just you")
    if draft.transport_mode is not None:
        parts.append(_MODE_WORDS[draft.transport_mode])
    return parts


def reply_for(draft: QuickDraft) -> str:
    """ "Prague, by train, got it. Just tell me when and how many people." """
    understood = ", ".join(_understood(draft))
    if draft.complete:
        return f"Got it: {understood}. Looking for packages now."
    asks = [_ASKS[field] for field in draft.missing]
    wanted = asks[0] if len(asks) == 1 else f"{', '.join(asks[:-1])} and {asks[-1]}"
    if not understood:
        return f"Tell me {wanted}."
    return f"{understood}, got it. Just tell me {wanted}."
