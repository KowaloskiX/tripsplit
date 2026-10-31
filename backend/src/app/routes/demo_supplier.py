"""HTTP for the fake rail supplier (dev/test only, 404 elsewhere).

Not part of the API contract — these are HTML pages for the agent's browser, so they stay out
of the OpenAPI schema (and therefore out of the generated client).

The API's security headers apply unchanged and are compatible with these pages: the CSP allows
same-origin form targets (`form-action 'self'`) and inline `<style>`, and the pages carry no
script. Being same-origin, they are reachable from the agent without CORS.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette import status

from app.routes.dependencies import require_demo_routes
from app.services import demo_supplier as site

router = APIRouter(
    prefix="/demo-supplier/rail",
    tags=["demo"],
    include_in_schema=False,
    dependencies=[Depends(require_demo_routes)],
)


def _html(page: str | None) -> HTMLResponse:
    if page is None:
        return HTMLResponse(site.render_not_found(), status_code=status.HTTP_404_NOT_FOUND)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("", operation_id="demo-rail-search")
async def search(request: Request) -> HTMLResponse:
    return _html(site.render_search(site.parse_order(request.query_params)))


@router.get("/results", operation_id="demo-rail-results")
async def results(request: Request) -> HTMLResponse:
    return _html(site.render_results(site.parse_order(request.query_params)))


@router.get("/passengers", operation_id="demo-rail-passengers")
async def passengers(request: Request) -> HTMLResponse:
    return _html(site.render_passengers(site.parse_order(request.query_params)))


@router.get("/summary", operation_id="demo-rail-summary")
async def summary(request: Request) -> HTMLResponse:
    return _html(site.render_summary(site.parse_order(request.query_params)))


@router.get("/confirmation", operation_id="demo-rail-confirmation")
async def confirmation(request: Request) -> HTMLResponse:
    return _html(site.render_confirmation(site.parse_order(request.query_params)))
