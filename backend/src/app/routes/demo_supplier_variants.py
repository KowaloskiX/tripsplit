"""HTTP for the perturbed fake rail sites — the booking agent's eval targets (dev/test only).

`/api/demo-supplier/rail-variants/<variant>[/<page>]`, see `services/demo_supplier_variants`
for the list. Like the base demo site: HTML for the agent's browser, out of the OpenAPI schema,
404 outside dev/test.
"""

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.routes.dependencies import require_demo_routes
from app.services import demo_supplier_variants as variants

router = APIRouter(
    prefix="/demo-supplier/rail-variants",
    tags=["demo"],
    include_in_schema=False,
    dependencies=[Depends(require_demo_routes)],
)


async def _respond(variant: str, page: str, request: Request) -> HTMLResponse:
    answer = variants.render(variant, page, request.query_params, request.cookies)
    if answer.delay_s:
        await asyncio.sleep(answer.delay_s)
    response = HTMLResponse(
        answer.html, status_code=answer.status, headers={"Cache-Control": "no-store"}
    )
    if answer.set_consent_cookie:
        response.set_cookie(
            variants.CONSENT_COOKIE, "1", path=variants.VARIANT_BASE_PATH, samesite="lax"
        )
    return response


@router.get("/{variant}", operation_id="demo-rail-variant-search")
async def search(variant: str, request: Request) -> HTMLResponse:
    return await _respond(variant, "", request)


@router.get("/{variant}/{page}", operation_id="demo-rail-variant-page")
async def page(variant: str, page: str, request: Request) -> HTMLResponse:
    return await _respond(variant, page, request)
