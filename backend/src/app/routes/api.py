"""One place showing the entire HTTP surface of the application.

A new route means a new module in `app/routes/` plus one `include_router` line here. That way
the answer to "which endpoints do we expose" is a single file rather than a tree walk.
"""

from fastapi import APIRouter

from app.routes.auth import router as auth_router
from app.routes.bookings import router as bookings_router
from app.routes.contributions import router as contributions_router
from app.routes.demo import router as demo_router
from app.routes.demo_supplier import router as demo_supplier_router
from app.routes.demo_supplier_variants import router as demo_supplier_variants_router
from app.routes.health import router as health_router
from app.routes.proposals import router as proposals_router
from app.routes.trips import router as trips_router

# Everything under /api — same origin as the frontend, so the session cookie is first-party.
api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(trips_router)
api_router.include_router(proposals_router)
api_router.include_router(contributions_router)
api_router.include_router(demo_router)
api_router.include_router(bookings_router)
# Dev/test only: both answer 404 elsewhere (`require_demo_routes`).
api_router.include_router(demo_supplier_router)
api_router.include_router(demo_supplier_variants_router)
