"""`sim_tickets` and `sim_sights`: the simulated attraction suppliers (`attraction_catalogue`).

- `sim_tickets` sells timed-entry tickets for ticketed sights. Channel `agent`: the booking
  agent buys them on our demo ticket shop (`/api/demo-supplier/tickets`, dev/test only) —
  pick the date, the entry slot and the number of tickets, enter the visitors, stop at the
  summary before paying. Without a demo base URL the offers point at an invalid host, like
  every other simulator.
- `sim_sights` proposes the free ones (bridges, squares, markets) as ideas: channel `manual`,
  nothing to buy.

Their offers are attraction candidates for the itinerary, never package items: they carry
`supplier_data["itinerary_only"] = True`, which the package research skips.
"""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.domain.result import Err, Result
from app.core.domain.suppliers import NAME_ONLY, SupplierCapabilities
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import BookingKind, SupplierChannel
from app.suppliers.attraction_catalogue import CatalogueAttraction, City, find_city
from app.suppliers.ports import (
    BookingRef,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
)

TICKETS = "sim_tickets"
SIGHTS = "sim_sights"
BASE_PATH = "/api/demo-supplier/tickets"
SIM_URL = "https://sim.tripsplit.invalid"
LOCAL = ZoneInfo("Europe/Warsaw")
SHOP_NAME = "CityPass Tickets (demo shop)"
MAX_TICKETS_PER_PURCHASE = 10

TICKETS_CAPABILITIES = SupplierCapabilities(
    kind=BookingKind.ACTIVITY,
    mode=None,
    channel=SupplierChannel.AGENT,
    max_party_per_purchase=MAX_TICKETS_PER_PURCHASE,
    quote_ttl=timedelta(hours=1),
    required_traveller_fields=NAME_ONLY,
)
SIGHTS_CAPABILITIES = SupplierCapabilities(
    kind=BookingKind.ACTIVITY,
    mode=None,
    channel=SupplierChannel.MANUAL,
    max_party_per_purchase=None,
    required_traveller_fields=frozenset(),
)


def supplier_data(
    attraction: CatalogueAttraction, rank: int, *, provenance: str, currency: str
) -> dict[str, Any]:
    return {
        "attraction": attraction.code,
        "title": attraction.title,
        "kind": attraction.kind.value,
        "lat": attraction.lat,
        "lon": attraction.lon,
        "opening_hours": f"{attraction.opens}-{attraction.closes}",
        "duration_minutes": attraction.minutes,
        "price_per_person_minor": attraction.price_pp_minor,
        "currency": currency,
        "website": attraction.website,
        "rank": rank,
        "bookable": attraction.ticketed,
        "provenance": provenance,
        "itinerary_only": True,
    }


class AttractionSupplier:
    """One of the two simulated attraction suppliers; `ticketed` picks which half of the
    catalogue it offers."""

    def __init__(
        self,
        supplier_id: str,
        *,
        site_url: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if supplier_id not in (TICKETS, SIGHTS):
            raise ValueError(f"unknown attraction supplier {supplier_id!r}")
        self.id = supplier_id
        self.clock = clock or (lambda: datetime.now(LOCAL))
        self.ticketed = supplier_id == TICKETS
        self.display_name = (
            "Attraction tickets (demo ticket shop)" if self.ticketed else "Sights (free ideas)"
        )
        self.capabilities = TICKETS_CAPABILITIES if self.ticketed else SIGHTS_CAPABILITIES
        base = site_url.rstrip("/") if site_url else f"{SIM_URL}/{TICKETS}"
        self.site_url = f"{base}{BASE_PATH}" if site_url else base

    async def search(self, request: SearchRequest) -> list[Offer]:
        city = find_city(request.destination)
        if city is None:
            return []
        return [
            self._offer(city, attraction, rank, request)
            for rank, attraction in enumerate(city.attractions)
            if attraction.ticketed == self.ticketed
        ]

    def _offer(
        self, city: City, attraction: CatalogueAttraction, rank: int, request: SearchRequest
    ) -> Offer:
        price = attraction.price_pp_minor * request.party_size
        provenance = "Demo ticket shop" if self.ticketed else "Simulated city guide"
        return Offer(
            supplier_id=self.id,
            offer_ref=f"{self.id}:{attraction.code}",
            title=attraction.title,
            price_minor=price,
            currency=request.currency,
            seller=SHOP_NAME if self.ticketed else "Free entry",
            purchase_url=(
                f"{self.site_url}?attraction={attraction.code}"
                if self.ticketed
                else attraction.website
            ),
            details=(
                f"{attraction.kind.value.title()} in {city.name}, open "
                f"{attraction.opens}-{attraction.closes}."
            ),
            starts_at=datetime.combine(request.depart_date, datetime.min.time(), tzinfo=LOCAL),
            supplier_data=supplier_data(
                attraction, rank, provenance=provenance, currency=request.currency
            ),
        )

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        per_person = offer.supplier_data.get("price_per_person_minor")
        if not isinstance(per_person, int) or per_person < 0:
            return None
        return Quote(
            price_minor=per_person * party_size,
            currency=str(offer.supplier_data.get("currency", "PLN")),
            quoted_at=self.clock(),
        )

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
        return Err("attraction tickets are bought by the booking agent on the ticket shop")

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        return None
