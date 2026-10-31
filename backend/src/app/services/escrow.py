"""The trip escrow at the payment partner: where every share goes and every purchase is paid
from. TripSplit instructs; the (simulated) licensed partner holds and moves the money.

- voting close: `open` — one escrow wallet per trip, a release target (the total) and `pay_by`;
- a share: member wallet -> escrow (`WalletPayments.charge` -> `collect`);
- an API purchase: `pay_supplier` — a payout from the escrow at the approval;
- an agent purchase: `issue_card` at launch (details into the agent's vault, unfunded),
  `activate_card` at the approval (exactly the amount reserved), charged once by the site,
  `close_card` afterwards (unused funds return to the escrow);
- a cancelled purchase: `return_supplier_funds` (payout reversed / card charge refunded);
- refunds: escrow -> member wallets; leftovers at BOOKED pro rata; a missed `pay_by` refunds
  every paid share and EXPIRES the trip (`expire_overdue`).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from secrets import token_hex

from beanie import PydanticObjectId

from app.core.domain.escrow import (
    DEFAULT_CARD_TTL,
    CardStatus,
    EscrowTotals,
    PurchasePayment,
    card_limit_minor,
    default_pay_by,
    pro_rata,
)
from app.core.domain.packages import format_money
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import (
    BookingStatus,
    ContributionStatus,
    EventActor,
    EventKind,
    TripStatus,
)
from app.core.domain.wallet import WALLET_CURRENCY, InsufficientFunds
from app.db.documents import utc_now
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.bookings import Booking
from app.models.trips import Trip
from app.payments.partner import (
    CardCharge,
    CardSecrets,
    LedgerKind,
    Movement,
    PartnerError,
    PaymentPartner,
    SupplierAccount,
    TransferTag,
    VirtualCard,
    WalletOwnerKind,
)
from app.repositories.bookings import BookingRepository
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    TripRepository,
)
from app.services.supplier_prices import Clock
from app.services.wallet import PotView, WalletService

logger = logging.getLogger(__name__)

# Trips the funding deadline applies to: still collecting shares, nothing bought yet.
_DEADLINE_STATUSES = (TripStatus.PAYING,)
_REFUND_TAGS = frozenset(
    {TransferTag.REFUND.value, TransferTag.DEADLINE_REFUND.value, TransferTag.LEFTOVER.value}
)


@dataclass(frozen=True, slots=True)
class IssuedCard:
    card: VirtualCard
    # Straight into the agent's private vault; never stored or logged by TripSplit.
    secrets: CardSecrets


def card_vault(secrets: CardSecrets) -> dict[str, str]:
    """The `card_*` vault keys the agent types on the supplier's payment page."""
    return {
        "card_number": secrets.pan,
        "card_expiry": f"{secrets.exp_month:02d}/{secrets.exp_year % 100:02d}",
        "card_cvc": secrets.cvc,
        "card_holder": "TripSplit Pay trip card",
    }


def card_charge_from_vault(vault: dict[str, str], amount_minor: int, merchant: str) -> CardCharge:
    """What a supplier's checkout sends to the card network from the typed card fields."""
    month, _, year = vault.get("card_expiry", "").partition("/")
    return CardCharge(
        pan=vault.get("card_number", "").replace(" ", ""),
        exp_month=int(month) if month.isdigit() else 0,
        exp_year=2000 + int(year) if year.isdigit() else 0,
        cvc=vault.get("card_cvc", ""),
        amount_minor=amount_minor,
        merchant=merchant,
    )


def escrow_totals(
    statement: list[Movement], cards: list[VirtualCard], wallet_id: str
) -> EscrowTotals:
    """The escrow's money from the partner's own records, each figure computed independently
    of the wallet balance — so `held == collected - paid - refunded` is a real check."""
    collected = refunded = payouts = 0
    for move in statement:
        incoming = move.credit_wallet_id == wallet_id
        if move.kind is LedgerKind.TRANSFER and incoming and move.tag == TransferTag.SHARE.value:
            collected += move.amount_minor
        elif move.kind is LedgerKind.TRANSFER and not incoming and move.tag in _REFUND_TAGS:
            refunded += move.amount_minor
        elif move.kind is LedgerKind.PAYOUT and not incoming:
            payouts += move.amount_minor
        elif (move.kind is LedgerKind.PAYOUT_REVERSAL and incoming) or (
            move.kind is LedgerKind.CARD_REFUND and incoming
        ):
            payouts -= move.amount_minor
    card_spend = sum(card.spent_minor for card in cards if card.status is CardStatus.USED)
    reserved = sum(card.limit_minor for card in cards if card.status is CardStatus.ACTIVE)
    balance = 0
    if statement:
        last = statement[-1]
        balance = (
            last.credit_balance_after_minor
            if last.credit_wallet_id == wallet_id
            else last.debit_balance_after_minor
        ) or 0
    return EscrowTotals(
        collected_minor=collected,
        paid_to_suppliers_minor=payouts + card_spend,
        refunded_minor=refunded,
        reserved_minor=reserved,
        balance_minor=balance,
    )


class EscrowService:
    def __init__(
        self,
        partner: PaymentPartner,
        wallet: WalletService,
        *,
        clock: Clock = utc_now,
        card_ttl: timedelta = DEFAULT_CARD_TTL,
    ) -> None:
        self.partner = partner
        self.wallet = wallet
        self.clock = clock
        self.card_ttl = card_ttl
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.contributions = ContributionRepository()
        self.bookings = BookingRepository()
        self.events = EventRepository()

    # ---- the escrow wallet ----------------------------------------------------------------

    async def open(self, trip: Trip, *, announce: bool = True) -> str:
        """The trip's escrow wallet (opened once), its release target and the deadline."""
        trip_oid = identifier_of(trip)
        existed = trip.escrow_wallet_id is not None
        wallet_id = trip.escrow_wallet_id or await self.partner.create_wallet(
            WalletOwnerKind.TRIP_ESCROW, f"trip:{to_text(trip_oid)}", trip.currency
        )
        changes: dict[str, object] = {}
        if not existed:
            changes["escrow_wallet_id"] = wallet_id
        if trip.pay_by is None and trip.status is TripStatus.PAYING:
            changes["pay_by"] = default_pay_by(self.clock())
        if changes:
            await self.trips.update(trip, changes)
        await self.sync_target(trip_oid)
        if announce and not existed and trip.pay_by is not None:
            await self.events.add(
                trip_oid,
                EventKind.ESCROW_OPENED,
                EventActor.AGENT,
                "TripSplit Pay (our simulated licensed payment partner) opened the trip escrow: "
                "your shares are held there, never by TripSplit, and paid to suppliers only "
                f"once everyone has paid. Pay by {trip.pay_by:%a %d %b, %H:%M} UTC — otherwise "
                "every paid share goes back automatically.",
                payload={"escrow_wallet_id": wallet_id, "pay_by": trip.pay_by.isoformat()},
            )
        return wallet_id

    async def escrow_of(self, trip_id: str) -> str | None:
        trip_oid = to_object_id(trip_id)
        trip = await self.trips.get(trip_oid) if trip_oid is not None else None
        if trip is None:
            return None
        return await self.open(trip, announce=False)

    async def sync_target(self, trip_oid: PydanticObjectId) -> None:
        """The escrow releases nothing until the net share transfers cover every share."""
        trip = await self.trips.get(trip_oid)
        if trip is None or trip.escrow_wallet_id is None:
            return
        target = sum(c.amount_minor for c in await self.contributions.for_trip(trip_oid))
        await self.partner.set_release_target(trip.escrow_wallet_id, target)

    # ---- shares and refunds ---------------------------------------------------------------

    async def collect(
        self, trip_id: str, user_id: str, amount_minor: int
    ) -> Result[str, InsufficientFunds]:
        escrow = await self.escrow_of(trip_id)
        if escrow is None:
            return Err(InsufficientFunds(shortfall_minor=amount_minor))
        # One key per charge: a payer may cover several equal shares in a row (pay for
        # everyone), and each must move money. The contribution's compare-and-set (not the key)
        # is what stops a share from being paid twice.
        return await self.wallet.charge(
            user_id,
            trip_id,
            amount_minor,
            to_wallet=escrow,
            idempotency_key=f"share:{trip_id}:{user_id}:{token_hex(8)}",
        )

    async def refund(
        self, trip_id: str, user_id: str, amount_minor: int, tag: TransferTag, reference: str
    ) -> Result[str, PartnerError]:
        escrow = await self.escrow_of(trip_id)
        if escrow is None:
            return Err(PartnerError.WALLET_NOT_FOUND)
        return await self.wallet.receive(
            user_id,
            trip_id,
            amount_minor,
            from_wallet=escrow,
            tag=tag,
            idempotency_key=f"{tag.value}:{trip_id}:{user_id}:{token_hex(8)}",
            reference=reference,
        )

    # ---- purchases ------------------------------------------------------------------------

    async def pay_supplier(self, trip: Trip, booking: Booking) -> Result[str, PartnerError]:
        """API supplier: a payout of the approved total from the escrow (Rule #1 enforced by
        the partner too). Recorded on the booking; announced in the feed."""
        escrow = await self.open(trip, announce=False)
        attempt = booking.payment_attempts + 1
        await self.bookings.update(booking, {"payment_attempts": attempt})
        paid = await self.partner.payout(
            escrow,
            SupplierAccount(
                supplier_id=booking.supplier_id or "supplier", display_name=booking.supplier
            ),
            booking.amount_minor,
            reference=booking.title,
            idempotency_key=f"payout:{to_text(identifier_of(booking))}:{attempt}",
        )
        if isinstance(paid, Err):
            return paid
        await self.bookings.update(
            booking,
            {
                "payment_kind": PurchasePayment.PAYOUT,
                "payment_ref": paid.value.id,
                "card_last4": None,
            },
        )
        await self._say_paid(
            trip,
            booking,
            f"TripSplit Pay paid {format_money(booking.amount_minor, trip.currency)} from the "
            f"trip escrow to {booking.supplier} (payout {paid.value.id}).",
        )
        return Ok(paid.value.id)

    async def reverse_payout(self, booking: Booking) -> None:
        """The supplier purchase failed after the payout: the supplier sends it back."""
        if booking.payment_kind is not PurchasePayment.PAYOUT or not booking.payment_ref:
            return
        await self.partner.reverse_payout(
            booking.payment_ref, idempotency_key=f"reverse:{booking.payment_ref}"
        )
        await self.bookings.update(booking, {"payment_kind": None, "payment_ref": None})

    async def issue_card(
        self, trip: Trip, booking: Booking, run_id: str
    ) -> Result[IssuedCard, PartnerError]:
        """Agent supplier: a single-use card for exactly this purchase, issued INACTIVE when
        the agent starts. Its details go into the agent's vault; nothing is reserved yet."""
        escrow = await self.open(trip, announce=False)
        issued = await self.partner.issue_virtual_card(
            escrow,
            card_limit_minor(booking.amount_minor),
            f"{booking.supplier}: {booking.title}",
            self.card_ttl,
            idempotency_key=f"card:{run_id}",
        )
        if isinstance(issued, Err):
            return issued
        card = issued.value
        secrets = await self.partner.reveal_card(card.card_id)
        if secrets is None:
            return Err(PartnerError.CARD_NOT_FOUND)
        await self.bookings.update(
            booking,
            {
                "payment_kind": PurchasePayment.VIRTUAL_CARD,
                "payment_ref": card.card_id,
                "card_last4": card.pan_last4,
            },
        )
        return Ok(IssuedCard(card=card, secrets=secrets))

    async def activate_card(
        self, trip: Trip, booking: Booking
    ) -> Result[VirtualCard, PartnerError]:
        """At the approval: the card is funded with exactly its limit (Rule #1 at the partner)."""
        if booking.payment_kind is not PurchasePayment.VIRTUAL_CARD or not booking.payment_ref:
            return Err(PartnerError.CARD_NOT_FOUND)
        await self.sync_target(identifier_of(trip))
        return await self.partner.activate_card(
            booking.payment_ref, idempotency_key=f"activate:{booking.payment_ref}"
        )

    async def card_of(self, booking: Booking) -> VirtualCard | None:
        if booking.payment_kind is not PurchasePayment.VIRTUAL_CARD or not booking.payment_ref:
            return None
        return await self.partner.card_status(booking.payment_ref)

    async def settle_site_checkout(
        self, trip: Trip, booking: Booking
    ) -> Result[VirtualCard | None, PartnerError]:
        """The supplier site's checkout charges the card for the booking amount — for runs
        that only SIMULATE the final click (the live demo). A card already charged by the
        site (the scripted agent) is left alone."""
        card = await self.card_of(booking)
        if card is None or card.status is CardStatus.USED:
            return Ok(card)
        secrets = await self.partner.reveal_card(card.card_id)
        if secrets is None:
            return Err(PartnerError.CARD_NOT_FOUND)
        charged = await self.partner.charge_card(
            card_charge_from_vault(card_vault(secrets), booking.amount_minor, booking.supplier),
            idempotency_key=f"charge:{card.card_id}",
        )
        if isinstance(charged, Err):
            return charged
        return Ok(await self.partner.card_status(card.card_id))

    async def close_card(self, booking: Booking) -> VirtualCard | None:
        """The run is over: a card still open closes, its funds go back to the escrow."""
        if booking.payment_kind is not PurchasePayment.VIRTUAL_CARD or not booking.payment_ref:
            return None
        return await self.partner.close_card(booking.payment_ref)

    async def announce_card_spend(self, trip: Trip, booking: Booking) -> None:
        card = await self.card_of(booking)
        if card is None or card.status is not CardStatus.USED:
            return
        await self._say_paid(
            trip,
            booking,
            f"The agent paid {booking.supplier} {format_money(card.spent_minor, trip.currency)} "
            f"with a single-use virtual card •••• {card.pan_last4} funded from the trip escrow; "
            "the card is closed now.",
        )

    async def return_supplier_funds(self, booking: Booking) -> None:
        """A cancelled purchase: the supplier returns what it was paid, into the escrow."""
        if booking.payment_kind is PurchasePayment.PAYOUT and booking.payment_ref:
            await self.partner.reverse_payout(
                booking.payment_ref, idempotency_key=f"reverse:{booking.payment_ref}"
            )
        elif booking.payment_kind is PurchasePayment.VIRTUAL_CARD and booking.payment_ref:
            card = await self.partner.card_status(booking.payment_ref)
            if card is not None and card.status is CardStatus.USED:
                await self.partner.refund_card_charge(
                    booking.payment_ref, idempotency_key=f"card_refund:{booking.payment_ref}"
                )
            elif card is not None:
                await self.partner.close_card(booking.payment_ref)

    async def _say_paid(self, trip: Trip, booking: Booking, message: str) -> None:
        await self.events.add(
            identifier_of(trip),
            EventKind.SUPPLIER_PAID,
            EventActor.AGENT,
            message,
            payload={
                "booking_id": to_text(identifier_of(booking)),
                "payment_kind": (booking.payment_kind or PurchasePayment.PAYOUT).value,
            },
        )

    # ---- leftovers and the deadline -------------------------------------------------------

    async def return_leftover(self, trip: Trip) -> int:
        """At BOOKED, whatever the escrow still holds (rounding, a card charged under its
        limit) goes back to the members pro rata to what they paid. The amount returned."""
        if trip.escrow_wallet_id is None:
            return 0
        trip_oid = identifier_of(trip)
        left = await self.partner.balance(trip.escrow_wallet_id)
        if left <= 0:
            return 0
        contributions = await self.contributions.for_trip(trip_oid)
        parts = pro_rata(left, [c.paid_minor for c in contributions])
        returned = 0
        for contribution, part in zip(contributions, parts, strict=True):
            if part <= 0:
                continue
            sent = await self.wallet.receive(
                to_text(contribution.user_id),
                to_text(trip_oid),
                part,
                from_wallet=trip.escrow_wallet_id,
                tag=TransferTag.LEFTOVER,
                idempotency_key=f"leftover:{to_text(trip_oid)}:{to_text(contribution.user_id)}:{part}",
                reference=f"Leftover from {trip.title}",
            )
            if isinstance(sent, Ok):
                returned += part
        if returned:
            await self.events.add(
                trip_oid,
                EventKind.REFUND_ISSUED,
                EventActor.AGENT,
                f"Everything is paid: {format_money(returned, trip.currency)} left in the trip "
                "escrow went back to your wallets, in proportion to what each of you paid.",
                payload={"amount_minor": returned, "leftover": True},
            )
        return returned

    async def expire_overdue(self, now: datetime | None = None) -> list[str]:
        """Every PAYING trip past its `pay_by` and not fully paid: refund each paid share from
        the escrow, then EXPIRE the trip. The trip ids that expired."""
        moment = now or self.clock()
        expired: list[str] = []
        for trip in await self.trips.overdue(_DEADLINE_STATUSES, moment):
            if await self._expire(trip):
                expired.append(to_text(identifier_of(trip)))
        return expired

    async def _expire(self, trip: Trip) -> bool:
        trip_oid = identifier_of(trip)
        contributions = await self.contributions.for_trip(trip_oid)
        if contributions and all(c.paid_minor >= c.amount_minor for c in contributions):
            return False  # fully paid: the all-paid transition is about to happen
        bought = any(
            b.status is BookingStatus.CONFIRMED for b in await self.bookings.for_trip(trip_oid)
        )
        if bought:
            return False  # a rebooking top-up round: nothing is unwound after a purchase
        # Claim the trip first, so a share paid meanwhile is refused (the trip is not PAYING).
        if not await self.trips.transition_status(trip_oid, TripStatus.PAYING, TripStatus.EXPIRED):
            return False
        names = {m.user_id: m.display_name for m in await self.members.for_trip(trip_oid)}
        refunded = 0
        for contribution in contributions:
            if contribution.paid_minor <= 0 or trip.escrow_wallet_id is None:
                continue
            amount = contribution.paid_minor
            sent = await self.wallet.receive(
                to_text(contribution.user_id),
                to_text(trip_oid),
                amount,
                from_wallet=trip.escrow_wallet_id,
                tag=TransferTag.DEADLINE_REFUND,
                idempotency_key=f"deadline:{to_text(trip_oid)}:{to_text(contribution.user_id)}",
                reference=f"Refund: {trip.title} was not fully paid in time",
            )
            if isinstance(sent, Err):
                logger.error("deadline refund failed for trip %s: %s", trip_oid, sent.error)
                continue
            refunded += amount
            await self.contributions.update(
                contribution, {"paid_minor": 0, "status": ContributionStatus.PENDING}
            )
        paid_names = [
            names.get(c.user_id, "a former member") for c in contributions if c.paid_minor > 0
        ]
        who = f" to {', '.join(paid_names)}" if paid_names else ""
        await self.events.add(
            trip_oid,
            EventKind.FUNDING_EXPIRED,
            EventActor.AGENT,
            "Not everyone paid by the deadline, so nothing was booked. TripSplit Pay returned "
            f"every paid share from the trip escrow ({format_money(refunded, trip.currency)}"
            f"{who}) to your wallets. Start a new trip whenever you are ready.",
            payload={"refunded_minor": refunded},
        )
        return True

    async def set_pay_by(self, trip: Trip, pay_by: datetime) -> None:
        await self.trips.update(trip, {"pay_by": pay_by})

    # ---- reads ----------------------------------------------------------------------------

    async def totals(self, trip: Trip) -> EscrowTotals | None:
        if trip.escrow_wallet_id is None:
            return None
        statement = await self.partner.statement(trip.escrow_wallet_id)
        cards = await self.partner.cards_funded_by(trip.escrow_wallet_id)
        totals = escrow_totals(statement, cards, trip.escrow_wallet_id)
        # The balance from the partner itself (the statement may be empty).
        balance = await self.partner.balance(trip.escrow_wallet_id)
        return EscrowTotals(
            collected_minor=totals.collected_minor,
            paid_to_suppliers_minor=totals.paid_to_suppliers_minor,
            refunded_minor=totals.refunded_minor,
            reserved_minor=totals.reserved_minor,
            balance_minor=balance,
        )

    async def pot(self, trip: Trip) -> PotView:
        totals = await self.totals(trip)
        target = sum(c.amount_minor for c in await self.contributions.for_trip(identifier_of(trip)))
        if totals is None:
            return PotView(
                collected_minor=0,
                spent_minor=0,
                refunded_minor=0,
                held_minor=0,
                pay_by=trip.pay_by,
                target_minor=target,
            )
        return PotView(
            collected_minor=totals.collected_minor,
            spent_minor=totals.paid_to_suppliers_minor,
            refunded_minor=totals.refunded_minor,
            held_minor=totals.held_minor,
            reserved_minor=totals.reserved_minor,
            escrow_wallet_id=trip.escrow_wallet_id,
            pay_by=trip.pay_by,
            funded_minor=totals.collected_minor - totals.refunded_minor,
            target_minor=target,
        )


__all__ = ["WALLET_CURRENCY", "EscrowService", "IssuedCard", "card_charge_from_vault", "card_vault"]
