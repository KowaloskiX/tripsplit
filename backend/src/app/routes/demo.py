"""Demo-only HTTP: trigger a disruption on a booked trip. 404 outside dev/test."""

from fastapi import APIRouter, Depends
from starlette import status

from app.core.domain.result import Ok
from app.core.errors_http import ErrorResponse
from app.db.identifiers import identifier_of, to_text
from app.routes.bookings import booking_response
from app.routes.dependencies import BookingServiceDep, CurrentUser, require_demo_routes
from app.routes.errors import booking_failure
from app.schemas.bookings import DisruptionRequest, DisruptionResponse, ShareChangeResponse
from app.services.bookings import BookingWithRun

router = APIRouter(tags=["demo"], dependencies=[Depends(require_demo_routes)])


@router.post(
    "/trips/{trip_id}/demo/disruption",
    operation_id="demo-disruption",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def simulate_disruption(
    trip_id: str, payload: DisruptionRequest, user: CurrentUser, service: BookingServiceDep
) -> DisruptionResponse:
    """The demo's last scene: the train is delayed, the agent rebooks and re-splits."""
    result = await service.simulate_disruption(
        trip_id,
        user.id,
        booking_id=payload.booking_id,
        delay_minutes=payload.delay_minutes,
        price_change_percent=payload.price_change_percent,
    )
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    outcome = result.value
    return DisruptionResponse(
        cancelled_booking_id=to_text(identifier_of(outcome.cancelled)),
        replacement=booking_response(BookingWithRun(booking=outcome.replacement, run=None)),
        trip_status=outcome.trip.status,
        previous_total_minor=outcome.previous_total_minor,
        total_minor=outcome.trip.total_minor,
        shares=[
            ShareChangeResponse(
                user_id=to_text(share.user_id),
                display_name=share.display_name,
                previous_minor=share.change.previous_minor,
                share_minor=share.change.share_minor,
                delta_minor=share.change.delta_minor,
                paid_minor=share.change.paid_minor,
                status=share.change.status,
            )
            for share in outcome.shares
        ],
    )
