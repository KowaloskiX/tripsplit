"""`liteapi`: real hotels through LiteAPI (Nuitee Connect) behind the supplier port.

| port method | LiteAPI                                                                   |
|-------------|---------------------------------------------------------------------------|
| `search`    | `GET /data/hotels` (city) -> `POST /hotels/rates` (party, dates, PLN)     |
| `quote`     | `POST /hotels/rates` for the one hotel, matched to the same room and rate |
| `hold`      | `POST /rates/prebook` -> `prebookId` (the price is locked)                |
| `purchase`  | `POST /rates/book` with the prebook, the lead guest per room, payment     |
| `status`    | `GET /bookings/{id}` -> a cancellation notice                             |

One booking carries the whole party: the rooms are LiteAPI "occupancies" (`occupancies_for`:
pairs of adults, an odd party puts three in one room), and an offer's price is the sum of one
rate per room. An `offerId` belongs to a search session and goes stale, so `supplier_data`
keeps what identifies the room for good (hotel id, room type id, board, refund tag, rate
names) and a hold or quote re-runs the rates and matches it again when needed.

Only the SANDBOX is used unless `LITEAPI_ALLOW_LIVE=true` (`check_key`): there the booking pays
with LiteAPI's hidden test card (`ACC_CREDIT_CARD`), so no money moves. Guest names go to
LiteAPI and nowhere else: never into logs, the harness report or a failure reason.
"""

import asyncio
import hashlib
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import SecretStr

from app.core.domain.places import resolve_city
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import NAME_ONLY, SupplierCapabilities
from app.core.domain.travellers import TravellerDetails, has_full_name, split_name
from app.core.domain.trips import BookingKind, SupplierChannel
from app.suppliers.liteapi_client import Json, LiteApiClient, LiteApiFailure
from app.suppliers.ports import (
    BookingRef,
    DisruptionKind,
    DisruptionNotice,
    Hold,
    Offer,
    OfferRef,
    Quote,
    SearchRequest,
)

logger = logging.getLogger(__name__)

SUPPLIER_ID = "liteapi"
DISPLAY_NAME = "LiteAPI hotels"
type Clock = Callable[[], datetime]

# LiteAPI documents no prebook lifetime for hotels; its booking guides keep a checkout session
# for ~15 minutes. Conservative: after that the trip flow prebooks again before buying.
HOLD_TTL = timedelta(minutes=15)
QUOTE_TTL = timedelta(minutes=10)
MAX_HOTELS = 40
# Rates per hotel in the city search (cheapest first): enough to find a refundable one.
MAX_RATES_PER_HOTEL = 15
MAX_OFFERS = 6
SPARE_PICKS = 2
# Equivalent offers tried when the chosen one cannot be prebooked any more.
PREBOOK_ATTEMPTS = 3
CENTRAL_KM = 1.5
# The radius of the hotel search around a city centre when the city name finds nothing.
NEAR_CENTRE_M = 5_000
GOOD_RATING = 8.0
GUEST_NATIONALITY = "PL"
REFUNDABLE = "RFN"
CANCELLED = frozenset({"CANCELLED", "CANCELED"})
# LiteAPI 4002 = "required request field is missing or wrong input": a stale offerId or an
# unknown/expired prebookId (the description says which).
STALE_INPUT = 4002

CAPABILITIES = SupplierCapabilities(
    kind=BookingKind.STAY,
    mode=None,
    channel=SupplierChannel.API,
    max_party_per_purchase=None,  # the rooms are allocated inside one booking
    supports_hold=True,
    hold_ttl=HOLD_TTL,
    quote_ttl=QUOTE_TTL,
    required_traveller_fields=NAME_ONLY,
    refund_policy_known=True,
    reports_disruptions=True,  # one cheap GET per confirmed stay
)


@dataclass(frozen=True, slots=True)
class City:
    country_code: str
    name: str  # as LiteAPI's hotel content names it
    latitude: float
    longitude: float  # the centre, for "km from the centre"


CONTACT_EMAIL = "trips@tripsplit.example"
CONTACT_PHONE = "+48500100200"


@dataclass(frozen=True, slots=True)
class LiteApiConfig:
    api_key: SecretStr
    allow_live: bool = False
    # Sent as the holder's and every room's contact (TripSplit keeps no per-guest e-mail).
    contact_email: str = CONTACT_EMAIL
    contact_phone: str = CONTACT_PHONE


# ---- pure helpers -----------------------------------------------------------------------------


def find_city(name: str) -> City | None:
    """The hotel search's view of a catalogue city (`resolve_city`): any city the catalogue
    knows, in any form people type ("Sztokholmu", "Praha")."""
    city = resolve_city(name)
    if city is None:
        return None
    return City(city.country_code, city.name, city.latitude, city.longitude)


def occupancies_for(party_size: int) -> tuple[int, ...]:
    """Adults per room: pairs; an odd party puts three in one room (one guest alone gets a
    single). 6 -> (2, 2, 2), 5 -> (2, 3), 1 -> (1,)."""
    if party_size <= 0:
        return ()
    if party_size == 1:
        return (1,)
    rooms = [2] * (party_size // 2)
    if party_size % 2:
        rooms[-1] = 3
    return tuple(rooms)


def rooms_of(travellers: Sequence[TravellerDetails]) -> list[list[TravellerDetails]]:
    """The travellers per room, in order (the first of each room is its lead guest)."""
    rooms: list[list[TravellerDetails]] = []
    start = 0
    for adults in occupancies_for(len(travellers)):
        rooms.append(list(travellers[start : start + adults]))
        start += adults
    return rooms


def to_minor(amount: Any) -> int | None:
    """1698.66 -> 169866 (half up); None when it is not a number."""
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


@dataclass(frozen=True, slots=True)
class Hotel:
    id: str
    name: str
    stars: float | None = None
    rating: float | None = None
    review_count: int = 0
    km_from_centre: float | None = None


@dataclass(frozen=True, slots=True)
class RoomOffer:
    """One LiteAPI room-type offer: one rate per room, priced for all of them together."""

    hotel_id: str
    offer_id: str
    room_type_id: str
    price_minor: int
    currency: str
    rate_names: tuple[str, ...]
    board_type: str
    board_name: str
    refundable: bool
    excluded_fees_minor: int = 0  # e.g. city tax, paid at the hotel

    @property
    def identity(self) -> tuple[str, str, bool]:
        return (self.room_type_id, self.board_type, self.refundable)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def parse_hotels(data: Any, city: City | None) -> dict[str, Hotel]:
    hotels: dict[str, Hotel] = {}
    for raw in data if isinstance(data, list) else []:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("name"):
            continue
        lat, lon = _number(raw.get("latitude")), _number(raw.get("longitude"))
        km = (
            round(km_between(city.latitude, city.longitude, lat, lon), 1)
            if city is not None and lat is not None and lon is not None
            else None
        )
        reviews = raw.get("reviewCount")
        hotels[str(raw["id"])] = Hotel(
            id=str(raw["id"]),
            name=str(raw["name"]).strip(),
            stars=_number(raw.get("stars")) or None,
            rating=_number(raw.get("rating")) or None,
            review_count=reviews if isinstance(reviews, int) else 0,
            km_from_centre=km,
        )
    return hotels


def _room_offer(hotel_id: str, raw: Mapping[str, Any], currency: str) -> RoomOffer | None:
    total = raw.get("offerRetailRate")
    rates = raw.get("rates")
    if not isinstance(total, dict) or not isinstance(rates, list) or not rates:
        return None
    if total.get("currency") != currency or not raw.get("offerId"):
        return None
    price = to_minor(total.get("amount"))
    if price is None or price <= 0:
        return None
    ordered = sorted(
        (rate for rate in rates if isinstance(rate, dict)),
        key=lambda rate: rate.get("occupancyNumber") or 0,
    )
    excluded = 0
    for rate in ordered:
        for fee in (rate.get("retailRate") or {}).get("taxesAndFees") or []:
            if isinstance(fee, dict) and fee.get("included") is False:
                excluded += to_minor(fee.get("amount")) or 0
    tags = {(rate.get("cancellationPolicies") or {}).get("refundableTag") for rate in ordered}
    first = ordered[0]
    return RoomOffer(
        hotel_id=hotel_id,
        offer_id=str(raw["offerId"]),
        room_type_id=str(raw.get("roomTypeId") or ""),
        price_minor=price,
        currency=currency,
        rate_names=tuple(str(rate.get("name") or "Room").strip() for rate in ordered),
        board_type=str(first.get("boardType") or ""),
        board_name=str(first.get("boardName") or ""),
        refundable=tags == {REFUNDABLE},
        excluded_fees_minor=excluded,
    )


def parse_rates(data: Any, currency: str) -> dict[str, list[RoomOffer]]:
    """hotel id -> its offers, cheapest first (offers in another currency are skipped)."""
    found: dict[str, list[RoomOffer]] = {}
    for hotel in data if isinstance(data, list) else []:
        if not isinstance(hotel, dict) or not hotel.get("hotelId"):
            continue
        hotel_id = str(hotel["hotelId"])
        offers = [
            offer
            for raw in hotel.get("roomTypes") or []
            if isinstance(raw, dict) and (offer := _room_offer(hotel_id, raw, currency))
        ]
        if offers:
            found[hotel_id] = sorted(offers, key=lambda offer: offer.price_minor)
    return found


@dataclass(frozen=True, slots=True)
class Pick:
    hotel: Hotel
    offer: RoomOffer
    why: str  # "cheapest", "best value", "free cancellation", "central premium", ...


def select_offers(
    hotels: Mapping[str, Hotel], rates: Mapping[str, list[RoomOffer]], limit: int = MAX_OFFERS
) -> list[Pick]:
    """At most `limit` hotels, one offer each: the cheapest, the next cheapest, the best value
    (best rated at or under the median price), the cheapest free-cancellation one (well rated
    if possible) and a central premium one (most stars, then rating, near the centre); the
    rest are filled by price."""
    candidates = [hotel_id for hotel_id in rates if hotel_id in hotels and rates[hotel_id]]
    if not candidates:
        return []

    def cheapest(hotel_id: str) -> RoomOffer:
        return rates[hotel_id][0]

    by_price = sorted(candidates, key=lambda h: (cheapest(h).price_minor, h))
    picks: list[Pick] = []

    def add(hotel_id: str | None, offer: RoomOffer | None, why: str) -> None:
        if hotel_id is None or offer is None or len(picks) >= limit:
            return
        if any(pick.hotel.id == hotel_id for pick in picks):
            return
        picks.append(Pick(hotels[hotel_id], offer, why))

    add(by_price[0], cheapest(by_price[0]), "cheapest")
    if len(by_price) > 1:
        add(by_price[1], cheapest(by_price[1]), "a step up")
    median = cheapest(by_price[len(by_price) // 2]).price_minor
    affordable = [h for h in candidates if cheapest(h).price_minor <= median]
    value = max(
        affordable,
        key=lambda h: (hotels[h].rating or 0.0, hotels[h].stars or 0.0, -cheapest(h).price_minor),
        default=None,
    )
    add(value, cheapest(value) if value else None, "best value")
    refundable = [(offer, h) for h in candidates for offer in rates[h] if offer.refundable]
    well_rated = [(o, h) for o, h in refundable if (hotels[h].rating or 0.0) >= GOOD_RATING]
    unpicked = [
        (o, h) for o, h in (well_rated or refundable) if all(p.hotel.id != h for p in picks)
    ]
    if unpicked:
        offer, hotel_id = min(unpicked, key=lambda pair: (pair[0].price_minor, pair[1]))
        add(hotel_id, offer, "free cancellation")
    central = [
        h
        for h in candidates
        if hotels[h].km_from_centre is not None and (hotels[h].km_from_centre or 0) <= CENTRAL_KM
    ]
    premium = max(
        central or candidates,
        key=lambda h: (hotels[h].stars or 0.0, hotels[h].rating or 0.0, cheapest(h).price_minor),
    )
    add(premium, cheapest(premium), "central premium" if central else "premium")
    for hotel_id in by_price:
        add(hotel_id, cheapest(hotel_id), "by price")
    return picks


def matching_offers(original: Mapping[str, Any], offers: Sequence[RoomOffer]) -> list[RoomOffer]:
    """The same room again in a fresh rates answer, best match first: same room type, board
    and refund terms (preferring the same rate names, then the cheaper); if there is none, the
    same rate names, board and terms. Empty = no longer offered."""
    room_type = str(original.get("room_type_id") or "")
    board = str(original.get("board_type") or "")
    refundable = original.get("refundable_tag") == REFUNDABLE
    names = tuple(str(name) for name in original.get("rate_names") or ())
    same = [o for o in offers if room_type and o.identity == (room_type, board, refundable)]
    if same:
        return sorted(same, key=lambda o: (o.rate_names != names, o.price_minor))
    alike = [
        o
        for o in offers
        if set(o.rate_names) == set(names) and o.board_type == board and o.refundable == refundable
    ]
    return sorted(alike, key=lambda o: o.price_minor)


def match_offer(original: Mapping[str, Any], offers: Sequence[RoomOffer]) -> RoomOffer | None:
    found = matching_offers(original, offers)
    return found[0] if found else None


def rates_request(
    hotel_ids: Sequence[str],
    checkin: date | str,
    checkout: date | str,
    party_size: int,
    currency: str,
    max_rates: int | None,
) -> Json:
    body: Json = {
        "hotelIds": list(hotel_ids),
        "checkin": str(checkin),
        "checkout": str(checkout),
        "currency": currency,
        "guestNationality": GUEST_NATIONALITY,
        "occupancies": [{"adults": adults} for adults in occupancies_for(party_size)],
    }
    if max_rates is not None:
        body["maxRatesPerHotel"] = max_rates
    return body


def book_request(
    prebook_id: str,
    travellers: Sequence[TravellerDetails],
    contact_email: str,
    contact_phone: str,
) -> Json:
    """The holder is the first traveller; each room's lead guest is the first of its room."""
    first, last = split_name(travellers[0].full_name)
    guests = []
    for number, room in enumerate(rooms_of(travellers), start=1):
        guest_first, guest_last = split_name(room[0].full_name)
        guests.append(
            {
                "occupancyNumber": number,
                "firstName": guest_first,
                "lastName": guest_last,
                "email": contact_email,
            }
        )
    return {
        "prebookId": prebook_id,
        "clientReference": f"tripsplit-{prebook_id}",
        "holder": {
            "firstName": first,
            "lastName": last,
            "email": contact_email,
            "phone": contact_phone,
        },
        "guests": guests,
        # Sandbox: LiteAPI's hidden test card — a simulated booking, nothing is charged.
        "payment": {"method": "ACC_CREDIT_CARD"},
    }


def mask_names(text: str, travellers: Sequence[TravellerDetails]) -> str:
    """Every traveller's name part replaced by `***` — a supplier may echo them back."""
    for traveller in travellers:
        for part in traveller.full_name.split():
            if len(part) > 1:
                text = text.replace(part, "***")
    return text


def _rooms_label(names: Sequence[str]) -> str:
    """("Superior Room",) * 3 -> "3x Superior Room"; mixed -> "2x Twin + 1x Triple"."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return " + ".join(f"{count}x {name}" for name, count in counts.items())


def _money(minor: int, currency: str) -> str:
    return f"{minor / 100:,.2f} {currency}".replace(",", " ")


def offer_of(pick: Pick, request: SearchRequest, now: datetime) -> Offer:
    hotel, room = pick.hotel, pick.offer
    checkout = request.return_date or request.depart_date + timedelta(days=1)
    nights = max((checkout - request.depart_date).days, 1)
    stars = f"{hotel.stars:g}-star" if hotel.stars else "unrated"
    facts = [stars]
    if hotel.rating:
        facts.append(f"rated {hotel.rating:g}/10 ({hotel.review_count} reviews)")
    if hotel.km_from_centre is not None:
        facts.append(f"{hotel.km_from_centre:g} km from the centre")
    terms = "Free cancellation" if room.refundable else "Non-refundable"
    details = (
        f"{nights} night(s) for {request.party_size} guests in {len(room.rate_names)} room(s): "
        f"{_rooms_label(room.rate_names)}. {room.board_name or room.board_type}. {terms}. "
        f"{', '.join(facts).capitalize()}. Picked as: {pick.why}."
    )
    if room.excluded_fees_minor:
        details += f" Paid at the hotel: {_money(room.excluded_fees_minor, room.currency)}."
    fingerprint = hashlib.sha1(
        f"{room.room_type_id}|{room.board_type}|{room.refundable}|{room.rate_names}".encode(),
        usedforsecurity=False,
    ).hexdigest()[:12]
    title = f"{hotel.name} — {_rooms_label(room.rate_names)}"[:120]
    return Offer(
        supplier_id=SUPPLIER_ID,
        offer_ref=f"{SUPPLIER_ID}:{hotel.id}:{request.depart_date}:{checkout}:{fingerprint}",
        title=title,
        price_minor=room.price_minor,
        currency=room.currency,
        seller=hotel.name,
        refundable=room.refundable,
        expires_at=now + QUOTE_TTL,
        details=details,
        supplier_data={
            "hotel_id": hotel.id,
            "hotel_name": hotel.name,
            "offer_id": room.offer_id,
            "room_type_id": room.room_type_id,
            "occupancies": list(occupancies_for(request.party_size)),
            "currency": room.currency,
            "rate_names": list(room.rate_names),
            "board_type": room.board_type,
            "refundable_tag": REFUNDABLE if room.refundable else "NRFN",
            "checkin": str(request.depart_date),
            "checkout": str(checkout),
            "title": title,
            # For a value score in the research (stable names; None = unknown).
            "stars": hotel.stars,
            "rating": hotel.rating,
            "review_count": hotel.review_count,
            "km_from_centre": hotel.km_from_centre,
            "why": pick.why,
        },
    )


# ---- the adapter ------------------------------------------------------------------------------


@dataclass
class LiteApiLog:
    """What the real supplier did — for harness reports. No guest data."""

    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Prebooked:
    prebook_id: str
    price_minor: int


class LiteApiSupplier:
    id = SUPPLIER_ID
    display_name = DISPLAY_NAME

    def __init__(
        self,
        client: LiteApiClient,
        config: LiteApiConfig,
        clock: Clock,
        *,
        verify_availability: bool = True,
    ) -> None:
        self.capabilities = CAPABILITIES
        self.verify_availability = verify_availability
        self.client = client
        self.config = config
        self.clock = clock
        self.log = LiteApiLog()

    # ---- search -------------------------------------------------------------------------

    async def search(self, request: SearchRequest) -> list[Offer]:
        """The city's hotels, their rates for the party, a handful of distinct picks. A
        failed search means "no stays from LiteAPI" — never a crashed research."""
        city = find_city(request.destination)
        if city is None or request.party_size <= 0:
            return []
        try:
            return await self._search(request, city)
        except Exception:
            logger.exception("LiteAPI search failed")
            self.log.notes.append("the LiteAPI search failed")
            return []

    async def _search(self, request: SearchRequest, city: City) -> list[Offer]:
        found = await self.client.hotels(city.country_code, city.name, MAX_HOTELS)
        if isinstance(found, Err):
            self.log.notes.append(f"hotel list: {found.error.describe()}")
            return []
        hotels = parse_hotels(found.value, city)
        if not hotels:
            # LiteAPI names some cities differently (München, Malmö): ask around the centre.
            near = await self.client.hotels_near(
                city.latitude, city.longitude, NEAR_CENTRE_M, MAX_HOTELS
            )
            hotels = parse_hotels(near.value, city) if isinstance(near, Ok) else {}
        if not hotels:
            return []
        checkout = request.return_date or request.depart_date + timedelta(days=1)
        body = rates_request(
            list(hotels),
            request.depart_date,
            checkout,
            request.party_size,
            request.currency,
            MAX_RATES_PER_HOTEL,
        )
        answered = await self.client.rates(body)
        if isinstance(answered, Err):
            self.log.notes.append(f"rates: {answered.error.describe()}")
            return []
        rates = parse_rates(answered.value, request.currency)
        self.log.notes.append(
            f"{city.name}: {len(hotels)} hotels, {len(rates)} with rates for "
            f"{request.party_size} in {len(occupancies_for(request.party_size))} rooms"
        )
        if self.verify_availability:
            # A few spares: some rates cannot be prebooked, the package needs ones that can.
            picks = await self._bookable(select_offers(hotels, rates, MAX_OFFERS + SPARE_PICKS))
        else:
            picks = select_offers(hotels, rates)
        picks = picks[:MAX_OFFERS]
        now = self.clock()
        self.log.notes.extend(
            f"pick ({pick.why}): {pick.hotel.name} — {_rooms_label(pick.offer.rate_names)}, "
            f"{_money(pick.offer.price_minor, pick.offer.currency)}"
            for pick in picks
        )
        return [offer_of(pick, request, now) for pick in picks]

    async def _bookable(self, picks: list[Pick]) -> list[Pick]:
        """Only the picks LiteAPI can actually prebook right now (its documented live
        availability check; a prebook spends nothing). Many sandbox rates answer "no prebook
        availability" — a package should not be built on one of those."""
        checks = await asyncio.gather(
            *(self._prebook_offer(pick.offer.offer_id) for pick in picks),
            return_exceptions=True,
        )
        kept = []
        for pick, check in zip(picks, checks, strict=True):
            if isinstance(check, _Prebooked):
                kept.append(pick)
            else:
                self.log.notes.append(f"dropped {pick.hotel.name}: cannot be prebooked now")
        return kept

    # ---- quote / hold -------------------------------------------------------------------

    async def _fresh(self, offer: OfferRef, party_size: int) -> list[RoomOffer]:
        """The same room in a fresh rates answer for `party_size`, best match first (raises
        when LiteAPI is unreachable)."""
        data = offer.supplier_data
        currency = str(data.get("currency") or "PLN")
        body = rates_request(
            [str(data.get("hotel_id") or "")],
            str(data.get("checkin") or ""),
            str(data.get("checkout") or ""),
            party_size,
            currency,
            None,
        )
        answered = await self.client.rates(body)
        if isinstance(answered, Err):
            return []
        offers = parse_rates(answered.value, currency).get(str(data.get("hotel_id")), [])
        return matching_offers(data, offers)

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        found = await self._fresh(offer, party_size)
        if not found:
            return None
        fresh = found[0]
        now = self.clock()
        return Quote(
            price_minor=fresh.price_minor,
            currency=fresh.currency,
            quoted_at=now,
            expires_at=now + QUOTE_TTL,
        )

    async def _prebook(self, offer: OfferRef, party_size: int) -> _Prebooked | None:
        """Prebooks the stored offer when it is for this party. A stale or unavailable offerId
        (or another party size) is matched again in a fresh search, and up to
        `PREBOOK_ATTEMPTS` equivalent offers are tried — a supplier rate that cannot be
        prebooked is common, the same room from another rate often can."""
        data = offer.supplier_data
        stored = tuple(int(n) for n in data.get("occupancies") or ())
        offer_id = str(data.get("offer_id") or "")
        if offer_id and stored == occupancies_for(party_size):
            prebooked = await self._prebook_offer(offer_id)
            if prebooked is not None:
                return prebooked
        candidates = [o for o in await self._fresh(offer, party_size) if o.offer_id != offer_id]
        for candidate in candidates[:PREBOOK_ATTEMPTS]:
            prebooked = await self._prebook_offer(candidate.offer_id)
            if prebooked is not None:
                return prebooked
        return None

    async def _prebook_offer(self, offer_id: str) -> _Prebooked | None:
        answered = await self.client.prebook(offer_id)
        if isinstance(answered, Err) or not isinstance(answered.value, dict):
            return None
        data = answered.value
        price = to_minor(data.get("price"))
        if not data.get("prebookId") or price is None:
            return None
        return _Prebooked(str(data["prebookId"]), price)

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        party = len(travellers) or len(offer.supplier_data.get("occupancies") or ())
        prebooked = await self._prebook(offer, party)
        if prebooked is None:
            self.log.notes.append(f"prebook failed for {_hotel(offer)}")
            return None
        self.log.notes.append(
            f"prebook {prebooked.prebook_id}: {_hotel(offer)} at "
            f"{_money(prebooked.price_minor, str(offer.supplier_data.get('currency', 'PLN')))}"
        )
        return Hold(
            ref=prebooked.prebook_id,
            expires_at=self.clock() + HOLD_TTL,
            price_minor=prebooked.price_minor,
        )

    # ---- purchase -----------------------------------------------------------------------

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        """Books on the prebook (`hold_ref`). Without one (HOLDS=off, the default) the offer
        is prebooked right here, at the approval, and booked on that prebook; an expired
        prebook is replaced the same way. Either only at an unchanged price: a moved price is
        refused, so the trip flow re-quotes and re-splits before anything is paid."""
        if not travellers:
            return Err("no travellers to book the stay for")
        if not all(has_full_name(t.full_name) for t in travellers):
            return Err("every guest needs a first and a last name")
        try:
            return await self._purchase(offer, travellers, price_minor, hold_ref)
        except Exception as exc:  # the boundary: a purchase answers Ok/Err, never raises
            logger.warning("LiteAPI booking failed: %s", type(exc).__name__)
            return Err(
                "LiteAPI could not be reached while booking; the booking carries a client "
                "reference, so a retry cannot book twice — check the stay before retrying"
            )

    async def _purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        currency = str(offer.supplier_data.get("currency") or "PLN")
        prebook_id = hold_ref
        if prebook_id is not None:
            booked = await self._book(prebook_id, travellers)
            if not _prebook_gone(booked):
                return self._booked(booked, offer, travellers)
            self.log.notes.append(f"prebook {prebook_id} expired — prebooking again")
        prebooked = await self._prebook(offer, len(travellers))
        if prebooked is None:
            return Err(f"{_hotel(offer)} no longer offers this room")
        if prebooked.price_minor != price_minor:
            return Err(
                f"{_hotel(offer)} now asks {_money(prebooked.price_minor, currency)} instead "
                f"of {_money(price_minor, currency)} — start the purchase again to re-quote"
            )
        placed = "re-placed" if hold_ref is not None else "placed at the approval"
        self.log.notes.append(f"prebook {prebooked.prebook_id}: {placed}, same price")
        booked = await self._book(prebooked.prebook_id, travellers)
        return self._booked(booked, offer, travellers)

    async def _book(
        self, prebook_id: str, travellers: Sequence[TravellerDetails]
    ) -> Result[Any, LiteApiFailure]:
        body = book_request(
            prebook_id, travellers, self.config.contact_email, self.config.contact_phone
        )
        return await self.client.book(body)

    def _booked(
        self,
        booked: Result[Any, LiteApiFailure],
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
    ) -> Result[str, str]:
        if isinstance(booked, Err):
            reason = mask_names(booked.error.describe(), travellers)
            return Err(f"LiteAPI refused the booking: {reason}")
        data = booked.value if isinstance(booked.value, dict) else {}
        booking_id = data.get("bookingId")
        status = str(data.get("status") or "")
        if not booking_id or status != "CONFIRMED":
            return Err(f"LiteAPI did not confirm the booking (status {status or 'missing'})")
        self.log.notes.append(
            f"booking {booking_id}: {status} at {_hotel(offer)}, "
            f"{_money(to_minor(data.get('price')) or 0, str(data.get('currency') or ''))}, "
            f"sandbox={data.get('sandbox')}"
        )
        return Ok(str(booking_id))

    # ---- status -------------------------------------------------------------------------

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        """A stay cancelled at LiteAPI (by the hotel or support) is a CANCELLATION; nothing is
        offered in its place — the group picks another stay."""
        if not booking.confirmation_ref:
            return None
        try:
            answered = await self.client.booking(booking.confirmation_ref)
        except Exception:
            logger.warning("LiteAPI booking status could not be read")
            return None
        if isinstance(answered, Err) or not isinstance(answered.value, dict):
            return None
        if str(answered.value.get("status") or "").upper() not in CANCELLED:
            return None
        return DisruptionNotice(
            kind=DisruptionKind.CANCELLATION,
            message=f"{_hotel(booking.offer)} cancelled the stay (LiteAPI booking "
            f"{booking.confirmation_ref}).",
        )


def _hotel(offer: OfferRef) -> str:
    return str(offer.supplier_data.get("hotel_name") or "the hotel")


def _prebook_gone(booked: Result[Any, LiteApiFailure]) -> bool:
    """The book call was refused because the prebook no longer exists (expired/unknown)."""
    if not isinstance(booked, Err):
        return False
    failure = booked.error
    return failure.status == 404 or (
        failure.code == STALE_INPUT and "prebook" in failure.description.casefold()
    )


def liteapi_supplier(config: LiteApiConfig, clock: Clock) -> LiteApiSupplier:
    client = LiteApiClient(config.api_key, allow_live=config.allow_live)
    return LiteApiSupplier(client, config, clock)
