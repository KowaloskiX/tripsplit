"""HTTP for "what do we do there": attraction votes and the day-by-day plan. Zero logic."""

from typing import Annotated, Any

from fastapi import APIRouter, Path
from starlette import status

from app.core.errors_http import ErrorResponse
from app.routes.dependencies import AttractionServiceDep, CurrentUser, ItineraryServiceDep
from app.routes.errors import trip_value
from app.schemas.itinerary import AttractionsResponse, ItineraryResponse

router = APIRouter(prefix="/trips/{trip_id}", tags=["itinerary"])

AttractionId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]

ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
}


@router.get("/attractions", operation_id="attractions-list", responses=ERRORS)
async def list_attractions(
    trip_id: str, service: AttractionServiceDep, user: CurrentUser
) -> AttractionsResponse:
    """Ranked attraction candidates at the destination with their voters (after the package
    vote; the list is fixed at the first request)."""
    return AttractionsResponse.model_validate(trip_value(await service.overview(trip_id, user.id)))


@router.post("/attractions/{attraction_id}/vote", operation_id="attractions-vote", responses=ERRORS)
async def toggle_attraction_vote(
    trip_id: str, attraction_id: AttractionId, service: AttractionServiceDep, user: CurrentUser
) -> AttractionsResponse:
    """Toggles the caller's vote on one attraction; answers with the updated list."""
    result = await service.vote(trip_id, attraction_id, user.id)
    return AttractionsResponse.model_validate(trip_value(result))


@router.get("/itinerary", operation_id="itinerary-get", responses=ERRORS)
async def get_itinerary(
    trip_id: str, service: ItineraryServiceDep, user: CurrentUser
) -> ItineraryResponse:
    """The day-by-day plan (no days until the organizer plans them)."""
    return ItineraryResponse.model_validate(trip_value(await service.get(trip_id, user.id)))


@router.post("/itinerary/generate", operation_id="itinerary-generate", responses=ERRORS)
async def generate_itinerary(
    trip_id: str, service: ItineraryServiceDep, user: CurrentUser
) -> ItineraryResponse:
    """The organizer plans (or re-plans) the days from the votes; bookable visits queue their
    tickets, which re-splits the shares."""
    return ItineraryResponse.model_validate(trip_value(await service.generate(trip_id, user.id)))
