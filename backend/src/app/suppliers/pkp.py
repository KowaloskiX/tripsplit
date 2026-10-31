"""`pkp_intercity`: the real PKP Intercity behind the supplier port.

Search and quote go to the e-IC JSON gateway through `IntercityClient` (read-only, unofficial —
see `app.suppliers.intercity`). Buying stays with the booking agent: the channel is `agent` and
an offer's `purchase_url` is the deterministic e-IC results page for its first train. One online
purchase carries at most five passengers, which the capabilities declare — the trip flow splits
a bigger party from that, never from the carrier's name.

An offer is a whole journey (one way, or out and back) for the whole party in one class; its
`supplier_data` records each leg (station codes, departure, first train number) so a re-quote
asks for exactly the same trains.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.domain.result import Err, Result
from app.core.domain.suppliers import NAME_ONLY, SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import (
    NO_PREFERENCES,
    BookingKind,
    SupplierChannel,
    TransportMode,
    TravelPreferences,
)
from app.core.domain.trust import LinkKind, OfferLink, Provenance, ProvenanceSource
from app.suppliers.intercity import (
    MAX_PASSENGERS_PER_PURCHASE,
    Connection,
    FareQuote,
    IntercityClient,
    Station,
    Transport,
    results_url,
    split_group,
)
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
    Segment,
    SupplierUnavailableError,
)

logger = logging.getLogger(__name__)

SUPPLIER_ID = "pkp_intercity"
CARRIER = "PKP Intercity"
LOCAL = ZoneInfo("Europe/Warsaw")
# Departure windows a weekend trip wants (outbound morning, return afternoon).
OUTBOUND_HOURS = range(5, 12)
RETURN_HOURS = range(13, 21)
MAX_CONNECTIONS = 6
# City names as people type them -> the station query that finds the main station.
STATION_ALIASES: dict[str, str] = {
    "warszawa": "Warszawa Centralna",
    "warsaw": "Warszawa Centralna",
    "kraków": "Kraków Główny",
    "krakow": "Kraków Główny",
    "prague": "Praha",
    "praha": "Praha",
    "berlin": "Berlin Hbf",
    "vienna": "Wien Hbf",
    "wien": "Wien Hbf",
    "budapest": "Budapest-Keleti",
}

CAPABILITIES = SupplierCapabilities(
    kind=BookingKind.TRANSPORT,
    mode=TransportMode.RAIL,
    channel=SupplierChannel.AGENT,
    max_party_per_purchase=MAX_PASSENGERS_PER_PURCHASE,
    quote_ttl=timedelta(minutes=15),
    required_traveller_fields=NAME_ONLY,
)


@dataclass(frozen=True, slots=True)
class LegQuote:
    direction: str  # "outbound" | "return"
    connection: str
    departs_at: datetime
    arrives_at: datetime
    travel_class: int
    offer_name: str
    purchases: tuple[int, ...]  # grosze per purchase
    passengers: tuple[int, ...]
    from_code: int = 0
    to_code: int = 0
    train_number: int = 0

    @property
    def total_minor(self) -> int:
        return sum(self.purchases)


@dataclass
class LiveSearchLog:
    """What the real search found — shown in harness reports."""

    origin: str = ""
    destination: str = ""
    seconds: float = 0.0
    legs: list[LegQuote] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _in_window(
    connections: Sequence[Connection],
    hours: range,
    preferences: TravelPreferences = NO_PREFERENCES,
) -> list[Connection]:
    """The connections the group accepts (earliest departure, transfers), preferring the
    weekend window; none when the preferences rule every connection out."""
    allowed = [c for c in connections if preferences.accepts(c.departs_at.hour, len(c.legs) - 1)]
    preferred = [c for c in allowed if c.departs_at.hour in hours]
    return (preferred or allowed)[:MAX_CONNECTIONS]


def _cheapest(fares: Sequence[FareQuote], travel_class: int) -> FareQuote | None:
    matching = [f for f in fares if f.travel_class == travel_class and not f.refundable]
    return min(matching, key=lambda fare: fare.total_minor, default=None)


def _links(legs: Sequence[LegQuote]) -> tuple[OfferLink, ...]:
    """Each leg's results page on e-IC (PKP's own shop): the train, the date, the time."""
    return tuple(
        OfferLink(
            label=f"{leg.connection} on e-IC ({leg.direction}, {leg.departs_at:%d %b %H:%M})",
            url=results_url(
                leg.departs_at.date(), leg.from_code, leg.to_code, f"{leg.departs_at:%H:%M}"
            ),
            kind=LinkKind.BOOK,
        )
        for leg in legs
        if leg.from_code and leg.to_code
    )


def _local(moment: datetime) -> datetime:
    return moment.replace(tzinfo=LOCAL) if moment.tzinfo is None else moment


class PkpIntercitySupplier:
    id = SUPPLIER_ID
    display_name = CARRIER

    def __init__(self, transport: Transport, purchase_site: str | None = None) -> None:
        """`purchase_site`: in a demo, where the agent BUYS the train instead of e-IC (our
        fake rail site) — prices still come from PKP, the agent never drives intercity.pl."""
        self.capabilities = CAPABILITIES
        self.client = IntercityClient(transport)
        self.purchase_site = purchase_site
        self.log = LiveSearchLog()

    # ---- search -------------------------------------------------------------------------

    async def search(self, request: SearchRequest) -> list[Offer]:
        if request.mode not in (None, TransportMode.RAIL):
            return []
        started = time.monotonic()
        try:
            return await self._search(request)
        except Exception:
            # The boundary to an unofficial API: a failed search means "no rail offers", and
            # the reason goes to the log the harness reports — never a crashed research.
            logger.exception("PKP Intercity search failed")
            self.log.notes.append("the PKP Intercity search failed")
            return []
        finally:
            self.log.seconds = round(self.log.seconds + time.monotonic() - started, 1)

    async def _station(self, name: str) -> Station | None:
        query = STATION_ALIASES.get(name.strip().casefold(), name)
        return await self.client.station(query)

    async def _search(self, request: SearchRequest) -> list[Offer]:
        origin, destination = await asyncio.gather(
            self._station(request.origin), self._station(request.destination)
        )
        if origin is None or destination is None:
            self.log.notes.append(f"unknown station: {request.origin} / {request.destination}")
            return []
        self.log.origin, self.log.destination = origin.name, destination.name
        party = request.party_size
        wants = request.preferences
        # Both directions at once; the client bounds how many calls are in flight.
        directions = [
            self._best((origin, destination), request.depart_date, party, OUTBOUND_HOURS, wants)
        ]
        if request.return_date is not None:
            directions.append(
                self._best((destination, origin), request.return_date, party, RETURN_HOURS, wants)
            )
        there, *rest = await asyncio.gather(*directions)
        back: dict[int, LegQuote] = rest[0] if rest else {}
        offers = []
        for travel_class in (2, 1):
            legs = [there.get(travel_class)]
            if request.return_date is not None:
                legs.append(back.get(travel_class))
            found = [leg for leg in legs if leg is not None]
            if len(found) != len(legs):
                self.log.notes.append(f"no {travel_class}. class fare found for every leg")
                continue
            self.log.legs.extend(found)
            offers.append(self._offer(found, origin, destination, request))
        return offers

    async def _best(
        self,
        route: tuple[Station, Station],
        day: date,
        travellers: int,
        hours: range,
        preferences: TravelPreferences = NO_PREFERENCES,
    ) -> dict[int, LegQuote]:
        """The cheapest whole-party fare per class over the connections in the window."""
        origin, to = route
        connections = _in_window(
            await self.client.connections(origin.code, to.code, day), hours, preferences
        )
        sizes = split_group(travellers)
        # Every train priced concurrently, each distinct purchase size once (3 + 3 = one call).
        priced = await asyncio.gather(
            *(
                self.client.fares_by_size(connection, origin.code, to.code, sizes)
                for connection in connections
            )
        )
        best: dict[int, LegQuote] = {}
        for connection, by_size in zip(connections, priced, strict=True):
            per_size = [by_size[size] for size in sizes]
            for travel_class in (1, 2):
                picks = [_cheapest(fares, travel_class) for fares in per_size]
                chosen = [pick for pick in picks if pick is not None]
                if len(chosen) != len(picks):
                    continue
                quote = LegQuote(
                    direction="outbound" if hours is OUTBOUND_HOURS else "return",
                    connection=connection.label,
                    departs_at=connection.departs_at,
                    arrives_at=connection.arrives_at,
                    travel_class=travel_class,
                    offer_name=chosen[0].offer_name,
                    purchases=tuple(pick.total_minor for pick in chosen),
                    passengers=tuple(pick.passengers for pick in chosen),
                    from_code=origin.code,
                    to_code=to.code,
                    train_number=connection.legs[0].number,
                )
                current = best.get(travel_class)
                if current is None or quote.total_minor < current.total_minor:
                    best[travel_class] = quote
        return best

    def _offer(
        self,
        legs: list[LegQuote],
        origin: Station,
        destination: Station,
        request: SearchRequest,
    ) -> Offer:
        first = legs[0]
        trip = "return" if len(legs) > 1 else "one way"
        label = f"{first.travel_class}. class"
        title = (
            f"{CARRIER} {first.connection} {origin.name} -> {destination.name} ({label}, {trip})"
        )
        split = "+".join(str(n) for n in first.passengers)
        segments = tuple(
            Segment(
                carrier=CARRIER,
                number=leg.connection,
                origin=origin.name if leg.direction == "outbound" else destination.name,
                destination=destination.name if leg.direction == "outbound" else origin.name,
                departs_at=_local(leg.departs_at),
                arrives_at=_local(leg.arrives_at),
            )
            for leg in legs
        )
        details = " ".join(
            f"{leg.direction.capitalize()} {leg.departs_at:%Y-%m-%d %H:%M} {leg.connection}."
            for leg in legs
        )
        ref = ":".join(f"{leg.train_number}@{leg.departs_at:%Y%m%dT%H%M}" for leg in legs)
        return Offer(
            supplier_id=self.id,
            offer_ref=f"{self.id}:{ref}:c{first.travel_class}",
            title=title[:120],
            price_minor=sum(leg.total_minor for leg in legs),
            currency=request.currency,
            seller=CARRIER,
            segments=segments,
            refundable=False,
            purchase_url=self.purchase_site
            or results_url(
                first.departs_at.date(), first.from_code, first.to_code, f"{first.departs_at:%H:%M}"
            ),
            details=(
                f"{details} {first.offer_name}. Sold as {split} passengers per purchase "
                f"({CARRIER} sells at most {MAX_PASSENGERS_PER_PURCHASE} per transaction)."
            ),
            starts_at=_local(first.departs_at),
            links=_links(legs),
            provenance=Provenance(ProvenanceSource.LIVE, CARRIER, datetime.now(UTC)),
            supplier_data={
                "travel_class": first.travel_class,
                "refundable": False,
                "title": title[:120],
                "legs": [
                    {
                        "from_code": leg.from_code,
                        "to_code": leg.to_code,
                        "departs_at": leg.departs_at.isoformat(),
                        "train_number": leg.train_number,
                    }
                    for leg in legs
                ],
            },
        )

    # ---- quote and the rest -----------------------------------------------------------------

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        """Asks PKP again for exactly the trains of the offer. A transport failure (Akamai
        reset, timeout) raises `SupplierUnavailableError` — "could not ask", never sold out."""
        legs: list[dict[str, Any]] = list(offer.supplier_data.get("legs") or [])
        if not legs:
            return None
        travel_class = int(offer.supplier_data.get("travel_class", 2))
        refundable = bool(offer.supplier_data.get("refundable", False))
        try:
            total, valid_until = 0, None
            for leg in legs:
                departs_at = datetime.fromisoformat(str(leg["departs_at"]))
                from_code, to_code = int(leg["from_code"]), int(leg["to_code"])
                connections = await self.client.connections(from_code, to_code, departs_at.date())
                connection = next(
                    (
                        candidate
                        for candidate in connections
                        if candidate.legs[0].number == int(leg["train_number"])
                        and candidate.legs[0].departs_at == departs_at.replace(tzinfo=None)
                    ),
                    None,
                )
                if connection is None:
                    return None
                group = await self.client.group_quote(
                    connection,
                    from_code,
                    to_code,
                    party_size,
                    travel_class=travel_class,
                    refundable=refundable,
                )
                if group is None:
                    return None
                total += group.total_minor
                until = _local(group.valid_until)
                valid_until = until if valid_until is None else min(valid_until, until)
        except Exception as failure:
            logger.exception("PKP Intercity re-quote failed for %s", offer.offer_ref)
            raise SupplierUnavailableError(str(failure)) from failure
        return Quote(
            price_minor=total,
            currency="PLN",
            quoted_at=datetime.now(LOCAL),
            expires_at=valid_until,
        )

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        return None  # PKP Intercity has no holds

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        return Err("PKP Intercity is bought by the booking agent, not through an API")

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return None
