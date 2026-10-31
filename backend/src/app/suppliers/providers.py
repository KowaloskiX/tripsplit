"""Builds the application's `SupplierRegistry` from configuration."""

import logging
from collections.abc import Sequence
from decimal import Decimal
from functools import lru_cache

from app.core.config import PkpTransportKind, Settings
from app.core.domain.result import Err
from app.db.documents import utc_now
from app.suppliers.demo_rail import BASE_PATH as DEMO_RAIL_PATH
from app.suppliers.demo_rail import DemoRailSupplier
from app.suppliers.duffel import SUPPLIER_ID as DUFFEL
from app.suppliers.duffel import Clock, DuffelConfig, DuffelSupplier
from app.suppliers.duffel_client import DuffelClient, check_key
from app.suppliers.intercity import HttpTransport, SharedBrowserTransport, Transport
from app.suppliers.liteapi import SUPPLIER_ID as LITEAPI
from app.suppliers.liteapi import LiteApiConfig, liteapi_supplier
from app.suppliers.liteapi_client import check_key as check_liteapi_key
from app.suppliers.osm_activities import SUPPLIER_ID as OSM_ACTIVITIES
from app.suppliers.osm_activities import OsmActivitiesSupplier
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import SupplierAdapter
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SIM_CAPABILITIES, sim_supplier

logger = logging.getLogger(__name__)

PKP_INTERCITY = "pkp_intercity"
DEMO_RAIL = "demo_rail"
KNOWN_SUPPLIERS: frozenset[str] = frozenset(
    {*SIM_CAPABILITIES, PKP_INTERCITY, DEMO_RAIL, LITEAPI, DUFFEL, OSM_ACTIVITIES}
)


def liteapi_config(settings: Settings) -> LiteApiConfig | None:
    """The LiteAPI configuration, or None without a usable key (none, empty, or not a sandbox
    key while live mode is not allowed). The reason is logged; the key never is."""
    key = settings.liteapi_key
    value = key.get_secret_value().strip() if key is not None else ""
    if key is None or not value:
        return None
    checked = check_liteapi_key(value, allow_live=settings.liteapi_allow_live)
    if isinstance(checked, Err):
        logger.warning("the liteapi supplier is disabled: %s", checked.error)
        return None
    return LiteApiConfig(api_key=key, allow_live=settings.liteapi_allow_live)


def duffel_config(settings: Settings) -> DuffelConfig | None:
    """The Duffel configuration, or None without a usable key (none, empty, or a live key
    while live mode is not allowed). The reason is logged; the key never is."""
    key = settings.duffel_api_key
    if key is None or not key.get_secret_value().strip():
        return None
    checked = check_key(key.get_secret_value().strip(), allow_live=settings.duffel_allow_live)
    if isinstance(checked, Err):
        logger.warning("the duffel supplier is disabled: %s", checked.error)
        return None
    return DuffelConfig(
        api_key=key,
        allow_live=settings.duffel_allow_live,
        fx_eur_pln=Decimal(str(settings.duffel_fx_eur_pln)),
        contact_email=settings.duffel_contact_email,
        contact_phone=settings.duffel_contact_phone,
    )


def duffel_supplier(config: DuffelConfig, clock: Clock = utc_now) -> DuffelSupplier:
    client = DuffelClient(config.api_key, allow_live=config.allow_live)
    return DuffelSupplier(client, config, clock=clock)


@lru_cache
def shared_browser_transport() -> SharedBrowserTransport:
    """The process's one PKP browser (started on its first call, see SharedBrowserTransport)."""
    return SharedBrowserTransport()


def pkp_transport(kind: PkpTransportKind) -> Transport:
    """`browser` (the default; Akamai resets plain HTTP) or `http` (tests, open networks)."""
    return shared_browser_transport() if kind == "browser" else HttpTransport()


async def close_shared_transports() -> None:
    """Server shutdown: closes the PKP browser if it was ever started."""
    await shared_browser_transport().close()


def _adapter(
    supplier_id: str,
    demo_rail_url: str | None,
    liteapi: LiteApiConfig | None,
    duffel: DuffelConfig | None,
    pkp: Transport | None,
) -> SupplierAdapter | None:
    if supplier_id in SIM_CAPABILITIES:
        return sim_supplier(supplier_id, utc_now)
    if supplier_id == PKP_INTERCITY:
        # In a demo (`demo_rail_url`) the agent buys PKP's trains on our fake rail site.
        site = f"{demo_rail_url}{DEMO_RAIL_PATH}" if demo_rail_url is not None else None
        return PkpIntercitySupplier(pkp or HttpTransport(), purchase_site=site)
    if supplier_id == DEMO_RAIL and demo_rail_url is not None:
        return DemoRailSupplier(demo_rail_url)
    if supplier_id == LITEAPI and liteapi is not None:
        return liteapi_supplier(liteapi, utc_now)
    if supplier_id == DUFFEL and duffel is not None:
        return duffel_supplier(duffel)
    if supplier_id == OSM_ACTIVITIES:
        return OsmActivitiesSupplier()
    return None


def build_registry(
    supplier_ids: Sequence[str],
    demo_rail_url: str | None,
    *,
    liteapi: LiteApiConfig | None = None,
    duffel: DuffelConfig | None = None,
    pkp: Transport | None = None,
) -> SupplierRegistry:
    """The enabled suppliers, in configuration order (`Settings.supplier_ids`). Unknown ids
    are skipped, and so are `demo_rail` outside a demo (no `demo_rail_url`), `liteapi`
    without a usable key (`liteapi_config`) and `duffel` without a usable key
    (`duffel_config`). `pkp` is PKP Intercity's transport (see `pkp_transport`; plain HTTP
    when not given)."""
    adapters = [
        _adapter(supplier_id, demo_rail_url, liteapi, duffel, pkp) for supplier_id in supplier_ids
    ]
    return SupplierRegistry(adapter for adapter in adapters if adapter is not None)
