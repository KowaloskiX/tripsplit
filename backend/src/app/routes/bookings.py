"""HTTP for bookings and agent runs: statuses, mapping onto schemas. Zero business logic."""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Response
from starlette import status

from app.core.domain.bookings import RUN_ID_PATTERN
from app.core.domain.result import Ok
from app.core.errors_http import ErrorResponse
from app.db.identifiers import identifier_of, to_text
from app.routes.dependencies import BookingServiceDep, CurrentUser
from app.routes.errors import booking_failure
from app.schemas.bookings import (
    AgentRunResponse,
    ApproveRequest,
    BookingResponse,
    LiveStatusResponse,
    RunStatusResponse,
    TripBookingsResponse,
)
from app.services.bookings import AgentRunRecord, BookingWithRun

router = APIRouter(tags=["bookings"])

RunId = Annotated[str, Path(pattern=RUN_ID_PATTERN.pattern, max_length=64)]

_NOT_FOUND: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}
_ORGANIZER_ACTION: dict[int | str, dict[str, Any]] = {
    **_NOT_FOUND,
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
}


def run_response(run: AgentRunRecord) -> AgentRunResponse:
    return AgentRunResponse(
        run_id=run.run_id,
        status=run.status,
        outcome=run.outcome,
        milestone=run.milestone,
        steps=run.steps,
        reason=run.reason,
        cost_usd=run.cost_usd,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def booking_response(item: BookingWithRun) -> BookingResponse:
    booking = item.booking
    return BookingResponse(
        id=to_text(identifier_of(booking)),
        trip_id=to_text(booking.trip_id),
        kind=booking.kind,
        title=booking.title,
        supplier=booking.supplier,
        supplier_url=booking.supplier_url,
        amount_minor=booking.amount_minor,
        status=booking.status,
        confirmation_ref=booking.confirmation_ref,
        replaces_booking_id=to_text(booking.replaces_booking_id)
        if booking.replaces_booking_id is not None
        else None,
        run=run_response(item.run) if item.run is not None else None,
    )


@router.get("/trips/{trip_id}/bookings", operation_id="bookings-list", responses=_NOT_FOUND)
async def list_bookings(
    trip_id: str, user: CurrentUser, service: BookingServiceDep
) -> TripBookingsResponse:
    result = await service.list_for_trip(trip_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    trip = result.value.trip
    return TripBookingsResponse(
        trip_id=trip_id,
        trip_status=trip.status,
        currency=trip.currency,
        total_minor=trip.total_minor,
        travellers=result.value.travellers,
        is_organizer=result.value.is_organizer,
        bookings=[booking_response(item) for item in result.value.items],
    )


@router.post(
    "/trips/{trip_id}/bookings/{booking_id}/start",
    operation_id="bookings-start",
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ORGANIZER_ACTION,
)
async def start_booking(
    trip_id: str, booking_id: str, user: CurrentUser, service: BookingServiceDep
) -> BookingResponse:
    result = await service.start(trip_id, booking_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    return booking_response(result.value)


@router.post(
    "/trips/{trip_id}/bookings/{booking_id}/approve",
    operation_id="bookings-approve",
    responses=_ORGANIZER_ACTION,
)
async def approve_booking(
    trip_id: str,
    booking_id: str,
    payload: ApproveRequest,
    user: CurrentUser,
    service: BookingServiceDep,
) -> BookingResponse:
    result = await service.approve(trip_id, booking_id, user.id, payload.approved)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    return booking_response(result.value)


@router.get("/agent-runs/{run_id}/status", operation_id="agent-runs-status", responses=_NOT_FOUND)
async def run_status(
    run_id: RunId, user: CurrentUser, service: BookingServiceDep
) -> RunStatusResponse:
    result = await service.run_status(run_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    view = result.value
    live = view.live
    return RunStatusResponse(
        booking_id=to_text(view.run.booking_id),
        run=run_response(view.run),
        live=LiveStatusResponse(
            milestone=live.milestone,
            reached=live.reached,
            step=live.step,
            reason=live.reason,
            outcome=live.outcome,
            cost_usd=live.cost_usd,
        ),
    )


@router.get(
    "/agent-runs/{run_id}/frame",
    operation_id="agent-runs-frame",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {"image/png": {}, "image/jpeg": {}},
            "description": "The newest frame of the run (live screencast or last screenshot).",
        },
        **_NOT_FOUND,
    },
)
async def run_frame(run_id: RunId, user: CurrentUser, service: BookingServiceDep) -> Response:
    result = await service.frame(run_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    # Polled every second while the agent works — a cached frame would freeze the preview.
    return Response(
        content=result.value.content,
        media_type=result.value.media_type,
        headers={"Cache-Control": "no-store"},
    )
