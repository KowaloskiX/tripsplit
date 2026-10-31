"""HTTP for the fake attraction-ticket shop (dev/test only, 404 elsewhere).

HTML pages for the agent's browser, outside the OpenAPI schema like the demo rail site (see
`routes/demo_supplier`): same-origin GET forms, inline styles, no script.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette import status

from app.routes.dependencies import require_demo_routes
from app.services import demo_tickets as shop

router = APIRouter(
    prefix="/demo-supplier/tickets",
    tags=["demo"],
    include_in_schema=False,
    dependencies=[Depends(require_demo_routes)],
)


def _html(page: str | None) -> HTMLResponse:
    if page is None:
        return HTMLResponse(shop.render_not_found(), status_code=status.HTTP_404_NOT_FOUND)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("", operation_id="demo-tickets-visit")
async def visit(request: Request) -> HTMLResponse:
    return _html(shop.render_search(shop.parse_order(request.query_params)))


@router.get("/slots", operation_id="demo-tickets-slots")
async def slots(request: Request) -> HTMLResponse:
    return _html(shop.render_slots(shop.parse_order(request.query_params)))


@router.get("/visitors", operation_id="demo-tickets-visitors")
async def visitors(request: Request) -> HTMLResponse:
    return _html(shop.render_visitors(shop.parse_order(request.query_params)))


@router.get("/summary", operation_id="demo-tickets-summary")
async def summary(request: Request) -> HTMLResponse:
    return _html(shop.render_summary(shop.parse_order(request.query_params)))


@router.get("/confirmation", operation_id="demo-tickets-confirmation")
async def confirmation(request: Request) -> HTMLResponse:
    return _html(shop.render_confirmation(shop.parse_order(request.query_params)))
