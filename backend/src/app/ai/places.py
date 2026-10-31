"""Reading a trip brief: where the group goes and how it wants to travel. Deterministic text
rules — no LLM, so the default research is reproducible."""

import re

from app.core.domain.places import cities_in, resolve_city
from app.core.domain.trips import TransportMode

DEFAULT_DESTINATION = "Prague"  # the demo trip
# The word before a city that makes it the destination — surely ("do Sztokholmu", "to Rome")
# or probably ("w Pradze", "in Rome": also "we live in Poznań") — or the origin ("z Poznania",
# "from Warsaw").
_TO_WORDS = frozenset({"do", "to", "into", "nach"})
_IN_WORDS = frozenset({"w", "we", "in", "na"})
_FROM_WORDS = frozenset({"z", "ze", "from", "od"})
_MODE_WORDS: dict[TransportMode, str] = {
    TransportMode.FLIGHT: r"fly|flying|flights?|planes?",
    TransportMode.RAIL: r"trains?|rail",
    TransportMode.BUS: r"bus|buses|coach|coaches",
    TransportMode.FERRY: r"ferry|ferries",
}
_ANY_MODE = "|".join(_MODE_WORDS.values())
_THERE = re.compile(rf"\b({_ANY_MODE})\s+(?:there|out|outbound)\b", re.IGNORECASE)
_BACK = re.compile(rf"\b({_ANY_MODE})\s+(?:back|home|return)\b", re.IGNORECASE)


def canonical_place(place: str) -> str:
    """A place's canonical (English) catalogue name — "Sztokholmu" -> "Stockholm" — else the
    place as written."""
    city = resolve_city(place)
    return city.name if city is not None else place.strip()


def destination_of(explicit: str, text: str, origin: str = "") -> str:
    """The explicit destination (by its catalogue name when it has one), else the city the
    text sends the group to ("do Sztokholmu", "to Rome"), else the first city it names that
    is not where the group starts, else the demo's."""
    if explicit.strip():
        return canonical_place(explicit)
    start = resolve_city(origin) if origin.strip() else None
    mentions = cities_in(text)
    marked = next((m.city for m in mentions if m.before in _TO_WORDS), None) or next(
        (m.city for m in mentions if m.before in _IN_WORDS and m.city != start), None
    )
    if marked is not None:
        return marked.name
    unmarked = next(
        (m.city for m in mentions if m.before not in _FROM_WORDS and m.city != start), None
    )
    return unmarked.name if unmarked is not None else DEFAULT_DESTINATION


def origin_of(explicit: str, text: str) -> str:
    """Where the group starts: the explicit origin as written (suppliers resolve it), else
    the city the text marks as the start ("z Poznania", "from Warsaw"), else ""."""
    if explicit.strip():
        return explicit.strip()
    marked = next((m.city for m in cities_in(text) if m.before in _FROM_WORDS), None)
    return marked.name if marked is not None else ""


def _mode_of(word: str) -> TransportMode | None:
    return next(
        (
            mode
            for mode, pattern in _MODE_WORDS.items()
            if re.fullmatch(pattern, word, re.IGNORECASE)
        ),
        None,
    )


def travel_modes(
    preferred: TransportMode | None, text: str
) -> tuple[TransportMode | None, TransportMode | None]:
    """(outbound mode, return mode). The trip's preference wins; otherwise the brief: "fly
    there, train back" -> (flight, rail), "by bus" -> (bus, bus), nothing -> (None, None)."""
    if preferred is not None:
        return preferred, preferred
    there, back = _THERE.search(text), _BACK.search(text)
    if there and back:
        return _mode_of(there.group(1)), _mode_of(back.group(1))
    mentioned = {
        mode
        for mode, pattern in _MODE_WORDS.items()
        if re.search(rf"\b(?:{pattern})\b", text, re.I)
    }
    if len(mentioned) == 1:
        (mode,) = mentioned
        return mode, mode
    return None, None
