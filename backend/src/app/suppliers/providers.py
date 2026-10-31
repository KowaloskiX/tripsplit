"""Builds the application's `SupplierRegistry` from configuration."""

from collections.abc import Sequence

from app.db.documents import utc_now
from app.suppliers.demo_rail import DemoRailSupplier
from app.suppliers.intercity import HttpTransport
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import SupplierAdapter
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SIM_CAPABILITIES, sim_supplier

PKP_INTERCITY = "pkp_intercity"
DEMO_RAIL = "demo_rail"
KNOWN_SUPPLIERS: frozenset[str] = frozenset({*SIM_CAPABILITIES, PKP_INTERCITY, DEMO_RAIL})


def _adapter(supplier_id: str, demo_rail_url: str | None) -> SupplierAdapter | None:
    if supplier_id in SIM_CAPABILITIES:
        return sim_supplier(supplier_id, utc_now)
    if supplier_id == PKP_INTERCITY:
        return PkpIntercitySupplier(HttpTransport())
    if supplier_id == DEMO_RAIL and demo_rail_url is not None:
        return DemoRailSupplier(demo_rail_url)
    return None


def build_registry(supplier_ids: Sequence[str], demo_rail_url: str | None) -> SupplierRegistry:
    """The enabled suppliers, in configuration order (`Settings.supplier_ids`). Unknown ids
    are skipped, and so is `demo_rail` outside a demo (no `demo_rail_url`)."""
    adapters = [_adapter(supplier_id, demo_rail_url) for supplier_id in supplier_ids]
    return SupplierRegistry(adapter for adapter in adapters if adapter is not None)
