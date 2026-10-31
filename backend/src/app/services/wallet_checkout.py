"""The "Pay my share" sheet in one call: top the wallet up by exactly what is missing, then pay
the share from it once the (dummy) bank confirms."""

from dataclasses import dataclass

from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.wallet import (
    InsufficientFunds,
    TopUpFailure,
    shortfall,
    top_up_for_shortfall,
)
from app.db.identifiers import identifier_of, to_text
from app.repositories.trips import MemberRepository, TripRepository
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
