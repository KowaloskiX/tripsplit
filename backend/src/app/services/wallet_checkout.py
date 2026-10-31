"""The "Pay my share" sheet in one call: top the wallet up by exactly what is missing, then pay
the share from it once the (dummy) bank confirms. And "I'll pay for everyone": the organizer
covers every outstanding share the same way."""

from dataclasses import dataclass

from app.core.domain.errors import TripError
from app.core.domain.packages import format_money
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import EventActor, EventKind, MemberRole, TripStatus
from app.core.domain.wallet import (
    InsufficientFunds,
    TopUpFailure,
    shortfall,
    top_up_for_shortfall,
)
from app.db.identifiers import identifier_of, to_object_id, to_text
from app.models.trips import Trip, TripMember
from app.repositories.trips import (
    ContributionRepository,
    EventRepository,
    MemberRepository,
    TripRepository,
)
from app.services.contributions import ContributionService, PaymentView
from app.services.trip_access import load_access
from app.services.wallet import TopUpRequest, WalletEntryView, WalletService


@dataclass(frozen=True, slots=True)
class CheckoutView:
    """Either the share is paid now (`payment`), or a top-up is on its way (`top_up`) and the
    share is paid as soon as it is credited."""

    payment: PaymentView | None
    top_up: WalletEntryView | None


type CheckoutError = TripError | InsufficientFunds | TopUpFailure


class WalletCheckoutService:
    def __init__(self, contributions: ContributionService, wallet: WalletService) -> None:
        self.contributions = contributions
        self.wallet = wallet
        self.trips = TripRepository()
        self.members = MemberRepository()

    async def top_up_and_pay(
        self, trip_id: str, user_id: str, request: TopUpRequest
    ) -> Result[CheckoutView, CheckoutError]:
        """`request.amount_minor` is ignored: the top-up is the shortfall, computed here."""
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        trip, member = access.value.trip, access.value.member
        due = await self.contributions.outstanding(trip, member)
        if not isinstance(due, Ok):
            return due
        missing = shortfall(await self.wallet.balance(user_id), due.value)
        if missing == 0:
            paid = await self.contributions.pay_for(trip, member)
            return (
                Ok(CheckoutView(payment=paid.value, top_up=None)) if isinstance(paid, Ok) else paid
            )

        async def pay_once_credited() -> object:
            return await self.contributions.pay(trip_id, user_id)

        started = await self.wallet.start_top_up(
            user_id,
            TopUpRequest(
                amount_minor=top_up_for_shortfall(missing),
                method=request.method,
                blik_code=request.blik_code,
                card_last4=request.card_last4,
            ),
            trip_id=to_text(identifier_of(trip)),
            after=pay_once_credited,
        )
        if isinstance(started, Err):
            return started
        return Ok(CheckoutView(payment=None, top_up=started.value))


@dataclass(frozen=True, slots=True)
class PayAllView:
    """ "I'll pay for everyone": the shares paid now (`payments`), or a top-up of the whole
    shortfall on its way (`top_up`) after which every outstanding share is paid."""

    total_minor: int  # what the organizer covers
    shares: int  # how many members' shares
    payments: tuple[PaymentView, ...]
    top_up: WalletEntryView | None

    @property
    def all_paid(self) -> bool:
        return any(payment.all_paid for payment in self.payments)


class PayAllService:
    """The organizer pays every outstanding share of the trip from their own wallet."""

    def __init__(self, contributions: ContributionService, wallet: WalletService) -> None:
        self.contributions = contributions
        self.wallet = wallet
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.shares = ContributionRepository()
        self.events = EventRepository()

    async def pay_everyone(
        self, trip_id: str, user_id: str, request: TopUpRequest
    ) -> Result[PayAllView, CheckoutError]:
        """Tops the organizer's wallet up by the total shortfall (when it is short) and pays
        each member's outstanding share from it, recorded as paid by the organizer."""
        access = await load_access(trip_id, user_id, trips=self.trips, members=self.members)
        if not isinstance(access, Ok):
            return access
        trip, organizer = access.value.trip, access.value.member
        if organizer.role is not MemberRole.ORGANIZER:
            return Err(TripError.NOT_ORGANIZER)
        if trip.status is not TripStatus.PAYING:
            return Err(TripError.INVALID_STATE)
        owed = await self._owed(trip)
        if not owed:
            return Err(TripError.ALREADY_PAID)
        total = sum(due for _, due in owed)
        await self.events.add(
            identifier_of(trip),
            EventKind.MESSAGE,
            EventActor.MEMBER,
            f"{organizer.display_name} is paying for everyone: "
            f"{format_money(total, trip.currency)} for {len(owed)} share(s).",
            payload={"pay_all": True, "total_minor": total, "shares": len(owed)},
            actor_user_id=organizer.user_id,
        )
        missing = shortfall(await self.wallet.balance(user_id), total)
        if missing == 0:
            paid = await self._pay_all(trip_id, organizer)
            if isinstance(paid, Err):
                return paid
            return Ok(PayAllView(total, len(owed), paid.value, None))

        async def pay_once_credited() -> object:
            return await self._pay_all(trip_id, organizer)

        started = await self.wallet.start_top_up(
            user_id,
            TopUpRequest(
                amount_minor=top_up_for_shortfall(missing),
                method=request.method,
                blik_code=request.blik_code,
                card_last4=request.card_last4,
            ),
            trip_id=trip_id,
            after=pay_once_credited,
        )
        if isinstance(started, Err):
            return started
        return Ok(PayAllView(total, len(owed), (), started.value))

    async def _owed(self, trip: Trip) -> list[tuple[TripMember, int]]:
        """Current members with something still to pay, in membership order."""
        shares = {c.user_id: c for c in await self.shares.for_trip(identifier_of(trip))}
        owed = []
        for member in await self.members.for_trip(identifier_of(trip)):
            share = shares.get(member.user_id)
            if share is not None and share.amount_minor > share.paid_minor:
                owed.append((member, share.amount_minor - share.paid_minor))
        return owed

    async def _pay_all(
        self, trip_id: str, organizer: TripMember
    ) -> Result[tuple[PaymentView, ...], TripError | InsufficientFunds]:
        trip_oid = to_object_id(trip_id)
        trip = await self.trips.get(trip_oid) if trip_oid is not None else None
        if trip is None:
            return Err(TripError.NOT_FOUND)
        payments: list[PaymentView] = []
        for member, _ in await self._owed(trip):
            paid = await self.contributions.pay_for(trip, member, payer=organizer)
            if isinstance(paid, Err):
                if paid.error is TripError.ALREADY_PAID:
                    continue  # paid by themselves meanwhile
                return paid if not payments else Ok(tuple(payments))
            payments.append(paid.value)
        return Ok(tuple(payments))
