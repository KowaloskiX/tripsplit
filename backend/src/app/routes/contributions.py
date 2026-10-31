"""HTTP for shares and payments. Zero business logic."""

from fastapi import APIRouter
from starlette import status

from app.core.errors_http import ErrorResponse
from app.routes.dependencies import ContributionServiceDep, CurrentUser
from app.routes.errors import trip_value
from app.schemas.trips import PaymentResponse

router = APIRouter(prefix="/trips/{trip_id}/contributions", tags=["contributions"])


@router.post(
    "/pay",
    operation_id="contributions-pay",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def pay_my_share(
    trip_id: str, service: ContributionServiceDep, user: CurrentUser
) -> PaymentResponse:
    """Charges the caller's outstanding share; the last payment moves the trip to booking."""
    return PaymentResponse.model_validate(trip_value(await service.pay(trip_id, user.id)))
