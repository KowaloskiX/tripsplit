"""Reading a trip brief: where the group goes and how it wants to travel. Deterministic text
rules — no LLM, so the default research is reproducible."""

import re

from app.core.domain.trips import TransportMode

DEFAULT_DESTINATION = "Prague"  # the demo trip
_DESTINATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Prague", ("prague", "praha", "prag")),
    ("Berlin", ("berlin",)),
    ("Vienna", ("vienna", "wien", "wiedeń", "wieden")),
    ("Budapest", ("budapest", "budapeszt")),
    ("Barcelona", ("barcelona", "barcelonie")),
    ("Lisbon", ("lisbon", "lisboa", "lizbona")),
    ("Rome", ("rome", "roma", "rzym")),
)
_MODE_WORDS: dict[TransportMode, str] = {
    TransportMode.FLIGHT: r"fly|flying|flights?|planes?",
    TransportMode.RAIL: r"trains?|rail",
    TransportMode.BUS: r"bus|buses|coach|coaches",
    TransportMode.FERRY: r"ferry|ferries",
}
_ANY_MODE = "|".join(_MODE_WORDS.values())
_THERE = re.compile(rf"\b({_ANY_MODE})\s+(?:there|out|outbound)\b", re.IGNORECASE)
_BACK = re.compile(rf"\b({_ANY_MODE})\s+(?:back|home|return)\b", re.IGNORECASE)


def destination_of(explicit: str, text: str) -> str:
    """The explicit destination, else the first known city in the text, else the demo's."""
    if explicit.strip():
        return explicit.strip()
    folded = text.casefold()
    for name, aliases in _DESTINATIONS:
        if any(alias in folded for alias in aliases):
            return name
    return DEFAULT_DESTINATION


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
