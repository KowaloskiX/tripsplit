"""Which suppliers an eval run asks, each wrapped in a `RecordingSupplier`.

- `record` / `live`: real adapters — `pkp_intercity` through a Camoufox `BrowserTransport`,
  `duffel` with the test key and `liteapi` with the sandbox key from `.env` — and the
  simulators for everything else (`sim_*`). Without a usable LiteAPI key stays come from
  `sim_stay`.
- `replay`: no adapter at all; the suppliers come from the cassette manifest.
"""

import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.search_evals.cassette import (
    CassetteMode,
    CassetteStore,
    RecordingSupplier,
    SupplierInfo,
)
from app.suppliers.intercity import BrowserTransport
from app.suppliers.liteapi import liteapi_supplier
from app.suppliers.pkp import PkpIntercitySupplier
from app.suppliers.ports import SupplierAdapter
from app.suppliers.providers import duffel_config, duffel_supplier, liteapi_config
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SIM_CAPABILITIES, sim_supplier

logger = logging.getLogger(__name__)

PKP = "pkp_intercity"
DUFFEL = "duffel"
LITEAPI = "liteapi"
LIVE_DEFAULT = (PKP, DUFFEL, LITEAPI, "sim_activity")
STAY_FALLBACK = "sim_stay"
BACKEND_DIR = Path(__file__).resolve().parents[3]


def _now() -> datetime:
    return datetime.now(UTC)


async def live_adapters(ids: Sequence[str], stack: AsyncExitStack) -> list[SupplierAdapter]:
    adapters: list[SupplierAdapter] = []
    wanted = list(ids)
    settings = Settings()
    for supplier_id in wanted:
        if supplier_id == PKP:
            browser = await stack.enter_async_context(BrowserTransport(headless=True))
            adapters.append(PkpIntercitySupplier(browser))
        elif supplier_id == DUFFEL:
            config = duffel_config(settings)
            if config is None:
                logger.warning("duffel skipped: no usable DUFFEL_API_KEY")
                continue
            adapters.append(duffel_supplier(config))
        elif supplier_id == LITEAPI:
            stays = liteapi_config(settings)
            if stays is None:
                logger.warning("liteapi unavailable: stays come from %s", STAY_FALLBACK)
                if STAY_FALLBACK not in wanted:
                    adapters.append(sim_supplier(STAY_FALLBACK, _now))
                continue
            adapters.append(liteapi_supplier(stays, _now))
        elif supplier_id in SIM_CAPABILITIES:
            adapters.append(sim_supplier(supplier_id, _now))
        else:
            raise ValueError(f"unknown supplier {supplier_id!r}")
    return adapters


async def build(
    mode: CassetteMode,
    store: CassetteStore,
    stack: AsyncExitStack,
    ids: Sequence[str] | None = None,
    *,
    refresh_empty: bool = False,
) -> tuple[SupplierRegistry, list[RecordingSupplier]]:
    if mode is CassetteMode.REPLAY:
        known = store.suppliers()
        chosen = [info for info in known if not ids or info.id in ids]
        if not chosen:
            raise ValueError(f"no recorded suppliers in {store.root} (record first)")
        wrapped = [RecordingSupplier(info, store, mode) for info in chosen]
    else:
        adapters = await live_adapters(ids or LIVE_DEFAULT, stack)
        wrapped = []
        for adapter in adapters:
            info = SupplierInfo.of(adapter)
            if mode is CassetteMode.RECORD:
                store.register(info)
            wrapped.append(
                RecordingSupplier(info, store, mode, inner=adapter, refresh_empty=refresh_empty)
            )
    return SupplierRegistry(wrapped), wrapped
