"""Keeping a booking's price true to its supplier: holds, re-quotes and the price-change path.

Everything here reads the supplier's capabilities, never its name:

- `supports_hold` with HOLDS=on -> a hold is placed when the vote closes, so the price is
  locked while the group pays (`hold_needs_traveller_details`: only once every passenger's
  required details are in, otherwise when the purchase starts). A hold that lapsed before the
  purchase is announced (HOLD_EXPIRED) and placed again — at whatever the supplier now asks.
- otherwise (HOLDS=off is the default) -> the booking is re-quoted right before the purchase
  starts, unless its price was confirmed by the supplier within the capability's `quote_ttl`;
  an API supplier then books without a hold when the summary is approved.

A new price beyond the tolerance takes the ONE re-split path: the booking's amount changes, the
shares are re-split, the feed gets PRICE_CHANGED, and a rise that leaves somebody owing sends
the trip back to PAYING (Rule #1). A supplier that no longer offers it fails the booking.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.bookings import (
    BOOKING_STATUSES_THAT_START,
    exceeds_tolerance,
    format_money,
)
from app.core.domain.errors import BookingError
from app.core.domain.suppliers import (
    SupplierCapabilities,
    hold_is_live,
    mode_noun,
    quote_is_fresh,
)
from app.core.domain.trips import BookingStatus, EventActor, EventKind, TripStatus
from app.db.client import Database
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_text
from app.models.bookings import Booking
from app.models.trips import Trip, TripMember
from app.repositories.bookings import BookingRepository
from app.repositories.trips import EventRepository, MemberRepository, TripRepository
from app.services.resplit import Resplit, resplit_payload, resplit_shares
from app.services.travellers import TravellerService
from app.suppliers.ports import OfferRef, SupplierAdapter, SupplierUnavailableError
from app.suppliers.registry import SupplierRegistry

logger = logging.getLogger(__name__)


class _Unheld(Enum):
    """A hold that was not placed because the supplier could not (or would not) give one."""

    UNHELD = "unheld"


_UNHELD = _Unheld.UNHELD

type Clock = Callable[[], datetime]

# An item bought as at least this many purchases is checked all-or-nothing.
MIN_SPLIT_PARTS = 2


def offer_of(booking: Booking) -> OfferRef:
    return OfferRef(
        supplier_id=booking.supplier_id,
        offer_ref=booking.offer_ref,
        supplier_data=booking.supplier_data,
    )


def passengers_of(booking: Booking, members: list[TripMember]) -> list[TripMember]:
    """The members travelling on THIS purchase, in vault order. A booking created before
    passengers were recorded per purchase covers the whole trip."""
    if not booking.passenger_user_ids:
        return members
    by_user = {member.user_id: member for member in members}
    return [by_user[user_id] for user_id in booking.passenger_user_ids if user_id in by_user]


def _when(moment: datetime) -> str:
    return f"{moment:%a %d %b %H:%M} UTC"


class SupplierPrices:
    def __init__(
        self,
        db: Database,
        suppliers: SupplierRegistry,
        *,
        clock: Clock = utc_now,
        price_tolerance_percent: float = 0.0,
        holds: bool = False,
    ) -> None:
        self.db = db
        # HOLDS=on: suppliers that support holds lock the price at voting close. Off: nothing
        # is held, every purchase re-quotes right before it starts.
        self.holds = holds
        self.suppliers = suppliers
        self.clock = clock
        self.price_tolerance_percent = price_tolerance_percent
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.bookings = BookingRepository()
        self.events = EventRepository()
        self.travellers = TravellerService()

    def adapter_of(self, booking: Booking) -> SupplierAdapter | None:
        return self.suppliers.get(booking.supplier_id) if booking.supplier_id else None

    def capabilities_of(self, booking: Booking) -> SupplierCapabilities | None:
        adapter = self.adapter_of(booking)
        return adapter.capabilities if adapter is not None else None

    # ---- holds at voting close ------------------------------------------------------------

    async def place_holds(self, trip: Trip) -> None:
        """Holds every booking whose supplier supports it. Called right after the vote closed,
        outside its transaction: a hold is a call to a supplier and cannot be replayed.
        Nothing happens with holds off."""
        if not self.holds:
            return
        members = await self.members.for_trip(identifier_of(trip))
        for booking in await self.bookings.for_trip(identifier_of(trip)):
            adapter = self.adapter_of(booking)
            if adapter is None or not adapter.capabilities.supports_hold:
                continue
            if booking.status is not BookingStatus.PENDING:
                continue
            if await self._hold_waits_for_details(booking, adapter, members):
                continue  # placed when the purchase starts (see `refresh`)
            await self._hold(trip, booking, adapter, members, expired=False)

    async def _hold_waits_for_details(
        self, booking: Booking, adapter: SupplierAdapter, members: list[TripMember]
    ) -> bool:
        """A supplier whose hold names the passengers cannot hold before they all entered
        the details it requires."""
        capabilities = adapter.capabilities
        if not capabilities.hold_needs_traveller_details:
            return False
        missing = await self.travellers.missing(
            passengers_of(booking, members), capabilities.required_traveller_fields
        )
        return bool(missing)

    # ---- right before a purchase ----------------------------------------------------------

    async def refresh(self, trip: Trip, booking: Booking) -> BookingError | None:
        """Makes the booking's price binding before a purchase starts. None = go ahead.

        A booking without a supplier plugin (written before suppliers were plugins) keeps its
        stored amount: the human still approves the binding summary.
        """
        if not booking.supplier_id:
            return None
        adapter = self.adapter_of(booking)
        if adapter is None:
            return BookingError.SUPPLIER_UNKNOWN
        members = await self.members.for_trip(identifier_of(trip))
        if adapter.capabilities.supports_hold and hold_is_live(
            booking.hold_expires_at, self.clock()
        ):
            return None
        if adapter.capabilities.supports_hold and self.holds:
            held = await self._hold(
                trip, booking, adapter, members, expired=booking.hold_ref is not None
            )
            if held is not _UNHELD:
                return held
            # The supplier could not hold this one: a fresh quote binds the price instead,
            # and the purchase pays it directly.
        if quote_is_fresh(booking.quoted_at, adapter.capabilities.quote_ttl, self.clock()):
            return None  # quoted moments ago (e.g. a rebooking): still binding
        return await self._requote(trip, booking, adapter, members)

    async def refresh_split(self, trip: Trip, parts: list[Booking]) -> BookingError | None:
        """All or nothing for an item bought as several purchases (a train for 6 at a cap of
        5 is 3 + 3): every startable part is re-quoted BEFORE any of them starts. One part
        gone -> none starts, every part fails and the item is SOLD_OUT, so half the group is
        never ticketed. Otherwise each new price is applied (the parts' quotes are then fresh,
        so their own starts do not ask again). None = go ahead.

        Parts holding a live hold, or whose price is still fresh, are not asked again; with
        holds on, the availability check does not apply the quote (the hold placed at the
        start binds the price instead)."""
        startable = [part for part in parts if part.status in BOOKING_STATUSES_THAT_START]
        if len(startable) < MIN_SPLIT_PARTS:
            return None
        members = await self.members.for_trip(identifier_of(trip))
        quoted: list[tuple[Booking, int]] = []
        for part in startable:
            adapter = self.adapter_of(part)
            if adapter is None or not self._needs_quote(part, adapter):
                continue
            party = len(passengers_of(part, members)) or len(members)
            try:
                quote = await adapter.quote(offer_of(part), party)
            except SupplierUnavailableError:
                logger.warning("supplier %s unavailable for a re-quote", part.supplier_id)
                continue
            if quote is None:
                return await self._split_sold_out(trip, startable)
            if not (adapter.capabilities.supports_hold and self.holds):
                quoted.append((part, quote.price_minor))
        # Every part takes its new price before answering, so a rise is topped up once.
        outcomes = [
            await self._apply(
                trip,
                await self.bookings.get(identifier_of(part)) or part,
                price,
                {"quoted_at": self.clock()},
            )
            for part, price in quoted
        ]
        return next((outcome for outcome in outcomes if outcome is not None), None)

    def _needs_quote(self, booking: Booking, adapter: SupplierAdapter) -> bool:
        capabilities = adapter.capabilities
        now = self.clock()
        if capabilities.supports_hold and hold_is_live(booking.hold_expires_at, now):
            return False
        return not quote_is_fresh(booking.quoted_at, capabilities.quote_ttl, now)

    async def _split_sold_out(self, trip: Trip, parts: list[Booking]) -> BookingError:
        failed = [
            part
            for part in parts
            if await self.bookings.update_if_status(
                part, BOOKING_STATUSES_THAT_START, {"status": BookingStatus.FAILED}
            )
        ]
        if failed:
            first = failed[0]
            await self.events.add(
                identifier_of(trip),
                EventKind.BOOKING_FAILED,
                EventActor.AGENT,
                f"{first.supplier} no longer has seats for the whole group on this "
                f"{mode_noun(first.mode)}: I bought none of its {len(parts)} purchases, so "
                "nobody is left without a ticket. Pick another option or book it by hand.",
                payload={
                    "booking_id": to_text(identifier_of(first)),
                    "booking_ids": [to_text(identifier_of(part)) for part in failed],
                    "sold_out": True,
                },
            )
        return BookingError.SOLD_OUT

    async def _requote(
        self, trip: Trip, booking: Booking, adapter: SupplierAdapter, members: list[TripMember]
    ) -> BookingError | None:
        party = len(passengers_of(booking, members)) or len(members)
        try:
            quote = await adapter.quote(offer_of(booking), party)
        except SupplierUnavailableError:
            # "Could not ask" is not "sold out": keep the stored price, the summary decides.
            logger.warning("supplier %s unavailable for a re-quote", booking.supplier_id)
            return None
        if quote is None:
            return await self._sold_out(trip, booking)
        changes: dict[str, Any] = {"quoted_at": self.clock()}
        if booking.hold_ref is not None:  # a lapsed hold must not reach the purchase
            changes |= {"hold_ref": None, "hold_expires_at": None}
        return await self._apply(trip, booking, quote.price_minor, changes)

    async def _hold(
        self,
        trip: Trip,
        booking: Booking,
        adapter: SupplierAdapter,
        members: list[TripMember],
        *,
        expired: bool,
    ) -> BookingError | _Unheld | None:
        """Places a hold. None = held; `_UNHELD` = the supplier could not be asked or would
        not hold this offer (nothing changed)."""
        if expired and booking.hold_expires_at is not None:
            await self._say(
                trip,
                EventKind.HOLD_EXPIRED,
                f"The hold on {booking.title} expired on {_when(booking.hold_expires_at)} "
                f"before the purchase. Asking {booking.supplier} for a new one.",
                booking,
                expired_at=booking.hold_expires_at.isoformat(),
            )
        passengers = passengers_of(booking, members)
        details = await self.travellers.details_for(passengers)
        try:
            hold = await adapter.hold(
                offer_of(booking), [details[member.user_id] for member in passengers]
            )
        except SupplierUnavailableError:
            logger.warning("supplier %s unavailable for a hold", booking.supplier_id)
            return _UNHELD
        if hold is None:
            return await self._sold_out(trip, booking)
        changes: dict[str, Any] = {
            "hold_ref": hold.ref,
            "hold_expires_at": hold.expires_at,
            "quoted_at": self.clock(),
        }
        outcome = await self._apply(trip, booking, hold.price_minor, changes)
        if outcome in (None, BookingError.PRICE_CHANGED):
            await self._say(
                trip,
                EventKind.HOLD_PLACED,
                f"{booking.supplier} holds {booking.title} at "
                f"{format_money(hold.price_minor, trip.currency)} until {_when(hold.expires_at)}.",
                booking,
                hold_expires_at=hold.expires_at.isoformat(),
            )
        return outcome

    async def _sold_out(self, trip: Trip, booking: Booking) -> BookingError:
        if await self.bookings.update_if_status(
            booking, BOOKING_STATUSES_THAT_START, {"status": BookingStatus.FAILED}
        ):
            await self._say(
                trip,
                EventKind.BOOKING_FAILED,
                f"{booking.supplier} no longer offers {booking.title}. Pick another option "
                "or book it by hand.",
                booking,
            )
        return BookingError.SOLD_OUT

    async def _apply(
        self, trip: Trip, booking: Booking, quoted: int, changes: dict[str, Any]
    ) -> BookingError | None:
        """Takes the supplier's price. Within the tolerance only `changes` are written; beyond
        it the amount moves and the shares are re-split (see the module docstring)."""
        previous = booking.amount_minor
        if not exceeds_tolerance(previous, quoted, self.price_tolerance_percent):
            moved = await self.bookings.update_if(
                booking, {"status": {"$in": list(BOOKING_STATUSES_THAT_START)}}, changes
            )
            return None if moved else BookingError.BOOKING_NOT_STARTABLE

        async def write(session: AsyncClientSession) -> Resplit | None:
            # Conditioned on the amount and status read before the quote: of two concurrent
            # starts only one applies the new price.
            moved = await self.bookings.update_if(
                booking,
                {"amount_minor": previous, "status": {"$in": list(BOOKING_STATUSES_THAT_START)}},
                {**changes, "amount_minor": quoted},
                session,
            )
            if not moved:
                return None
            fresh = await self.trips.get(identifier_of(trip), session) or trip
            bookings = await self.bookings.for_trip(identifier_of(trip), session)
            total = sum(b.amount_minor for b in bookings if b.status is not BookingStatus.CANCELLED)
            plan = await resplit_shares(fresh, total, session, announce=False)
            if plan.owes and fresh.status in (TripStatus.BOOKING, TripStatus.REBOOKING):
                await self.trips.set_status(fresh, TripStatus.PAYING, session)
            await self._say_price_changed(trip, booking, previous, quoted, plan, session)
            return plan

        plan = await self.db.in_transaction(write)
        if plan is None:
            return BookingError.BOOKING_NOT_STARTABLE
        return BookingError.PRICE_CHANGED if plan.owes else None

    async def _say_price_changed(
        self,
        trip: Trip,
        booking: Booking,
        previous_minor: int,
        current: int,
        plan: Resplit,
        session: AsyncClientSession,
    ) -> None:
        money = trip.currency
        rose = current > previous_minor
        verb = "raised" if rose else "lowered"
        message = (
            f"{booking.supplier} {verb} the price of {booking.title} from "
            f"{format_money(previous_minor, money).removesuffix(' ' + money)} to "
            f"{format_money(current, money)}"
        )
        if plan.shares:
            each = max(abs(share.change.delta_minor) for share in plan.shares)
            message += f", {format_money(each, money)} {'more' if rose else 'less'} each."
        else:
            message += "."
        if plan.owes:
            message += " Top up and I will buy it."
        elif plan.refunds:
            message += " The difference will be refunded. Buying it now."
        else:
            message += " Buying it now."
        payload = {
            **resplit_payload(plan),
            "booking_id": to_text(identifier_of(booking)),
            "previous_amount_minor": previous_minor,
            "amount_minor": current,
        }
        await self.events.add(
            identifier_of(trip),
            EventKind.PRICE_CHANGED,
            EventActor.AGENT,
            message[:4000],
            payload=payload,
            session=session,
        )

    async def _say(
        self, trip: Trip, kind: EventKind, message: str, booking: Booking, **extra: str
    ) -> None:
        await self.events.add(
            identifier_of(trip),
            kind,
            EventActor.AGENT,
            message[:4000],
            payload={"booking_id": to_text(identifier_of(booking)), **extra},
        )
