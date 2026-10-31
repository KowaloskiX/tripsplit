"""HTTP dependencies: services, the current user and the demo-route gate."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from starlette import status

from app.agent.launcher import SubprocessLauncher
from app.ai.researchers import build_researcher
from app.core.config import Settings
from app.core.deps import BackgroundRunnerDep, SettingsDep
from app.core.domain.errors import ApiError, AuthError
from app.core.domain.identity import AuthenticatedUser
from app.core.domain.result import Ok
from app.core.errors_http import DomainHTTPError
from app.db.deps import DbDep
from app.payments.providers import build_payment_provider
from app.services.auth import AuthService
from app.services.bookings import BookingService
from app.services.contributions import ContributionService
from app.services.demo import DemoService
from app.services.proposals import ProposalService
from app.services.supplier_prices import SupplierPrices
from app.services.travellers import TravellerService
from app.services.trips import TripService
from app.suppliers.duffel import DuffelConfig
from app.suppliers.liteapi import LiteApiConfig
from app.suppliers.providers import build_registry, duffel_config, liteapi_config
from app.suppliers.registry import SupplierRegistry

# routes/ -> app/ -> src/ -> backend/: the agent subprocess runs from the backend directory.
_BACKEND_DIR = Path(__file__).resolve().parents[3]

CSRF_HEADER_NAME = "X-CSRF-Token"


def get_auth_service(database: DbDep, settings: SettingsDep) -> AuthService:
    return AuthService(database, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    request: Request,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AuthenticatedUser:
    user = await _resolve_optional_user(request, service, settings)
    if user is None:
        raise DomainHTTPError(
            AuthError.SESSION_INVALID,
            status.HTTP_401_UNAUTHORIZED,
            "No active session.",
        )
    return user


async def get_optional_user(
    request: Request,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AuthenticatedUser | None:
    return await _resolve_optional_user(request, service, settings)


async def _resolve_optional_user(
    request: Request, service: AuthService, settings: Settings
) -> AuthenticatedUser | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    result = await service.resolve_session(token)
    return result.value if isinstance(result, Ok) else None


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
OptionalUser = Annotated[AuthenticatedUser | None, Depends(get_optional_user)]


@lru_cache
def _registry(
    supplier_ids: tuple[str, ...],
    demo_rail_url: str | None,
    liteapi: LiteApiConfig | None,
    duffel: DuffelConfig | None,
) -> SupplierRegistry:
    """One registry per configuration and process: a simulated supplier remembers its holds
    between requests, like the real one would."""
    return build_registry(supplier_ids, demo_rail_url, liteapi=liteapi, duffel=duffel)


def get_supplier_registry(settings: SettingsDep) -> SupplierRegistry:
    liteapi = liteapi_config(settings) if "liteapi" in settings.supplier_ids else None
    duffel = duffel_config(settings) if "duffel" in settings.supplier_ids else None
    return _registry(tuple(settings.supplier_ids), settings.demo_rail_url, liteapi, duffel)


SupplierRegistryDep = Annotated[SupplierRegistry, Depends(get_supplier_registry)]


def get_trip_service(database: DbDep, suppliers: SupplierRegistryDep) -> TripService:
    return TripService(database, suppliers=suppliers)


def get_proposal_service(
    database: DbDep,
    settings: SettingsDep,
    runner: BackgroundRunnerDep,
    suppliers: SupplierRegistryDep,
) -> ProposalService:
    return ProposalService(
        database,
        build_researcher(settings, suppliers),
        runner,
        suppliers=suppliers,
        prices=SupplierPrices(
            database, suppliers, price_tolerance_percent=settings.price_tolerance_percent
        ),
    )


def get_traveller_service() -> TravellerService:
    return TravellerService()


def get_contribution_service(settings: SettingsDep) -> ContributionService:
    return ContributionService(build_payment_provider(settings))


def get_demo_service(
    database: DbDep, settings: SettingsDep, suppliers: SupplierRegistryDep
) -> DemoService:
    return DemoService(
        database, get_contribution_service(settings), get_trip_service(database, suppliers)
    )


TripServiceDep = Annotated[TripService, Depends(get_trip_service)]
ProposalServiceDep = Annotated[ProposalService, Depends(get_proposal_service)]
ContributionServiceDep = Annotated[ContributionService, Depends(get_contribution_service)]
DemoServiceDep = Annotated[DemoService, Depends(get_demo_service)]
TravellerServiceDep = Annotated[TravellerService, Depends(get_traveller_service)]


def _under_backend(raw: str) -> Path:
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else _BACKEND_DIR / path).resolve()


def get_booking_service(
    database: DbDep, settings: SettingsDep, suppliers: SupplierRegistryDep
) -> BookingService:
    var_dir = _under_backend(settings.agent_var_dir)
    vault_file = _under_backend(settings.agent_vault_file) if settings.agent_vault_file else None
    launcher = SubprocessLauncher(
        backend_dir=_BACKEND_DIR, var_dir=var_dir, extra_vault_file=vault_file
    )
    return BookingService(
        database,
        launcher,
        var_dir / "runs",
        max_steps=settings.agent_max_steps,
        headful=settings.agent_headful,
        suppliers=suppliers,
        price_tolerance_percent=settings.price_tolerance_percent,
        payments=build_payment_provider(settings),
    )


BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]


def require_demo_routes(settings: SettingsDep) -> None:
    """Demo-only endpoints answer like an unknown path outside dev/test."""
    if not settings.demo_routes_enabled:
        raise DomainHTTPError(ApiError.NOT_FOUND, status.HTTP_404_NOT_FOUND, "No such resource.")
