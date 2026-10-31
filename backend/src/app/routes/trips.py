"""HTTP for trips: create, list, join, the room state and the feed. Zero business logic."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from starlette import status

from app.core.domain.trips import TravelPreferences
from app.core.errors_http import ErrorResponse
from app.routes.dependencies import CurrentUser, TripServiceDep
from app.routes.errors import trip_value
from app.schemas.trips import (
    CreateTripRequest,
    EventResponse,
    JoinTripRequest,
    PostMessageRequest,
    RoomResponse,
    SetPayByRequest,
    TripStatusResponse,
    TripSummaryResponse,
)
from app.services.trips import NewTrip

router = APIRouter(prefix="/trips", tags=["trips"])

NOT_FOUND: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}


@router.post("", operation_id="trips-create", status_code=status.HTTP_201_CREATED)
async def create_trip(
    payload: CreateTripRequest, service: TripServiceDep, user: CurrentUser
) -> TripStatusResponse:
    result = await service.create(
        user.id,
        NewTrip(
            title=payload.title,
            origin=payload.origin,
            brief=payload.brief,
            date_from=payload.date_from,
            date_to=payload.date_to,
            group_size=payload.group_size,
            budget_per_person_minor=payload.budget_per_person_minor,
            display_name=payload.display_name,
            destination=payload.destination,
            transport_mode=payload.transport_mode,
            preferences=TravelPreferences(
                earliest_departure_hour=payload.earliest_departure_hour,
                max_transfers=payload.max_transfers,
            ),
        ),
    )
    return TripStatusResponse.model_validate(trip_value(result))


@router.get("", operation_id="trips-list")
async def list_trips(service: TripServiceDep, user: CurrentUser) -> list[TripSummaryResponse]:
    return [TripSummaryResponse.model_validate(view) for view in await service.list_mine(user.id)]


@router.post(
    "/join",
    operation_id="trips-join",
    responses={**NOT_FOUND, status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def join_trip(
    payload: JoinTripRequest, service: TripServiceDep, user: CurrentUser
) -> TripStatusResponse:
    """Idempotent: a member opening the invite link again just gets the trip back."""
    result = await service.join(payload.invite_code, user.id, payload.display_name)
    return TripStatusResponse.model_validate(trip_value(result))


@router.get("/{trip_id}", operation_id="trips-room", responses=NOT_FOUND)
async def read_room(trip_id: str, service: TripServiceDep, user: CurrentUser) -> RoomResponse:
    """The whole room in one response — the UI polls this one endpoint."""
    return RoomResponse.model_validate(trip_value(await service.room(trip_id, user.id)))


@router.post(
    "/{trip_id}/leave",
    operation_id="trips-leave",
    responses={**NOT_FOUND, status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def leave_trip(
    trip_id: str, service: TripServiceDep, user: CurrentUser
) -> TripStatusResponse:
    """The caller drops out before anything is bought; the rest re-split the total."""
    return TripStatusResponse.model_validate(trip_value(await service.leave(trip_id, user.id)))


@router.post(
    "/{trip_id}/pay-by",
    operation_id="trips-set-pay-by",
    responses={
        **NOT_FOUND,
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def set_pay_by(
    trip_id: str, payload: SetPayByRequest, service: TripServiceDep, user: CurrentUser
) -> TripStatusResponse:
    """The organizer moves the funding deadline (PAYING only, must be in the future)."""
    return TripStatusResponse.model_validate(
        trip_value(await service.set_pay_by(trip_id, user.id, payload.pay_by))
    )


@router.get("/{trip_id}/feed", operation_id="trips-feed", responses=NOT_FOUND)
async def read_feed(
    trip_id: str,
    service: TripServiceDep,
    user: CurrentUser,
    after: Annotated[datetime | None, Query()] = None,
) -> list[EventResponse]:
    events = trip_value(await service.feed(trip_id, user.id, after))
    return [EventResponse.model_validate(event) for event in events]


@router.post(
    "/{trip_id}/messages",
    operation_id="trips-post-message",
    status_code=status.HTTP_201_CREATED,
    responses=NOT_FOUND,
)
async def post_message(
    trip_id: str, payload: PostMessageRequest, service: TripServiceDep, user: CurrentUser
) -> EventResponse:
    event = trip_value(await service.post_message(trip_id, user.id, payload.text))
    return EventResponse.model_validate(event)
