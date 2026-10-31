"""`demo_rail`: our own fake rail site (`app.services.demo_supplier`) as a supplier.

The live agent drives it in demos and in `trip-harness --live-agent`, so a real carrier is never
touched. It sells the three trains its pages list, one purchase carries at most five passengers
(like PKP Intercity), the price is the listed fare per person and leg and nothing can be held.
A return journey is one order on the site (both legs on one summary), so an offer's
`purchase_url` opens the search with the dates already filled in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.core.domain.result import Err, Result
from app.core.domain.suppliers import NAME_ONLY, SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import BookingKind, SupplierChannel, TransportMode
from app.core.domain.trust import Provenance, ProvenanceSource
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
    Segment,
)

SUPPLIER_ID = "demo_rail"
BASE_PATH = "/api/demo-supplier/rail"
MAX_PASSENGERS_PER_PURCHASE = 5
LOCAL = ZoneInfo("Europe/Warsaw")


@dataclass(frozen=True, slots=True)
class Train:
    code: str
    name: str
    departs: str
    arrives: str
    price_per_person_minor: int


TRAINS: tuple[Train, ...] = (
    Train("EC-111", "EC 111 Praha", "06:20", "14:05", 18_900),
    Train("EC-113", "EC 113 Vltava", "10:25", "18:10", 21_900),
    Train("EN-407", "EN 407 Chopin", "22:40", "07:05", 24_900),
)

CAPABILITIES = SupplierCapabilities(
    kind=BookingKind.TRANSPORT,
    mode=TransportMode.RAIL,
    channel=SupplierChannel.AGENT,
    max_party_per_purchase=MAX_PASSENGERS_PER_PURCHASE,
    quote_ttl=timedelta(hours=1),
    required_traveller_fields=NAME_ONLY,
)


def _at(day: date, clock: str, *, overnight_from: str | None = None) -> datetime:
    moment = datetime.combine(day, time.fromisoformat(clock), tzinfo=LOCAL)
    if overnight_from is not None and clock < overnight_from:
        moment += timedelta(days=1)
    return moment


def purchase_url(
    site_url: str,
    *,
    origin: str,
    destination: str,
    depart: date,
    back: date | None,
    fare_minor: int | None = None,
) -> str:
    """The site's search page for this journey: a return is bought as ONE order. `fare_minor`
    (per person, whole journey) makes the site charge that instead of its list price."""
    params = {"from": origin, "to": destination, "date": depart.isoformat()}
    if back is not None:
        params["return"] = back.isoformat()
    if fare_minor is not None:
        params["fare"] = str(fare_minor)
    return f"{site_url}?{urlencode(params)}"


class DemoRailSupplier:
    id = SUPPLIER_ID
    display_name = "Demo rail (local fake site)"

    def __init__(self, base_url: str) -> None:
        self.capabilities = CAPABILITIES
        self.site_url = f"{base_url.rstrip('/')}{BASE_PATH}"

    async def search(self, request: SearchRequest) -> list[Offer]:
        if request.mode not in (None, TransportMode.RAIL):
            return []
        days = [request.depart_date]
        if request.return_date is not None:
            days.append(request.return_date)
        offers = []
        for train in TRAINS:
            segments = tuple(
                Segment(
                    carrier="Demo rail",
                    number=train.name,
                    origin=request.origin if index == 0 else request.destination,
                    destination=request.destination if index == 0 else request.origin,
                    departs_at=_at(day, train.departs),
                    arrives_at=_at(day, train.arrives, overnight_from=train.departs),
                )
                for index, day in enumerate(days)
            )
            per_person = train.price_per_person_minor * len(days)
            trip = "return" if len(days) > 1 else "one way"
            offers.append(
                Offer(
                    supplier_id=self.id,
                    offer_ref=f"{self.id}:{train.code}:{len(days)}",
                    title=f"{train.name} · {request.origin} → {request.destination} · {trip}",
                    price_minor=per_person * request.party_size,
                    currency="PLN",
                    seller="Demo rail",
                    segments=segments,
                    purchase_url=purchase_url(
                        self.site_url,
                        origin=request.origin,
                        destination=request.destination,
                        depart=request.depart_date,
                        back=request.return_date,
                    ),
                    details=" ".join(segment.describe() + "." for segment in segments),
                    starts_at=segments[0].departs_at,
                    supplier_data={"price_per_person_minor": per_person, "train": train.code},
                    provenance=Provenance(
                        ProvenanceSource.EXAMPLE, "Demo rail", datetime.now(LOCAL)
                    ),
                )
            )
        return offers

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        per_person = int(offer.supplier_data.get("price_per_person_minor", 0))
        if per_person <= 0:
            return None
        now = datetime.now(LOCAL)
        return Quote(price_minor=per_person * party_size, currency="PLN", quoted_at=now)

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        return None

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        return Err("the demo rail site is bought by the booking agent")

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return None
