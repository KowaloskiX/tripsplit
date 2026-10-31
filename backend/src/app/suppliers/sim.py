"""Simulated suppliers: one configurable `SimSupplier` that plays an airline, a rail carrier, a
bus line, a hotel prebook or an activity seller, plus a scriptable `SimBehaviour`.

The catalogue is generated deterministically from the search (`app.suppliers.sim_catalogue`),
so the same trip always gets the same offers. `SimBehaviour` scripts what a real supplier does
to you: a price that moves between the search and the quote or hold, a sold-out offer, holds
that lapse, a purchase that fails, a CAPTCHA in front of the agent, a cancelled flight.

Time comes from an injected clock, so a hold "expires" when the caller's clock says so — the
trip harness moves that clock forward instead of sleeping for a day.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.domain.bookings import repriced_minor
from app.core.domain.result import Err, Ok, Result
from app.core.domain.suppliers import (
    NAME_ONLY,
    SupplierCapabilities,
    TravellerField,
    hold_is_live,
)
from app.core.domain.travellers import TravellerDetails
from app.core.domain.trips import BookingKind, SupplierChannel, TransportMode
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
)
from app.suppliers.sim_catalogue import (
    AIRLINES,
    BUS_LINES,
    RAIL_CARRIER,
    RETURN_LEG_FACTOR,
    Carrier,
    Origin,
    Place,
    RailLeg,
    find_origin,
    find_place,
)

LOCAL = ZoneInfo("Europe/Warsaw")
SIM_URL = "https://sim.tripsplit.invalid"
type Clock = Callable[[], datetime]
type ScriptedAgentOutcome = str  # "done" | "handoff" | "stuck" | "error" (harness vocabulary)


@dataclass(frozen=True, slots=True)
class SimDisruption:
    kind: DisruptionKind = DisruptionKind.CANCELLATION
    delay_minutes: int = 0
    # The re-accommodation on ANOTHER carrier, priced relative to the original fare.
    replacement_price_percent: float = 0.0


@dataclass
class SimBehaviour:
    """What the simulated supplier does next. One-shot fields are consumed when they fire."""

    price_change_percent: float | None = None  # one-shot: the next quote or hold moves
    sold_out: bool = False
    hold_ttl: timedelta | None = None  # overrides the capability's TTL for new holds
    purchase_failure: str | None = None
    agent_outcome: ScriptedAgentOutcome | None = None  # the harness's scripted agent reads it
    disruption: SimDisruption | None = None  # one-shot: reported by the next `status` call


@dataclass
class SimSupplier:
    id: str
    display_name: str
    capabilities: SupplierCapabilities
    clock: Clock
    behaviour: SimBehaviour = field(default_factory=SimBehaviour)
    holds: dict[str, tuple[datetime, int]] = field(default_factory=dict)
    purchases: list[str] = field(default_factory=list)

    # ---- search -------------------------------------------------------------------------

    async def search(self, request: SearchRequest) -> list[Offer]:
        match self.capabilities.kind:
            case BookingKind.TRANSPORT:
                return self._transport(request)
            case BookingKind.STAY:
                return self._stays(request)
            case BookingKind.ACTIVITY:
                return self._activities(request)

    def _transport(self, request: SearchRequest) -> list[Offer]:
        route = _route(request)
        if route is None:
            return []
        origin, place, outbound = route
        match self.capabilities.mode:
            case TransportMode.RAIL:
                return self._rail(request, origin, place, outbound)
            case TransportMode.FLIGHT:
                return self._carriers(request, origin, place, outbound, AIRLINES)
            case TransportMode.BUS:
                return self._carriers(request, origin, place, outbound, BUS_LINES)
            case _:
                return []

    def _rail(
        self, request: SearchRequest, origin: Origin, place: Place, outbound: bool
    ) -> list[Offer]:
        if place.rail_out is None or place.rail_back is None:
            return []
        out_leg, back_leg = place.rail_out, place.rail_back
        offers = []
        for travel_class in (2, 1):
            label = "2nd" if travel_class == 2 else "1st"
            legs: list[tuple[RailLeg, date, str, str]] = []
            if outbound:
                legs.append((out_leg, request.depart_date, origin.station, place.station))
                if request.return_date is not None:
                    legs.append((back_leg, request.return_date, place.station, origin.station))
            else:
                legs.append((back_leg, request.depart_date, place.station, origin.station))
            per_person = sum(
                leg.second_pp if travel_class == 2 else leg.first_pp for leg, *_ in legs
            )
            segments = tuple(
                Segment(
                    carrier=RAIL_CARRIER,
                    number=leg.number,
                    origin=start,
                    destination=end,
                    departs_at=_at(day, leg.departs),
                    arrives_at=_at(day, leg.arrives),
                )
                for leg, day, start, end in legs
            )
            first = legs[0][0]
            trip = "return" if len(legs) > 1 else "one way"
            offers.append(
                self._offer(
                    ref=f"{first.number}:{request.depart_date}:{label}:{len(legs)}",
                    title=(
                        f"{RAIL_CARRIER} {first.number} {first.name} · {segments[0].origin} → "
                        f"{segments[0].destination} · {label} class · {trip}"
                    ),
                    seller=RAIL_CARRIER,
                    per_person=per_person,
                    request=request,
                    segments=segments,
                    details=" ".join(s.describe() + "." for s in segments)
                    + f" Super Promo International, {label} class.",
                )
            )
        return offers

    def _carriers(
        self,
        request: SearchRequest,
        origin: Origin,
        place: Place,
        outbound: bool,
        carriers: Sequence[Carrier],
    ) -> list[Offer]:
        flight = self.capabilities.mode is TransportMode.FLIGHT
        base = place.flight_pp if flight else place.bus_pp
        if base is None:
            return []
        minutes = place.flight_minutes if flight else place.bus_minutes
        offers = []
        for carrier in carriers:
            home = (
                origin.low_cost_airport if flight and carrier.low_cost_airport else origin.airport
            )
            if not flight:
                home = origin.bus_stop
            away = place.airport if flight else place.bus_stop
            legs: list[tuple[date, str, str, time, float]] = []
            if outbound:
                legs.append((request.depart_date, home, away, carrier.departs_out, 1.0))
                if request.return_date is not None:
                    legs.append(
                        (request.return_date, away, home, carrier.departs_back, RETURN_LEG_FACTOR)
                    )
            else:
                legs.append((request.depart_date, away, home, carrier.departs_back, 1.0))
            segments = tuple(
                Segment(
                    carrier=carrier.name,
                    number=carrier.number(f"{start}-{end}"),
                    origin=start,
                    destination=end,
                    departs_at=_at(day, departs),
                    arrives_at=_at(day, departs) + timedelta(minutes=minutes),
                )
                for day, start, end, departs, _ in legs
            )
            per_person = sum(
                round(base * carrier.price_factor * factor / 100) * 100 for *_, factor in legs
            )
            trip = "return" if len(legs) > 1 else "one way"
            numbers = " / ".join(segment.number for segment in segments)
            offers.append(
                self._offer(
                    ref=f"{carrier.code}:{numbers}:{request.depart_date}:{len(legs)}",
                    title=(
                        f"{carrier.name} {numbers} · {segments[0].origin} → "
                        f"{segments[0].destination} · {trip}"
                    ),
                    seller=carrier.name,
                    per_person=per_person,
                    request=request,
                    segments=segments,
                    details=" ".join(s.describe() + "." for s in segments),
                    carrier=carrier.code,
                )
            )
        return offers

    def _stays(self, request: SearchRequest) -> list[Offer]:
        place = find_place(request.destination)
        if place is None:
            return []
        nights = max(((request.return_date or request.depart_date) - request.depart_date).days, 1)
        options = (
            (
                f"Central hostel in {place.name} (dorm beds)",
                place.hostel_dorm_night,
                "Beds in 6-bed dorms, lockers, shared kitchen, rating 8.5+.",
            ),
            (
                f"Central hostel in {place.name} (private rooms)",
                place.hostel_night,
                "Private 4-6 bed rooms, shared kitchen, rating 8.5+.",
            ),
            (
                f"Apartment in {place.apartment_area}, {place.name}",
                place.apartment_night,
                "Entire place, 3 bedrooms, kitchen, rating 9+.",
            ),
            (
                f"4-star hotel in {place.hotel_area}, {place.name}",
                place.hotel_night,
                "Twin rooms with breakfast, rating 8.8+.",
            ),
        )
        return [
            self._offer(
                ref=f"stay:{index}:{request.depart_date}:{nights}",
                title=title,
                seller="Booking.com",
                per_person=per_night * nights,
                request=request,
                details=f"{nights} night(s) for {request.party_size} guests. {details}",
            )
            for index, (title, per_night, details) in enumerate(options)
        ]

    def _activities(self, request: SearchRequest) -> list[Offer]:
        place = find_place(request.destination)
        if place is None:
            return []
        starts_at = _at(request.depart_date, time(19))
        options = (
            (place.casual_activity, place.casual_activity_price),
            (place.splurge_activity, place.splurge_activity_price),
        )
        return [
            self._offer(
                ref=f"activity:{index}:{request.depart_date}",
                title=title,
                seller="GetYourGuide",
                per_person=price,
                request=request,
                details=f"Saturday evening, {request.party_size} people.",
                starts_at=starts_at,
            )
            for index, (title, price) in enumerate(options)
        ]

    def _offer(
        self,
        *,
        ref: str,
        title: str,
        seller: str,
        per_person: int,
        request: SearchRequest,
        segments: tuple[Segment, ...] = (),
        details: str = "",
        starts_at: datetime | None = None,
        carrier: str = "",
    ) -> Offer:
        offer_ref = f"{self.id}:{ref}"
        return Offer(
            supplier_id=self.id,
            offer_ref=offer_ref,
            title=title[:120],
            price_minor=per_person * request.party_size,
            currency=request.currency,
            seller=seller,
            segments=segments,
            refundable=self.capabilities.refund_policy_known,
            expires_at=self.clock() + self.capabilities.quote_ttl,
            purchase_url=f"{SIM_URL}/{self.id}/book?offer={offer_ref}",
            details=details,
            starts_at=starts_at or (segments[0].departs_at if segments else None),
            supplier_data={
                "price_per_person_minor": per_person,
                "carrier": carrier,
                "title": title[:120],
                "currency": request.currency,
            },
        )

    # ---- quote / hold / purchase / status -------------------------------------------------

    def _price(self, offer: OfferRef, party_size: int) -> int:
        per_person = int(offer.supplier_data.get("price_per_person_minor", 0))
        price = per_person * party_size
        change = self.behaviour.price_change_percent
        if change is not None:
            self.behaviour.price_change_percent = None
            price = repriced_minor(price, change)
        return price

    async def quote(self, offer: OfferRef, party_size: int) -> Quote | None:
        if self.behaviour.sold_out:
            return None
        now = self.clock()
        return Quote(
            price_minor=self._price(offer, party_size),
            currency=str(offer.supplier_data.get("currency", "PLN")),
            quoted_at=now,
            expires_at=now + self.capabilities.quote_ttl,
        )

    async def hold(self, offer: OfferRef, travellers: Sequence[TravellerDetails]) -> Hold | None:
        ttl = self.behaviour.hold_ttl or self.capabilities.hold_ttl
        if not self.capabilities.supports_hold or ttl is None or self.behaviour.sold_out:
            return None
        price = self._price(offer, len(travellers))
        ref = f"{self.id.upper()}-H{len(self.holds) + 1:03d}"
        expires_at = self.clock() + ttl
        self.holds[ref] = (expires_at, price)
        return Hold(ref=ref, expires_at=expires_at, price_minor=price)

    async def purchase(
        self,
        offer: OfferRef,
        travellers: Sequence[TravellerDetails],
        *,
        price_minor: int,
        hold_ref: str | None,
    ) -> Result[str, str]:
        if self.capabilities.channel is not SupplierChannel.API:
            return Err(f"{self.display_name} is not bought through an API")
        if self.behaviour.purchase_failure is not None:
            return Err(self.behaviour.purchase_failure)
        if self.capabilities.supports_hold and hold_ref is not None:
            held = self.holds.get(hold_ref)
            if held is None or not hold_is_live(held[0], self.clock()):
                return Err("the hold has expired")
            if held[1] != price_minor:
                return Err("the price does not match the hold")
        required = self.capabilities.required_traveller_fields
        if any(required - traveller.provided_fields() for traveller in travellers):
            return Err("traveller details are incomplete")
        reference = f"{self.id.upper().replace('_', '')}-{len(self.purchases) + 1:04d}"
        self.purchases.append(reference)
        return Ok(reference)

    async def status(self, booking: BookingRef) -> DisruptionNotice | None:
        disruption = self.behaviour.disruption
        if disruption is None or not self.capabilities.reports_disruptions:
            return None
        self.behaviour.disruption = None
        title = str(booking.offer.supplier_data.get("title", booking.offer.offer_ref))
        if disruption.kind is DisruptionKind.DELAY:
            message = f"{title} is delayed by {disruption.delay_minutes} min."
        else:
            message = f"{title} is cancelled."
        return DisruptionNotice(
            kind=disruption.kind,
            message=message,
            delay_minutes=disruption.delay_minutes,
            replacement=self._replacement(booking, disruption),
        )

    def _replacement(self, booking: BookingRef, disruption: SimDisruption) -> Offer:
        """The same trip on another carrier (or the next departure), repriced."""
        data = dict(booking.offer.supplier_data)
        per_person = repriced_minor(
            int(data.get("price_per_person_minor", 0)), disruption.replacement_price_percent
        )
        carriers = AIRLINES if self.capabilities.mode is TransportMode.FLIGHT else BUS_LINES
        original = str(data.get("carrier", ""))
        other = next((c for c in carriers if c.code != original), None)
        if self.capabilities.mode is TransportMode.RAIL or other is None:
            title = f"{data.get('title', 'Replacement')} (next departure)"
            seller = RAIL_CARRIER if self.capabilities.mode is TransportMode.RAIL else ""
            code = original
        else:
            number = other.number(f"rebook:{booking.offer.offer_ref}")
            title = f"{other.name} {number} (rebooked: {data.get('title', '')})"
            seller, code = other.name, other.code
        ref = f"{booking.offer.offer_ref}:rebooked:{code}"
        supplier_data: dict[str, Any] = {
            **data,
            "price_per_person_minor": per_person,
            "carrier": code,
            "title": title[:120],
        }
        return Offer(
            supplier_id=self.id,
            offer_ref=ref,
            title=title[:120],
            price_minor=per_person * booking.party_size,
            currency=str(data.get("currency", "PLN")),
            seller=seller or self.display_name,
            refundable=self.capabilities.refund_policy_known,
            purchase_url=f"{SIM_URL}/{self.id}/book?offer={ref}",
            supplier_data=supplier_data,
        )


def _route(request: SearchRequest) -> tuple[Origin, Place, bool] | None:
    """(home, the place, outbound?) — a one-way search from the place is the way home."""
    place = find_place(request.destination)
    if place is not None:
        return find_origin(request.origin), place, True
    place = find_place(request.origin)
    if place is not None:
        return find_origin(request.destination), place, False
    return None


def _at(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=LOCAL)


# ---- the standard simulated suppliers -------------------------------------------------------

INTERNATIONAL_FLIGHT_FIELDS: frozenset[TravellerField] = frozenset(
    {
        TravellerField.FULL_NAME,
        TravellerField.DATE_OF_BIRTH,
        TravellerField.NATIONALITY,
        TravellerField.DOCUMENT_NUMBER,
    }
)

SIM_CAPABILITIES: dict[str, tuple[str, SupplierCapabilities]] = {
    "sim_flight": (
        "Flights (simulated airline API)",
        SupplierCapabilities(
            kind=BookingKind.TRANSPORT,
            mode=TransportMode.FLIGHT,
            channel=SupplierChannel.API,
            max_party_per_purchase=9,
            supports_hold=True,
            hold_ttl=timedelta(hours=24),
            quote_ttl=timedelta(minutes=30),
            required_traveller_fields=INTERNATIONAL_FLIGHT_FIELDS,
            refund_policy_known=True,
            reports_disruptions=True,
        ),
    ),
    "sim_rail": (
        "Rail (simulated carrier site)",
        SupplierCapabilities(
            kind=BookingKind.TRANSPORT,
            mode=TransportMode.RAIL,
            channel=SupplierChannel.AGENT,
            max_party_per_purchase=5,
            quote_ttl=timedelta(minutes=20),
            required_traveller_fields=NAME_ONLY,
            reports_disruptions=True,
        ),
    ),
    "sim_bus": (
        "Coaches (simulated bus site)",
        SupplierCapabilities(
            kind=BookingKind.TRANSPORT,
            mode=TransportMode.BUS,
            channel=SupplierChannel.AGENT,
            max_party_per_purchase=9,
            quote_ttl=timedelta(minutes=30),
            required_traveller_fields=NAME_ONLY,
            reports_disruptions=True,
        ),
    ),
    "sim_stay": (
        "Stays (simulated hotel API with prebook)",
        SupplierCapabilities(
            kind=BookingKind.STAY,
            mode=None,
            channel=SupplierChannel.API,
            max_party_per_purchase=None,
            supports_hold=True,
            hold_ttl=timedelta(hours=72),
            quote_ttl=timedelta(minutes=30),
            required_traveller_fields=NAME_ONLY,
            refund_policy_known=True,
        ),
    ),
    "sim_stay_site": (
        "Stays (simulated booking site)",
        SupplierCapabilities(
            kind=BookingKind.STAY,
            mode=None,
            channel=SupplierChannel.AGENT,
            max_party_per_purchase=None,
            required_traveller_fields=NAME_ONLY,
        ),
    ),
    "sim_activity": (
        "Activities (simulated marketplace)",
        SupplierCapabilities(
            kind=BookingKind.ACTIVITY,
            mode=None,
            channel=SupplierChannel.AGENT,
            max_party_per_purchase=None,
            required_traveller_fields=frozenset(),
        ),
    ),
}


def sim_supplier(
    supplier_id: str,
    clock: Clock,
    behaviour: SimBehaviour | None = None,
    capabilities: SupplierCapabilities | None = None,
) -> SimSupplier:
    """One of the standard simulators by id (`SIM_CAPABILITIES`), optionally reconfigured."""
    display_name, standard = SIM_CAPABILITIES[supplier_id]
    return SimSupplier(
        id=supplier_id,
        display_name=display_name,
        capabilities=capabilities or standard,
        clock=clock,
        behaviour=behaviour or SimBehaviour(),
    )
