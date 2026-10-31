"""The demo director and the six-phone grid — dev/test only (404 elsewhere, like every demo
route). The director plays a whole group trip in the background through the real services;
the phones endpoint is the compact per-member state the stage grid binds to."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from starlette import status

from app.core.deps import BackgroundRunnerDep, SettingsDep
from app.core.errors_http import ErrorResponse
from app.routes.dependencies import (
    BookingServiceDep,
    ContributionServiceDep,
    CurrentUser,
    DemoServiceDep,
    ProposalServiceDep,
    TripServiceDep,
    require_demo_routes,
)
from app.routes.errors import trip_value
from app.schemas.demo_director import DirectorProgressResponse, DirectorRequest, PhonesResponse
from app.services.demo_director import (
    DemoDirectorService,
    DirectorCast,
    DirectorOptions,
    DirectorRegistry,
    DirectorTuning,
    PhonesService,
    detect_features,
)

router = APIRouter(
    prefix="/trips/{trip_id}/demo",
    tags=["demo"],
    dependencies=[Depends(require_demo_routes)],
)


def get_director_registry(request: Request) -> DirectorRegistry:
    """One registry per application, created on first use (kept on the app state so it
    outlives the request — and so this route needs no change to the app factory)."""
    registry: DirectorRegistry | None = getattr(request.app.state, "demo_director", None)
    if registry is None:
        registry = DirectorRegistry()
        request.app.state.demo_director = registry
    return registry


def get_director_tuning() -> DirectorTuning:
    """Real time and the pace's own delays; tests override it with a fast clock."""
    return DirectorTuning()


def get_director_service(
    tuning: Annotated[DirectorTuning, Depends(get_director_tuning)],
    registry: Annotated[DirectorRegistry, Depends(get_director_registry)],
    runner: BackgroundRunnerDep,
    settings: SettingsDep,
    demo: DemoServiceDep,
    trips: TripServiceDep,
    proposals: ProposalServiceDep,
    contributions: ContributionServiceDep,
    bookings: BookingServiceDep,
) -> DemoDirectorService:
    cast = DirectorCast(
        demo=demo,
        trips=trips,
        proposals=proposals,
        contributions=contributions,
        bookings=bookings,
    )
    return DemoDirectorService(cast, registry, runner, detect_features(settings), tuning)


DirectorServiceDep = Annotated[DemoDirectorService, Depends(get_director_service)]

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
}


@router.post(
    "/director",
    operation_id="demo-director-start",
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ERRORS,
)
async def start_director(
    trip_id: str, payload: DirectorRequest, service: DirectorServiceDep, user: CurrentUser
) -> DirectorProgressResponse:
    """Starts a choreography (409 while one is already playing on the trip)."""
    options = DirectorOptions(
        script=payload.script,
        pace=payload.pace,
        leave_organizer_payment=payload.leave_organizer_payment,
        with_disruption=payload.with_disruption,
    )
    progress = trip_value(await service.start(trip_id, user.id, options))
    return DirectorProgressResponse.model_validate(progress)


@router.get("/director", operation_id="demo-director-progress", responses=_ERRORS)
async def director_progress(
    trip_id: str, service: DirectorServiceDep, user: CurrentUser
) -> DirectorProgressResponse:
    """The live progress of the trip's latest run (404 when none ran since the start-up)."""
    progress = trip_value(await service.progress(trip_id, user.id))
    return DirectorProgressResponse.model_validate(progress)


@router.delete("/director", operation_id="demo-director-stop", responses=_ERRORS)
async def stop_director(
    trip_id: str, service: DirectorServiceDep, user: CurrentUser
) -> DirectorProgressResponse:
    """Stops the run; whatever it already did to the trip stays done."""
    progress = trip_value(await service.stop(trip_id, user.id))
    return DirectorProgressResponse.model_validate(progress)


@router.get("/phones", operation_id="demo-phones", responses=_ERRORS)
async def phones(trip_id: str, user: CurrentUser) -> PhonesResponse:
    """One compact card per member for the six-phone grid."""
    view = trip_value(await PhonesService().phones(trip_id, user.id))
    return PhonesResponse.model_validate(view)
