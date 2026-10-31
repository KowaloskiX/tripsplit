"""Why a traveller can trust an offer: where it came from, and links to check it themselves.

Every offer, package item and booking carries `links` (book it at the supplier, verify it on an
independent site, find it on a map, follow its status), `provenance` (live data, a supplier's
test or sandbox API, or an illustrative example) and `images`. Pure Python: the adapters build
them, the services copy them through, the API shows them. A simulated offer is an `example`
and never gets a link that pretends to be real.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from urllib.parse import quote, urlencode


class LinkKind(StrEnum):
    BOOK = "book"  # the supplier's own page where it is bought
    VERIFY = "verify"  # an independent search that shows the same route / place exists
    MAP = "map"
    STATUS = "status"  # live status of a flight / train by its number


class ProvenanceSource(StrEnum):
    LIVE = "live"  # the supplier's real, current data
    TEST = "test"  # the supplier's test mode (real API, test inventory)
    SANDBOX = "sandbox"  # the supplier's sandbox (real catalogue, nothing is charged)
    EXAMPLE = "example"  # illustrative data from a simulator


@dataclass(frozen=True, slots=True)
class OfferLink:
    label: str
    url: str
    kind: LinkKind


@dataclass(frozen=True, slots=True)
class Provenance:
    source: ProvenanceSource
    supplier: str  # who the data came from, for people ("PKP Intercity", "Duffel")
    # When it was asked — metadata, not identity: the same offer found twice is equal.
    checked_at: datetime = field(compare=False)


MAX_LINKS = 6
MAX_IMAGES = 6


def google_flights_url(
    origin: str, destination: str, depart: date, return_date: date | None = None
) -> str:
    """A Google Flights search for the route and dates (no booking, just "it exists")."""
    query = f"Flights from {origin} to {destination} on {depart.isoformat()}"
    if return_date is not None:
        query += f" through {return_date.isoformat()}"
    return f"https://www.google.com/travel/flights?{urlencode({'q': query})}"


def flight_status_url(number: str) -> str:
    """Flightradar24's page for a flight number ("LO 401" -> .../data/flights/lo401)."""
    compact = "".join(number.split()).lower()
    return f"https://www.flightradar24.com/data/flights/{quote(compact)}"


def maps_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/?{urlencode({'api': '1', 'query': query})}"


def is_web_url(url: str) -> bool:
    return url.startswith(("https://", "http://"))
