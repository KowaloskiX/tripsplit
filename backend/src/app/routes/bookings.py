"""HTTP for bookings and agent runs: statuses, mapping onto schemas. Zero business logic."""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response
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
    BatchItemResponse,
    BatchResponse,
    BookingResponse,
    CompleteManuallyRequest,
    DisruptionResponse,
    FlowEdgeResponse,
    FlowGraphResponse,
    FlowNodeResponse,
    LiveStatusResponse,
    RunStatusResponse,
    RunStepResponse,
    ShareChangeResponse,
    SupplierCallResponse,
    TripBookingsResponse,
)
from app.schemas.trips import LinkResponse, ProvenanceResponse
from app.services.bookings import AgentRunRecord, Batch, BookingWithRun, Disruption

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
        mode=booking.mode,
        title=booking.title,
        supplier=booking.supplier,
        supplier_url=booking.supplier_url,
        supplier_id=booking.supplier_id,
        channel=booking.channel,
        hold_expires_at=booking.hold_expires_at,
        amount_minor=booking.amount_minor,
        status=booking.status,
        confirmation_ref=booking.confirmation_ref,
        replaces_booking_id=to_text(booking.replaces_booking_id)
        if booking.replaces_booking_id is not None
        else None,
        passenger_user_ids=[to_text(user_id) for user_id in booking.passenger_user_ids],
        run=run_response(item.run) if item.run is not None else None,
        payment_kind=booking.payment_kind,
        payment_ref=booking.payment_ref,
        card_last4=booking.card_last4,
        links=[LinkResponse.model_validate(link, from_attributes=True) for link in booking.links],
        images=list(booking.images),
        provenance=ProvenanceResponse.model_validate(booking.provenance, from_attributes=True)
        if booking.provenance is not None
        else None,
    )


def disruption_response(outcome: Disruption) -> DisruptionResponse:
    return DisruptionResponse(
        cancelled_booking_ids=[to_text(identifier_of(booking)) for booking in outcome.cancelled],
        replacements=[
            booking_response(BookingWithRun(booking=booking, run=None))
            for booking in outcome.replacements
        ],
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


@router.get(
    "/trips/{trip_id}/bookings/activity",
    operation_id="bookings-activity",
    responses=_NOT_FOUND,
)
async def bookings_activity(
    trip_id: str,
    user: CurrentUser,
    service: BookingServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SupplierCallResponse]:
    """The trip's recent supplier API calls (Duffel, LiteAPI), oldest first: method, path
    without ids, status, duration. Members only; poll it for the mission-control terminal."""
    result = await service.activity(trip_id, user.id, limit)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    return [
        SupplierCallResponse(
            supplier_id=item.call.supplier_id,
            supplier=item.supplier,
            method=item.call.method,
            path=item.call.path,
            status=item.call.status,
            ms=item.call.ms,
            at=item.call.at,
        )
        for item in result.value
    ]


def batch_response(batch: Batch) -> BatchResponse:
    return BatchResponse(
        trip_status=batch.trip.status,
        items=[
            BatchItemResponse(
                booking=booking_response(BookingWithRun(booking=item.booking, run=item.run)),
                error=item.error,
            )
            for item in batch.items
        ],
    )


@router.post(
    "/trips/{trip_id}/bookings/start-all",
    operation_id="bookings-start-all",
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ORGANIZER_ACTION,
)
async def start_all_bookings(
    trip_id: str, user: CurrentUser, service: BookingServiceDep
) -> BatchResponse:
    """ "Book everything": starts every startable booking; refusals are reported per booking."""
    result = await service.start_all(trip_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    return batch_response(result.value)


@router.post(
    "/trips/{trip_id}/bookings/approve-all",
    operation_id="bookings-approve-all",
    responses=_ORGANIZER_ACTION,
)
async def approve_all_bookings(
    trip_id: str, user: CurrentUser, service: BookingServiceDep
) -> BatchResponse:
    """Approves every summary awaiting approval at once — refused unless every share is paid."""
    result = await service.approve_all(trip_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    return batch_response(result.value)


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


@router.post(
    "/trips/{trip_id}/bookings/{booking_id}/complete",
    operation_id="bookings-complete-manually",
    responses=_ORGANIZER_ACTION,
)
async def complete_booking_manually(
    trip_id: str,
    booking_id: str,
    payload: CompleteManuallyRequest,
    user: CurrentUser,
    service: BookingServiceDep,
) -> BookingResponse:
    """After a handoff (or a failure) the organizer finished the purchase by hand."""
    result = await service.complete_manually(trip_id, user.id, booking_id, payload.confirmation_ref)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    return booking_response(result.value)


@router.post(
    "/trips/{trip_id}/bookings/disruptions/check",
    operation_id="bookings-check-disruptions",
    responses=_ORGANIZER_ACTION,
)
async def check_disruptions(
    trip_id: str, user: CurrentUser, service: BookingServiceDep
) -> list[DisruptionResponse]:
    """Asks the suppliers that report disruptions about the trip's bought bookings; every
    notice with a replacement is rebooked and re-split. Empty = nothing happened."""
    result = await service.check_disruptions(trip_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    return [disruption_response(outcome) for outcome in result.value]


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
            steps=[
                RunStepResponse(
                    index=step.index,
                    node_id=step.node_id,
                    kind=step.kind,
                    status=step.status,
                    duration_ms=step.duration_ms,
                    source=step.source,
                    iteration=step.iteration,
                )
                for step in live.steps
            ],
            flow_steps=live.flow_steps,
            rule_steps=live.rule_steps,
            llm_calls=live.llm_calls,
            tokens=live.tokens,
        ),
    )


@router.get("/agent-runs/{run_id}/graph", operation_id="agent-runs-graph", responses=_NOT_FOUND)
async def run_graph(
    run_id: RunId, user: CurrentUser, service: BookingServiceDep
) -> FlowGraphResponse:
    """The run's plan, for the live pipeline view. 404 until the agent has written it."""
    result = await service.graph(run_id, user.id)
    if not isinstance(result, Ok):
        raise booking_failure(result.error)
    graph = result.value
    return FlowGraphResponse(
        nodes=[
            FlowNodeResponse(
                id=node.id,
                type=node.type,
                label=node.label,
                stage=node.stage,
                inputs=node.inputs,
                outputs=node.outputs,
            )
            for node in graph.nodes
        ],
        edges=[FlowEdgeResponse(source=start, to=end) for start, end in graph.edges],
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
