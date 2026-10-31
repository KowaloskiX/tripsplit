"""HTTP for packages: research, votes and closing the vote. Zero business logic."""

from typing import Any

from fastapi import APIRouter
from starlette import status

from app.core.errors_http import ErrorResponse
from app.routes.dependencies import CurrentUser, ProposalServiceDep
from app.routes.errors import trip_value
from app.schemas.trips import (
    CastVoteRequest,
    TripOptionsResponse,
    TripSelectionRequest,
    TripStatusResponse,
)

router = APIRouter(prefix="/trips/{trip_id}", tags=["proposals"])

ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
}


@router.post(
    "/proposals/generate",
    operation_id="proposals-generate",
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
async def generate_proposals(
    trip_id: str, service: ProposalServiceDep, user: CurrentUser
) -> TripStatusResponse:
    """Starts the research and returns at once; the packages arrive in the feed."""
    return TripStatusResponse.model_validate(trip_value(await service.generate(trip_id, user.id)))


@router.post("/votes", operation_id="proposals-vote", responses=ERRORS)
async def cast_vote(
    trip_id: str, payload: CastVoteRequest, service: ProposalServiceDep, user: CurrentUser
) -> TripStatusResponse:
    result = await service.vote(trip_id, user.id, payload.proposal_id)
    return TripStatusResponse.model_validate(trip_value(result))


@router.post("/voting/close", operation_id="proposals-close-voting", responses=ERRORS)
async def close_voting(
    trip_id: str, service: ProposalServiceDep, user: CurrentUser
) -> TripStatusResponse:
    result = await service.close_voting(trip_id, user.id)
    return TripStatusResponse.model_validate(trip_value(result))


@router.get("/options", operation_id="proposals-options", responses=ERRORS)
async def trip_options(
    trip_id: str, service: ProposalServiceDep, user: CurrentUser
) -> TripOptionsResponse:
    """Every transport, stay and activity the latest research found, to pick one step at a
    time. 409 while the research is still running."""
    return TripOptionsResponse.model_validate(trip_value(await service.options(trip_id, user.id)))


@router.post("/selection", operation_id="proposals-select", responses=ERRORS)
async def select_options(
    trip_id: str, payload: TripSelectionRequest, service: ProposalServiceDep, user: CurrentUser
) -> TripStatusResponse:
    """The organizer's picks become the trip's package and close the vote at once (shares and
    bookings as when a vote closes)."""
    result = await service.select(
        trip_id,
        user.id,
        transport_option_id=payload.transport_option_id,
        stay_option_id=payload.stay_option_id,
        activity_option_ids=payload.activities,
    )
    return TripStatusResponse.model_validate(trip_value(result))
