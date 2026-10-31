"""`duffel`: real flights through the Duffel Flights API — in TEST mode unless explicitly not.

- `search`: `POST /air/offer_requests?return_offers=true` — the best few holdable offers.
- `quote`: `GET /air/offers/{id}`; an expired offer (or another party size) is re-found.
- `hold`: `POST /air/orders` with `type: "hold"` and the travellers — a named booking.
- `purchase`: `GET /air/orders/{id}` + `POST /air/payments` (balance) on the held order;
  without a hold, `POST /air/orders` with `type: "instant"` and the payment.
- `status`: `GET /air/airline_initiated_changes?order_id=` -> a delay or cancellation.

**Offers expire after ~30 minutes**, a group votes for longer. `supplier_data` keeps the
search (slices, party) and the itinerary (flight numbers + departure times), so an expired
offer — or a purchase for a different party size — is found again with a fresh search and the
same flights; the new offer id lives only as long as the call needs it (the hold's order id is
what the purchase pays).

**Money.** Duffel prices and charges in the account's currency (EUR for ours). Trips are in PLN,
so prices are converted with a configured rate (`DUFFEL_FX_EUR_PLN`, default 4.30) for the
group; the original amount and currency stay in `supplier_data` and in the offer details, and
Duffel is always paid its own amount in its own currency. A purchase never pays more than the
approved PLN amount: a dearer order is refused and the price-change path re-splits the shares.

**Travellers.** An airline order names every passenger: given and family name, birth date,
gender (Duffel requires it and derives nothing; the title is derived from it), e-mail and phone.
TripSplit keeps no per-passenger contact, so the configured agency contact
(`DUFFEL_CONTACT_EMAIL` / `DUFFEL_CONTACT_PHONE`) is sent for everyone. Passports go only when
the offer says `passenger_identity_documents_required`, but are required up front for every
flight (like the simulated airline) because whether a route needs them is only known per offer.
Every passenger is booked as an adult. Names are sent in ASCII (airline PNRs are ASCII). No
traveller value is ever logged; Duffel's error messages (which may echo one) are dropped in
favour of codes and field names.
"""

import logging
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr

from app.core.domain.bookings import format_money
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import SupplierCapabilities, TravellerField
from app.core.domain.travellers import Gender, TravellerDetails, split_name
from app.core.domain.trips import BookingKind, SupplierChannel, TransportMode, TravelPreferences
from app.core.domain.trust import (
    LinkKind,
    OfferLink,
    Provenance,
    ProvenanceSource,
    flight_status_url,
    google_flights_url,
)
from app.suppliers.airports import airport_code
from app.suppliers.duffel_client import SEARCH_TIMEOUT_S, DuffelClient, DuffelFailure
from app.suppliers.ports import (
    BookingRef,
    DisruptionKind,
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

SUPPLIER_ID = "duffel"
DASHBOARD_URL = "https://app.duffel.com"
# "Airlines limit the number of passengers in a single order to <= 9" (Duffel, Create an order).
MAX_PASSENGERS_PER_ORDER = 9
OFFER_TTL = timedelta(minutes=30)
# Declared for the capability; every real hold carries its own expiry (see `_hold_expiry`).
NOMINAL_HOLD_TTL = timedelta(hours=24)
SEARCH_PARAMS = {"return_offers": "true", "supplier_timeout": "20000"}
DEFAULT_FX_EUR_PLN = Decimal("4.30")
DEFAULT_CONTACT_EMAIL = "trips@tripsplit.example"
DEFAULT_CONTACT_PHONE = "+48500100200"
# Offer gone / no longer holdable: "sold out" for the trip flow, not "could not ask".
PRICE_CHANGED_CODE = "price_changed"
# A hold order refused for the offer's airline although the offer advertises
# `requires_instant_payment: false`: that airline does not hold through Duffel.
HOLD_REFUSED_CODE = "invalid_order_create_type"
# Seen on Duffel's TEST API: these airlines' offers advertise holds but every hold order is
# refused with `HOLD_REFUSED_CODE`. Any other airline that refuses is learned at runtime.
TEST_MODE_HOLD_REFUSERS = frozenset({"Iberia"})
# How many matching offers of a fresh search are read in full before giving up.
_REFIND_CHECKS = 3
_GONE_CODES = frozenset(
    {"offer_no_longer_available", "offer_expired", "not_valid_with_selected_offer", "not_found"}
)

REQUIRED_TRAVELLER_FIELDS: frozenset[TravellerField] = frozenset(
    {
        TravellerField.FULL_NAME,
        TravellerField.DATE_OF_BIRTH,
        TravellerField.GENDER,
        TravellerField.NATIONALITY,
        TravellerField.DOCUMENT_NUMBER,
        TravellerField.DOCUMENT_EXPIRY,
    }
)

CAPABILITIES = SupplierCapabilities(
    kind=BookingKind.TRANSPORT,
    mode=TransportMode.FLIGHT,
    channel=SupplierChannel.API,
    max_party_per_purchase=MAX_PASSENGERS_PER_ORDER,
    supports_hold=True,
    hold_ttl=NOMINAL_HOLD_TTL,
    quote_ttl=OFFER_TTL,
    required_traveller_fields=REQUIRED_TRAVELLER_FIELDS,
    refund_policy_known=True,
    reports_disruptions=True,
    hold_needs_traveller_details=True,
)

type Clock = Callable[[], datetime]
type Json = dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DuffelConfig:
    api_key: SecretStr
    allow_live: bool = False
    fx_eur_pln: Decimal = DEFAULT_FX_EUR_PLN
    contact_email: str = DEFAULT_CONTACT_EMAIL
    contact_phone: str = DEFAULT_CONTACT_PHONE
    max_offers: int = 5
    cabin_class: str = "economy"

    def rates_to_pln(self) -> dict[str, Decimal]:
        return {"PLN": Decimal(1), "EUR": self.fx_eur_pln}


# ---- money ----------------------------------------------------------------------------------


def decimal_of(amount: object) -> Decimal | None:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def to_pln_minor(amount: Decimal, currency: str, rates: Mapping[str, Decimal]) -> int | None:
    """`Decimal("956.82"), "EUR"` at 4.30 -> 411433 (grosze); None without a rate."""
    rate = rates.get(currency.upper())
    if rate is None:
        return None
    return int((amount * rate * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---- parsing --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlightSegment:
    carrier: str
    carrier_code: str
    flight_number: str
    origin: str
    destination: str
    departs_at: datetime
    arrives_at: datetime

    @property
    def number(self) -> str:
        return f"{self.carrier_code} {self.flight_number}"


@dataclass(frozen=True, slots=True)
class FlightOffer:
    id: str
    owner: str
    total_amount: Decimal
    currency: str
    expires_at: datetime | None
    requires_instant_payment: bool
    hold_until: datetime | None  # the earlier of the price guarantee and the payment deadline
    refundable: bool
    documents_required: bool
    passenger_ids: tuple[str, ...]
    slices: tuple[tuple[FlightSegment, ...], ...]

    @property
    def itinerary(self) -> tuple[str, ...]:
        """What identifies the same flights across searches: number @ local departure."""
        return tuple(
            f"{segment.number}@{segment.departs_at.isoformat()}"
            for legs in self.slices
            for segment in legs
        )

    @property
    def direct(self) -> bool:
        return all(len(legs) == 1 for legs in self.slices)

    @property
    def duration(self) -> timedelta:
        return sum(
            (legs[-1].arrives_at - legs[0].departs_at for legs in self.slices if legs),
            timedelta(0),
        )


def parse_moment(value: object) -> datetime | None:
    """An ISO timestamp from Duffel (`...Z`, offset or naive = UTC)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _zone(place: object) -> ZoneInfo | None:
    name = place.get("time_zone") if isinstance(place, dict) else None
    if not isinstance(name, str):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _local(value: object, place: object) -> datetime:
    """Segment times are the airport's local time without an offset."""
    if not isinstance(value, str):
        raise ValueError("a segment without a time")
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=_zone(place) or UTC)


def _segment(raw: Json) -> FlightSegment:
    carrier = raw.get("marketing_carrier") or raw.get("operating_carrier") or {}
    origin, destination = raw.get("origin") or {}, raw.get("destination") or {}
    return FlightSegment(
        carrier=str(carrier.get("name", "")),
        carrier_code=str(carrier.get("iata_code", "")),
        flight_number=str(
            raw.get("marketing_carrier_flight_number")
            or raw.get("operating_carrier_flight_number")
            or ""
        ),
        origin=str(origin.get("iata_code", "")),
        destination=str(destination.get("iata_code", "")),
        departs_at=_local(raw.get("departing_at"), origin),
        arrives_at=_local(raw.get("arriving_at"), destination),
    )


def _earliest(*moments: datetime | None) -> datetime | None:
    present = [moment for moment in moments if moment is not None]
    return min(present) if present else None


def parse_offer(raw: object) -> FlightOffer | None:
    """One Duffel offer, or None when it is malformed (it is then simply not offered)."""
    if not isinstance(raw, dict):
        return None
    try:
        amount = decimal_of(raw.get("total_amount"))
        if amount is None or not raw.get("id"):
            return None
        payment = raw.get("payment_requirements") or {}
        conditions = raw.get("conditions") or {}
        refund = conditions.get("refund_before_departure") or {}
        slices = tuple(
            tuple(_segment(segment) for segment in sliced.get("segments") or [])
            for sliced in raw.get("slices") or []
        )
        if not slices or not all(slices):
            return None
        return FlightOffer(
            id=str(raw["id"]),
            owner=str((raw.get("owner") or {}).get("name", "")),
            total_amount=amount,
            currency=str(raw.get("total_currency", "")).upper(),
            expires_at=parse_moment(raw.get("expires_at")),
            requires_instant_payment=bool(payment.get("requires_instant_payment", True)),
            hold_until=_earliest(
                parse_moment(payment.get("price_guarantee_expires_at")),
                parse_moment(payment.get("payment_required_by")),
            ),
            refundable=bool(refund.get("allowed", False)),
            documents_required=bool(raw.get("passenger_identity_documents_required", False)),
            passenger_ids=tuple(
                str(passenger["id"])
                for passenger in raw.get("passengers") or []
                if isinstance(passenger, dict) and passenger.get("id")
            ),
            slices=slices,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        logger.debug("skipping a malformed Duffel offer")
        return None


def select_offers(offers: Sequence[FlightOffer], limit: int) -> list[FlightOffer]:
    """The few worth showing a group, cheapest first: the cheapest, the fastest, the cheapest
    direct one, then the next cheapest — each itinerary once."""
    by_price = sorted(offers, key=lambda offer: (offer.total_amount, offer.duration, offer.id))
    if not by_price or limit <= 0:
        return []
    picks: list[FlightOffer] = [by_price[0]]
    fastest = min(by_price, key=lambda offer: (offer.duration, offer.total_amount, offer.id))
    direct = next((offer for offer in by_price if offer.direct), None)
    candidates = [fastest, *([direct] if direct else []), *by_price]
    seen = {by_price[0].itinerary}
    for offer in candidates:
        if len(picks) >= limit:
            break
        if offer.itinerary in seen:
            continue
        seen.add(offer.itinerary)
        picks.append(offer)
    return sorted(picks, key=lambda offer: (offer.total_amount, offer.id))


def fits_preferences(offer: FlightOffer, preferences: TravelPreferences) -> bool:
    """Every slice leaves no earlier than the group wants (local time at the airport) and
    changes planes at most `max_transfers` times."""
    return all(preferences.accepts(legs[0].departs_at.hour, len(legs) - 1) for legs in offer.slices)


# ---- travellers -----------------------------------------------------------------------------

_ASCII_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "đ": "d"})


def ascii_name(name: str) -> str:
    """ "Łucja Żółć" -> "Lucja Zolc": airline PNRs take plain Latin letters."""
    folded = unicodedata.normalize("NFKD", name.translate(_ASCII_FOLD))
    return "".join(char for char in folded if not unicodedata.combining(char)).strip()


def passenger_payload(
    passenger_id: str,
    traveller: TravellerDetails,
    *,
    email: str,
    phone: str,
    documents: bool,
) -> Json:
    """One order passenger. Raises ValueError (naming the field, never a value) when the
    traveller lacks something Duffel requires."""
    given, family = split_name(ascii_name(traveller.full_name))
    if not given or not family:
        raise ValueError("full_name")
    if traveller.date_of_birth is None:
        raise ValueError("date_of_birth")
    if traveller.gender is None:
        raise ValueError("gender")
    female = traveller.gender is Gender.FEMALE
    payload: Json = {
        "id": passenger_id,
        "type": "adult",
        "given_name": given,
        "family_name": family,
        "born_on": traveller.date_of_birth.isoformat(),
        "gender": "f" if female else "m",
        "title": "ms" if female else "mr",
        "email": email,
        "phone_number": phone,
    }
    if documents:
        if not (traveller.document_number and traveller.nationality and traveller.document_expiry):
            raise ValueError("document_number")
        payload["identity_documents"] = [
            {
                "type": "passport",
                "unique_identifier": traveller.document_number,
                "issuing_country_code": traveller.nationality,
                "expires_on": traveller.document_expiry.isoformat(),
            }
        ]
    return payload


# ---- the adapter ----------------------------------------------------------------------------


@dataclass
class DuffelLog:
    """What the adapter did, for the harness report: calls with timings and notes. No
    traveller data, no key."""

    calls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# Duffel's test airline: its flight numbers exist nowhere else, so no status link for them.
TEST_AIRLINE_CODES = frozenset({"ZZ"})


def flight_links(offer: FlightOffer) -> tuple[OfferLink, ...]:
    """A Google Flights search for the same route and dates (verify), and a live-status page
    per real flight number. Never a "buy" link: the group buys through the app."""
    first, last = offer.slices[0], offer.slices[-1]
    return_date = last[0].departs_at.date() if len(offer.slices) > 1 else None
    links = [
        OfferLink(
            label=f"{first[0].origin} -> {first[-1].destination} on Google Flights",
            url=google_flights_url(
                first[0].origin, first[-1].destination, first[0].departs_at.date(), return_date
            ),
            kind=LinkKind.VERIFY,
        )
    ]
    numbers = dict.fromkeys(
        segment.number
        for legs in offer.slices
        for segment in legs
        if segment.carrier_code and segment.carrier_code not in TEST_AIRLINE_CODES
    )
    links += [
        OfferLink(label=f"{number} status", url=flight_status_url(number), kind=LinkKind.STATUS)
        for number in numbers
    ]
    return tuple(links)


def _trip_word(slices: Sequence[object]) -> str:
    return "return" if len(slices) > 1 else "one way"


class DuffelSupplier:
    id = SUPPLIER_ID

    def __init__(self, client: DuffelClient, config: DuffelConfig, clock: Clock = _utc_now):
        self.client = client
        self.config = config
        self.clock = clock
        self.capabilities = CAPABILITIES
        self.rates = config.rates_to_pln()
        mode = "" if client.live_mode else ", test mode"
        self.display_name = f"Duffel (airline API{mode})"
        self.log = DuffelLog()
        # Airlines (offer owners) whose offers are not offered as holdable any more.
        self.hold_refusers: set[str] = set() if client.live_mode else set(TEST_MODE_HOLD_REFUSERS)

    # ---- calls, timed and logged (paths and codes only) -----------------------------------

    async def _get(
        self, path: str, *, params: Mapping[str, str] | None = None, label: str = ""
    ) -> Result[Any, DuffelFailure]:
        started = time.monotonic()
        try:
            answer = await self.client.get(path, params=params)
        except SupplierUnavailableError:
            self._record(f"GET {label or path}", None, started)
            raise
        self._record(f"GET {label or path}", answer, started)
        return answer

    async def _post(self, path: str, data: Json, *, label: str) -> Result[Any, DuffelFailure]:
        started = time.monotonic()
        try:
            answer = await self.client.post(path, data)
        except SupplierUnavailableError:
            self._record(f"POST {path} {label}", None, started)
            raise
        self._record(f"POST {path} {label}", answer, started)
        return answer

    def _record(self, call: str, answer: Result[Any, DuffelFailure] | None, started: float) -> None:
        if answer is None:
            outcome = "unreachable"
        elif isinstance(answer, Err):
            outcome = answer.error.describe()
        else:
            outcome = "ok"
        self.log.calls.append(f"{call}: {outcome} ({time.monotonic() - started:.1f} s)")

    # ---- search -------------------------------------------------------------------------

    async def search(self, request: SearchRequest) -> list[Offer]:
        if request.mode not in (None, TransportMode.FLIGHT) or request.party_size <= 0:
            return []
        origin, destination = airport_code(request.origin), airport_code(request.destination)
        if origin is None or destination is None:
            self.log.notes.append(f"no airport for {request.origin} / {request.destination}")
            return []
        slices = [_slice(origin, destination, request.depart_date.isoformat())]
        if request.return_date is not None:
            slices.append(_slice(destination, origin, request.return_date.isoformat()))
        searched = min(request.party_size, MAX_PASSENGERS_PER_ORDER)
        try:
            found = await self._offer_request(slices, searched)
        except SupplierUnavailableError as error:
            # A failed search means "no flights from Duffel", never a crashed research.
            logger.warning("Duffel search failed: %s", error)
            self.log.notes.append(f"the Duffel search failed: {error}")
            return []
        if isinstance(found, Err):
            self.log.notes.append(f"the Duffel search was refused: {found.error.describe()}")
            return []
        request_id, offers = found.value
        usable = [
            offer
            for offer in offers
            if self._holdable(offer) and fits_preferences(offer, request.preferences)
        ]
        chosen = select_offers(usable, self.config.max_offers)
        self.log.notes.append(
            f"{origin} -> {destination} {searched} pax: {len(offers)} offers, "
            f"{len(usable)} holdable, showing {len(chosen)}"
        )
        return [
            self._offer(offer, request, slices, request_id, searched)
            for offer in chosen
            if offer.currency in self.rates
        ]

    def _holdable(self, offer: FlightOffer) -> bool:
        return (
            not offer.requires_instant_payment
            and offer.hold_until is not None
            and offer.owner not in self.hold_refusers
            and offer.currency in self.rates
        )

    def _offer(
        self,
        offer: FlightOffer,
        request: SearchRequest,
        slices: list[Json],
        request_id: str,
        searched: int,
    ) -> Offer:
        pln = to_pln_minor(offer.total_amount, offer.currency, self.rates) or 0
        # A party above an order's cap is priced from the capped search; each purchase of at
        # most nine is re-found and priced for its own size when it is held.
        price = round(pln * request.party_size / searched)
        segments = tuple(
            Segment(
                carrier=segment.carrier,
                number=segment.number,
                origin=segment.origin,
                destination=segment.destination,
                departs_at=segment.departs_at,
                arrives_at=segment.arrives_at,
            )
            for legs in offer.slices
            for segment in legs
        )
        numbers = " / ".join(" + ".join(s.number for s in legs) for legs in offer.slices)
        first = offer.slices[0]
        title = (
            f"{offer.owner} {numbers} {first[0].origin} -> {first[-1].destination} "
            f"({_trip_word(offer.slices)})"
        )[:120]
        rate = self.rates[offer.currency]
        fare = f"{offer.total_amount:.2f} {offer.currency}"
        converted = "" if offer.currency == "PLN" else f" = {format_money(pln, 'PLN')} at {rate}"
        details = (
            " ".join(segment.describe() + "." for segment in segments)
            + f" Fare for {searched} at Duffel: {fare}{converted}"
            + (f" PLN/{offer.currency}." if converted else ".")
            + (" Refundable before departure." if offer.refundable else " Non-refundable.")
        )
        return Offer(
            supplier_id=self.id,
            offer_ref=offer.id,
            title=title,
            price_minor=price,
            currency="PLN",
            seller=offer.owner or "Duffel",
            segments=segments,
            refundable=offer.refundable,
            expires_at=offer.expires_at,
            purchase_url=DASHBOARD_URL,
            details=details,
            starts_at=segments[0].departs_at,
            links=flight_links(offer),
            provenance=Provenance(
                ProvenanceSource.LIVE if self.client.live_mode else ProvenanceSource.TEST,
                "Duffel",
                self.clock(),
            ),
            supplier_data={
                "offer_id": offer.id,
                "offer_request_id": request_id,
                "passenger_ids": list(offer.passenger_ids),
                "party_size": searched,
                "currency": offer.currency,
                "original_amount": f"{offer.total_amount:.2f}",
                "fx_rate": str(rate),
                "slices": slices,
                "itinerary": list(offer.itinerary),
                "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
                "title": title,
            },
        )

    async def _offer_request(
        self, slices: list[Json], passengers: int
    ) -> Result[tuple[str, list[FlightOffer]], DuffelFailure]:
        started = time.monotonic()
        answer = await self.client.post(
            "/air/offer_requests",
            {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(passengers)],
                "cabin_class": self.config.cabin_class,
            },
            params=SEARCH_PARAMS,
            idempotent=True,
            timeout_s=SEARCH_TIMEOUT_S,
        )
        seconds = time.monotonic() - started
        route = " ".join(f"{s['origin']}-{s['destination']} {s['departure_date']}" for s in slices)
        if isinstance(answer, Err):
            self.log.calls.append(f"POST /air/offer_requests {route}: refused ({seconds:.1f} s)")
            return answer
        data = answer.value if isinstance(answer.value, dict) else {}
        offers = [parsed for raw in data.get("offers") or [] if (parsed := parse_offer(raw))]
        self.log.calls.append(
            f"POST /air/offer_requests {route} x{passengers}: {len(offers)} offers "
            f"({seconds:.1f} s)"
        )
        return Ok((str(data.get("id", "")), offers))

    # ---- finding the offer again ----------------------------------------------------------

    async def _current(
        self, offer: OfferRef, party_size: int, *, holdable_only: bool
    ) -> FlightOffer | None:
        """The offer as Duffel sells it now for `party_size`: the stored one while it is
        alive and for the same party, else the same flights found by a fresh search."""
        data = offer.supplier_data
        expires_at = parse_moment(data.get("expires_at"))
        same_party = int(data.get("party_size", 0)) == party_size
        if same_party and expires_at is not None and self.clock() < expires_at:
            answer = await self._get(f"/air/offers/{offer.offer_ref}")
            if isinstance(answer, Ok):
                current = parse_offer(answer.value)
                if current is not None and (not holdable_only or self._holdable(current)):
                    return current
        return await self._refind(offer, party_size, holdable_only=holdable_only)

    async def _refind(
        self, offer: OfferRef, party_size: int, *, holdable_only: bool
    ) -> FlightOffer | None:
        data = offer.supplier_data
        slices = data.get("slices")
        wanted = tuple(str(leg) for leg in data.get("itinerary") or [])
        if not isinstance(slices, list) or not wanted:
            return None
        found = await self._offer_request(slices, party_size)
        if isinstance(found, Err):
            if found.error.status >= 400 and found.error.status != 422:
                raise SupplierUnavailableError(f"Duffel search: {found.error.describe()}")
            return None
        _, offers = found.value
        same = sorted(
            (
                candidate
                for candidate in offers
                if candidate.itinerary == wanted and candidate.currency in self.rates
            ),
            key=lambda candidate: (candidate.total_amount, candidate.id),
        )
        title = data.get("title", offer.offer_ref)
        # A search result's payment terms are a summary; the single offer is authoritative
        # (and reading it refreshes the price Duffel books at).
        for candidate in same[:_REFIND_CHECKS]:
            answer = await self._get(f"/air/offers/{candidate.id}")
            current = parse_offer(answer.value) if isinstance(answer, Ok) else None
            if current is None or (holdable_only and not self._holdable(current)):
                continue
            self.log.notes.append(
                f"re-found {title} for {party_size} pax as {current.id} "
                f"({current.total_amount:.2f} {current.currency})"
            )
            return current
        self.log.notes.append(f"{title}: no longer offered for {party_size} pax")
        return None

    # ---- quote / hold / purchase -----------------------------------------------------------

    def _pln(self, amount: Decimal, currency: str) -> int:
        converted = to_pln_minor(amount, currency, self.rates)
        if converted is None:
            raise SupplierUnavailableError(f"no exchange rate for {currency} -> PLN configured")
        return converted

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        current = await self._current(offer, party_size, holdable_only=False)
        if current is None:
            return None
        now = self.clock()
        return Quote(
            price_minor=self._pln(current.total_amount, current.currency),
            currency="PLN",
            quoted_at=now,
            expires_at=current.expires_at,
        )

    def _passengers(self, offer: FlightOffer, travellers: Sequence[TravellerDetails]) -> list[Json]:
        if len(offer.passenger_ids) != len(travellers):
            raise SupplierUnavailableError("the offer's passengers do not match the travellers")
        try:
            return [
                passenger_payload(
                    passenger_id,
                    traveller,
                    email=self.config.contact_email,
                    phone=self.config.contact_phone,
                    documents=offer.documents_required,
                )
                for passenger_id, traveller in zip(offer.passenger_ids, travellers, strict=True)
            ]
        except ValueError as missing:
            raise SupplierUnavailableError(
                f"a traveller lacks a detail Duffel requires ({missing})"
            ) from None

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        """A hold order: the seats are booked and named, the price guaranteed until the
        hold's expiry, nothing is paid yet."""
        if not travellers:
            return None
        current = await self._current(offer, len(travellers), holdable_only=True)
        if current is None:
            return None
        passengers = self._passengers(current, travellers)
        answer = await self._order_hold(current.id, passengers)
        if isinstance(answer, Err) and answer.error.has(PRICE_CHANGED_CODE):
            # The airline re-priced since the search: reading the offer again refreshes the
            # price Duffel books at; the hold then carries it (and the trip flow re-splits).
            await self._get(f"/air/offers/{current.id}")
            answer = await self._order_hold(current.id, passengers)
        if isinstance(answer, Err):
            if answer.error.has(*_GONE_CODES):
                return None
            if answer.error.has(HOLD_REFUSED_CODE):
                self.hold_refusers.add(current.owner)
                self.log.notes.append(f"{current.owner} does not hold: offered as instant only")
            raise SupplierUnavailableError(f"Duffel refused the hold: {answer.error.describe()}")
        order = answer.value if isinstance(answer.value, dict) else {}
        amount = decimal_of(order.get("total_amount")) or current.total_amount
        currency = str(order.get("total_currency") or current.currency)
        expires_at = _hold_expiry(order) or current.hold_until or (self.clock() + NOMINAL_HOLD_TTL)
        self.log.notes.append(
            f"hold order {order.get('id')} ({order.get('booking_reference', '')}): "
            f"{amount:.2f} {currency}, until {expires_at:%Y-%m-%d %H:%M} UTC"
        )
        return Hold(
            ref=str(order.get("id", "")),
            expires_at=expires_at,
            price_minor=self._pln(amount, currency),
        )

    async def _order_hold(
        self, offer_id: str, passengers: list[Json]
    ) -> Result[Any, DuffelFailure]:
        return await self._post(
            "/air/orders",
            {"type": "hold", "selected_offers": [offer_id], "passengers": passengers},
            label=f"hold {offer_id}",
        )

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        """Pays the held order (or books and pays at once without a hold). Ok(the airline's
        booking reference).

        A held order is paid at the price it holds, while its guarantee lasts: that price
        is what the trip flow accepted when the hold was placed (re-split, or kept within
        `PRICE_TOLERANCE_PERCENT`). Without a hold nothing is paid above `price_minor`."""
        try:
            if hold_ref:
                return await self._pay_held(hold_ref)
            return await self._buy_instantly(offer, travellers, price_minor)
        except SupplierUnavailableError as error:
            return Err(f"Duffel could not be reached ({error}); check the order before retrying")

    async def _pay_held(self, order_id: str) -> Result[str, str]:
        found = await self._get(f"/air/orders/{order_id}")
        if isinstance(found, Err):
            return Err(f"Duffel does not know the held order ({found.error.describe()})")
        order = found.value if isinstance(found.value, dict) else {}
        reference = str(order.get("booking_reference") or "")
        if order.get("cancelled_at"):
            return Err("the held order was cancelled by the airline")
        payment_status = order.get("payment_status") or {}
        if payment_status.get("awaiting_payment") is False:
            return Ok(reference or order_id)  # already paid: a retried approval
        amount = decimal_of(order.get("total_amount"))
        currency = str(order.get("total_currency") or "")
        if amount is None or not currency:
            return Err("the held order has no price")
        guaranteed_until = _hold_expiry(order)
        if guaranteed_until is not None and guaranteed_until <= self.clock():
            return Err("the held price is no longer guaranteed — hold the flights again")
        paid = await self._post(
            "/air/payments",
            {
                "order_id": order_id,
                "payment": {"type": "balance", "amount": f"{amount:.2f}", "currency": currency},
            },
            label=f"{order_id} {amount:.2f} {currency}",
        )
        if isinstance(paid, Err):
            return Err(f"Duffel refused the payment ({paid.error.describe()})")
        payment = paid.value if isinstance(paid.value, dict) else {}
        if payment.get("status") == "failed":
            return Err(f"the payment failed: {payment.get('failure_reason') or 'unknown'}")
        self.log.notes.append(f"paid order {order_id}: booking reference {reference}")
        return Ok(reference or order_id)

    async def _buy_instantly(
        self, offer: OfferRef, travellers: Sequence[TravellerDetails], price_minor: int
    ) -> Result[str, str]:
        current = await self._current(offer, len(travellers), holdable_only=False)
        if current is None:
            return Err("Duffel no longer offers these flights")
        refused = self._dearer(current.total_amount, current.currency, price_minor)
        if refused is not None:
            return Err(refused)
        answer = await self._post(
            "/air/orders",
            {
                "type": "instant",
                "selected_offers": [current.id],
                "passengers": self._passengers(current, travellers),
                "payments": [
                    {
                        "type": "balance",
                        "amount": f"{current.total_amount:.2f}",
                        "currency": current.currency,
                    }
                ],
            },
            label=f"instant {current.id}",
        )
        if isinstance(answer, Err):
            return Err(f"Duffel refused the order ({answer.error.describe()})")
        order = answer.value if isinstance(answer.value, dict) else {}
        return Ok(str(order.get("booking_reference") or order.get("id") or ""))

    def _dearer(self, amount: Decimal, currency: str, price_minor: int) -> str | None:
        pln = self._pln(amount, currency)
        if pln <= price_minor:
            return None
        return (
            f"Duffel now asks {amount:.2f} {currency} ({format_money(pln, 'PLN')}), more than "
            f"the approved {format_money(price_minor, 'PLN')}"
        )

    # ---- disruptions ----------------------------------------------------------------------

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        """The newest airline-initiated change nobody acted on. Duffel offers no
        re-accommodation as an offer, so the notice carries no replacement."""
        if not booking.hold_ref:
            return None
        try:
            answer = await self._get(
                "/air/airline_initiated_changes",
                params={"order_id": booking.hold_ref},
                label=f"/air/airline_initiated_changes?order_id={booking.hold_ref}",
            )
        except SupplierUnavailableError as error:
            logger.warning("Duffel status check failed: %s", error)
            return None
        if isinstance(answer, Err) or not isinstance(answer.value, list):
            return None
        open_changes = [
            change
            for change in answer.value
            if isinstance(change, dict) and change.get("action_taken") is None
        ]
        if not open_changes:
            return None
        newest = max(open_changes, key=lambda change: str(change.get("created_at", "")))
        title = str(booking.offer.supplier_data.get("title", booking.offer.offer_ref))
        return notice_of(newest, title)


def _slice(origin: str, destination: str, day: str) -> Json:
    return {"origin": origin, "destination": destination, "departure_date": day}


def _hold_expiry(order: Json) -> datetime | None:
    status = order.get("payment_status") or {}
    return _earliest(
        parse_moment(status.get("price_guarantee_expires_at")),
        parse_moment(status.get("payment_required_by")),
    )


def _first_departure(slices: object) -> FlightSegment | None:
    for sliced in slices if isinstance(slices, list) else []:
        segments = sliced.get("segments") if isinstance(sliced, dict) else None
        if segments:
            try:
                return _segment(segments[0])
            except (TypeError, ValueError, AttributeError):
                return None
    return None


def notice_of(change: Json, title: str) -> DisruptionNotice:
    """An airline-initiated change -> a cancellation (nothing added) or a schedule change."""
    before = _first_departure(change.get("removed"))
    after = _first_departure(change.get("added"))
    if after is None:
        return DisruptionNotice(
            kind=DisruptionKind.CANCELLATION, message=f"The airline cancelled {title}."
        )
    minutes = 0
    if before is not None:
        minutes = round((after.departs_at - before.departs_at).total_seconds() / 60)
    if before is not None and minutes != 0:
        moved = f"from {before.departs_at:%a %d %b %H:%M} to {after.departs_at:%H:%M}"
    else:
        moved = f"(now {after.number} at {after.departs_at:%a %d %b %H:%M})"
    return DisruptionNotice(
        kind=DisruptionKind.DELAY,
        message=f"The airline changed the schedule of {title}: departure moved {moved}.",
        delay_minutes=max(minutes, 0),
    )
