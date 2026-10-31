"""HTTP for shares and payments. Zero business logic."""

from fastapi import APIRouter
from starlette import status

from app.core.domain.wallet import PaymentMethod
from app.core.errors_http import ErrorResponse
from app.routes.dependencies import ContributionServiceDep, CurrentUser, WalletCheckoutServiceDep
from app.routes.errors import payment_value
from app.schemas.trips import PaymentResponse
from app.schemas.wallet import CheckoutResponse, InsufficientFundsResponse, TopUpAndPayRequest
from app.services.wallet import TopUpRequest

router = APIRouter(prefix="/trips/{trip_id}/contributions", tags=["contributions"])


@router.post(
    "/pay",
    operation_id="contributions-pay",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        # `insufficient_funds` carries `shortfall_minor`.
        status.HTTP_409_CONFLICT: {"model": InsufficientFundsResponse},
    },
)
async def pay_my_share(
    trip_id: str, service: ContributionServiceDep, user: CurrentUser
) -> PaymentResponse:
    """Charges the caller's outstanding share; the last payment moves the trip to booking."""
    return PaymentResponse.model_validate(payment_value(await service.pay(trip_id, user.id)))


@router.post(
    "/top-up-and-pay",
    operation_id="contributions-top-up-and-pay",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": InsufficientFundsResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def top_up_and_pay(
    trip_id: str,
    payload: TopUpAndPayRequest,
    service: WalletCheckoutServiceDep,
    user: CurrentUser,
) -> CheckoutResponse:
    """Tops the wallet up by exactly the shortfall (BLIK / card) and pays the share once the
    bank confirms; pays right away when the wallet already covers it."""
    result = await service.top_up_and_pay(
        trip_id,
        user.id,
        TopUpRequest(
            amount_minor=0,
            method=PaymentMethod(payload.method),
            blik_code=payload.blik_code,
            card_last4=payload.card_last4,
        ),
    )
    return CheckoutResponse.model_validate(payment_value(result))
