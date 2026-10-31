"""Cassettes: what `record` writes, `replay` answers identically, and a miss is an error."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.core.domain.trips import TransportMode
from app.search_evals.cassette import (
    CassetteMiss,
    CassetteMode,
    CassetteStore,
    RecordingSupplier,
    SupplierInfo,
    offer_json,
    offer_of,
)
from app.suppliers.ports import OfferRef, SearchRequest
from app.suppliers.sim import sim_supplier

REQUEST = SearchRequest(
    origin="Warszawa",
    destination="Praha",
    depart_date=date(2026, 11, 20),
    return_date=date(2026, 11, 22),
    party_size=4,
)


def _clock() -> datetime:
    return datetime(2026, 10, 31, 12, tzinfo=UTC)


def _recorder(
    store: CassetteStore, mode: CassetteMode, supplier_id: str = "sim_rail"
) -> RecordingSupplier:
    adapter = sim_supplier(supplier_id, _clock)
    info = SupplierInfo.of(adapter)
    store.register(info)
    inner = None if mode is CassetteMode.REPLAY else adapter
    return RecordingSupplier(info, store, mode, inner=inner)


async def test_replay_answers_what_record_recorded(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    recorded = await _recorder(store, CassetteMode.RECORD).search(REQUEST)
    replayed = await _recorder(store, CassetteMode.REPLAY).search(REQUEST)
    assert recorded and replayed == recorded


async def test_a_replay_miss_is_an_error_not_a_live_call(tmp_path: Path) -> None:
    replayer = _recorder(CassetteStore(tmp_path), CassetteMode.REPLAY)
    with pytest.raises(CassetteMiss):
        await replayer.search(REQUEST)
    assert replayer.stats.misses == 1


async def test_the_key_ignores_budget_and_a_mode_equal_to_the_suppliers_own(
    tmp_path: Path,
) -> None:
    store = CassetteStore(tmp_path)
    await _recorder(store, CassetteMode.RECORD).search(REQUEST)
    replayer = _recorder(store, CassetteMode.REPLAY)
    same = replace(REQUEST, mode=TransportMode.RAIL, budget_per_person_minor=50_000)
    assert await replayer.search(same) == await replayer.search(REQUEST)
    with pytest.raises(CassetteMiss):
        await replayer.search(replace(REQUEST, party_size=5))


async def test_live_mode_writes_nothing(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    await _recorder(store, CassetteMode.LIVE).search(REQUEST)
    assert not (tmp_path / "sim_rail").exists()


async def test_quotes_are_recorded_and_replayed(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    recorder = _recorder(store, CassetteMode.RECORD)
    offer = (await recorder.search(REQUEST))[0]
    ref = OfferRef(offer.supplier_id, offer.offer_ref, offer.supplier_data)
    quoted = await recorder.quote(ref, 4)
    replayed = await _recorder(store, CassetteMode.REPLAY).quote(ref, 4)
    assert quoted is not None and replayed == quoted


async def test_the_manifest_lets_replay_run_without_the_adapter(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    _recorder(store, CassetteMode.RECORD, "sim_flight")
    (info,) = store.suppliers()
    assert info.id == "sim_flight" and info.capabilities().mode is TransportMode.FLIGHT


async def test_an_offer_survives_the_json_round_trip() -> None:
    offer = sim_supplier("sim_flight", _clock)
    (first, *_) = await offer.search(REQUEST)
    assert offer_of(offer_json(first)) == first
