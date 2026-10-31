"""HTTP for a member's own traveller details. Zero business logic.

Only ever the caller's own details: there is no endpoint that reads somebody else's. The trip
room shows other members' completeness (which fields are missing), never values.
"""

from fastapi import APIRouter

from app.routes.dependencies import CurrentUser, TravellerServiceDep
from app.routes.errors import trip_value
from app.schemas.travellers import TravellerDetailsRequest, TravellerDetailsResponse
from app.services.travellers import TravellerDetailsUpdate

router = APIRouter(prefix="/me/traveller-details", tags=["travellers"])


@router.get("", operation_id="traveller-details-read")
async def read_my_details(
    user: CurrentUser, service: TravellerServiceDep
) -> TravellerDetailsResponse:
    return TravellerDetailsResponse.model_validate(trip_value(await service.mine(user.id)))


@router.put("", operation_id="traveller-details-update")
async def update_my_details(
    payload: TravellerDetailsRequest, user: CurrentUser, service: TravellerServiceDep
) -> TravellerDetailsResponse:
    """Sets the caller's own details; fields left out stay as they are. The document number
    is write-only: the response carries it masked."""
    update = TravellerDetailsUpdate(
        full_name=payload.full_name,
        date_of_birth=payload.date_of_birth,
        nationality=payload.nationality,
        document_number=payload.document_number,
        document_expiry=payload.document_expiry,
        gender=payload.gender,
    )
    return TravellerDetailsResponse.model_validate(
        trip_value(await service.update_mine(user.id, update))
    )
