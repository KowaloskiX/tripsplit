"""Demo helpers — dev/test only. Elsewhere every route here answers 404, as if it did not
exist, so production does not advertise a way to fabricate members and payments."""

from fastapi import APIRouter, Depends
from starlette import status

from app.core.deps import SettingsDep
from app.core.domain.errors import ApiError
from app.core.errors_http import DomainHTTPError
from app.routes.dependencies import CurrentUser, DemoServiceDep
from app.routes.errors import trip_value
from app.schemas.trips import CastVoteRequest, DemoResultResponse, SeedMembersRequest

_DEMO_ENVS = frozenset({"dev", "test"})


def require_demo_environment(settings: SettingsDep) -> None:
    if settings.app_env not in _DEMO_ENVS:
        raise DomainHTTPError(ApiError.NOT_FOUND, status.HTTP_404_NOT_FOUND, "No such resource.")


router = APIRouter(
    prefix="/trips/{trip_id}/demo",
    tags=["demo"],
    dependencies=[Depends(require_demo_environment)],
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
