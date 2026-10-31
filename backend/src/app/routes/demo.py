"""Demo helpers — dev/test only. Elsewhere every route here answers 404, as if it did not
exist, so production does not advertise a way to fabricate members, payments or disruptions.

They exist so a six-person trip can be demonstrated from one browser: seed the friends, cast
their votes, pay their shares, then delay the train.
"""

from fastapi import APIRouter, Depends
from starlette import status

from app.core.domain.result import Ok
from app.core.errors_http import ErrorResponse
from app.db.identifiers import identifier_of, to_text
from app.routes.bookings import booking_response
from app.routes.dependencies import (
    BookingServiceDep,
    CurrentUser,
    DemoServiceDep,
    require_demo_routes,
)
from app.routes.errors import booking_failure, trip_value
from app.schemas.bookings import DisruptionRequest, DisruptionResponse, ShareChangeResponse
from app.schemas.trips import (
    CastVoteRequest,
    DemoLeaveRequest,
    DemoResultResponse,
    SeedMembersRequest,
    TripStatusResponse,
)
from app.services.bookings import BookingWithRun

router = APIRouter(
    prefix="/trips/{trip_id}/demo",
    tags=["demo"],
    dependencies=[Depends(require_demo_routes)],
)


@router.post("/seed-members", operation_id="demo-seed-members")
async def seed_members(
    trip_id: str, payload: SeedMembersRequest, service: DemoServiceDep, user: CurrentUser
) -> DemoResultResponse:
    affected = trip_value(await service.seed_members(trip_id, user.id, payload.count))
    return DemoResultResponse(affected=affected)


@router.post("/vote-all", operation_id="demo-vote-all")
async def vote_all(
    trip_id: str, payload: CastVoteRequest, service: DemoServiceDep, user: CurrentUser
) -> DemoResultResponse:
    affected = trip_value(await service.vote_all(trip_id, user.id, payload.proposal_id))
    return DemoResultResponse(affected=affected)


@router.post("/pay-all", operation_id="demo-pay-all")
async def pay_all(trip_id: str, service: DemoServiceDep, user: CurrentUser) -> DemoResultResponse:
    return DemoResultResponse(affected=trip_value(await service.pay_all(trip_id, user.id)))


@router.post(
    "/leave",
    operation_id="demo-leave",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def make_member_leave(
    trip_id: str, payload: DemoLeaveRequest, service: DemoServiceDep, user: CurrentUser
) -> TripStatusResponse:
    """A seeded member drops out — the organizer drives it from the demo panel."""
    result = await service.leave(trip_id, user.id, payload.user_id)
    return TripStatusResponse.model_validate(trip_value(result))


@router.post(
    "/disruption",
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
