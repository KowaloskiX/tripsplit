"""Builds the application's `SupplierRegistry` from configuration."""

import logging
from collections.abc import Sequence

from app.core.config import Settings
from app.core.domain.result import Err
from app.db.documents import utc_now
from app.suppliers.demo_rail import DemoRailSupplier
from app.suppliers.intercity import HttpTransport
from app.suppliers.liteapi import SUPPLIER_ID as LITEAPI
from app.suppliers.liteapi import LiteApiConfig, liteapi_supplier
from app.suppliers.liteapi_client import check_key as check_liteapi_key
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import SupplierAdapter
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SIM_CAPABILITIES, sim_supplier

logger = logging.getLogger(__name__)

PKP_INTERCITY = "pkp_intercity"
DEMO_RAIL = "demo_rail"
KNOWN_SUPPLIERS: frozenset[str] = frozenset({*SIM_CAPABILITIES, PKP_INTERCITY, DEMO_RAIL, LITEAPI})


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


def _adapter(
    supplier_id: str, demo_rail_url: str | None, liteapi: LiteApiConfig | None
) -> SupplierAdapter | None:
    if supplier_id in SIM_CAPABILITIES:
        return sim_supplier(supplier_id, utc_now)
    if supplier_id == PKP_INTERCITY:
        return PkpIntercitySupplier(HttpTransport())
    if supplier_id == DEMO_RAIL and demo_rail_url is not None:
        return DemoRailSupplier(demo_rail_url)
    if supplier_id == LITEAPI and liteapi is not None:
        return liteapi_supplier(liteapi, utc_now)
    return None


def build_registry(
    supplier_ids: Sequence[str], demo_rail_url: str | None, liteapi: LiteApiConfig | None = None
) -> SupplierRegistry:
    """The enabled suppliers, in configuration order (`Settings.supplier_ids`). Unknown ids
    are skipped, and so are `demo_rail` outside a demo (no `demo_rail_url`) and `liteapi`
    without a usable key (`liteapi_config`)."""
    adapters = [_adapter(supplier_id, demo_rail_url, liteapi) for supplier_id in supplier_ids]
    return SupplierRegistry(adapter for adapter in adapters if adapter is not None)
