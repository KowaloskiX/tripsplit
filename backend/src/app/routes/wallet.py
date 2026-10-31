"""HTTP for the wallet: balance + history, dummy top-ups and their polling. Zero logic."""

from fastapi import APIRouter
from starlette import status

from app.core.domain.wallet import PaymentMethod
from app.core.errors_http import ErrorResponse
from app.routes.dependencies import CurrentUser, WalletServiceDep
from app.routes.errors import payment_value
from app.schemas.wallet import TopUpRequest, WalletResponse, WalletTransactionResponse
from app.services.wallet import TopUpRequest as TopUp

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("", operation_id="wallet-read")
async def read_wallet(service: WalletServiceDep, user: CurrentUser) -> WalletResponse:
    """The caller's balance and their newest 50 ledger entries."""
    return WalletResponse.model_validate(await service.wallet(user.id))


@router.post(
    "/top-ups",
    operation_id="wallet-top-up",
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse}},
)
async def top_up(
    payload: TopUpRequest, service: WalletServiceDep, user: CurrentUser
) -> WalletTransactionResponse:
    """Starts a dummy BLIK / card top-up: pending now, completed (or declined) in ~1.5 s."""
    started = await service.start_top_up(
        user.id,
        TopUp(
            amount_minor=payload.amount_minor,
            method=PaymentMethod(payload.method),
            blik_code=payload.blik_code,
            card_last4=payload.card_last4,
        ),
    )
    return WalletTransactionResponse.model_validate(payment_value(started))


@router.get(
    "/top-ups/{transaction_id}",
    operation_id="wallet-top-up-status",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def top_up_status(
    transaction_id: str, service: WalletServiceDep, user: CurrentUser
) -> WalletTransactionResponse:
    """Polled by the top-up sheet until the status leaves `pending`."""
    found = await service.top_up_status(user.id, transaction_id)
    return WalletTransactionResponse.model_validate(payment_value(found))
