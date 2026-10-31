"""The live Duffel scenarios end to end — offline: the real services, the real `duffel`
adapter, and the fake Duffel API (`tests/duffel_fake.py`) instead of the network.

`trip-harness run barcelona_duffel_live --live-flights` runs the same scenarios against the
real test API; here they prove the flow (hold at close only with every passenger's details,
re-finding an expired offer, paying the held order) on every `pytest` run.
"""

from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.db.client import Database
from app.db.documents import utc_now
from app.harness.driver import Driver, ScenarioResult
from app.harness.scenarios import SCENARIOS
from app.harness.world import Options, World
from tests.duffel_fake import FakeDuffel


async def _run(
    name: str, api: FakeDuffel, database: Database, settings: Settings, out: Path
) -> ScenarioResult:
    api.shift_to(utc_now())
    options = Options(
        out_dir=out, live_flights=True, duffel_transport=httpx.MockTransport(api.handle)
    )
    world = World.build(database, settings, SCENARIOS[name], options)
    return await Driver(world, wait_timeout_s=10.0).run()


def _assert_passed(result: ScenarioResult) -> None:
    failed = [f"step {s.index} {s.label}: {s.detail}" for s in result.steps if s.outcome != "ok"]
    unexpected = [f"{v.invariant}: {v.message}" for v in result.violations if v.known is None]
    assert result.outcome == "pass", (result.reason, failed, unexpected)


async def test_a_full_group_is_held_at_close_and_the_hold_is_paid(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    api = FakeDuffel()
    result = await _run("barcelona_duffel_live", api, database, settings, tmp_path)

    _assert_passed(result)
    assert api.calls("POST", "/air/offer_requests") == 1  # the hold used the live offer
    assert len(api.bodies("POST", "/air/orders")) == 1
    payment = api.bodies("POST", "/air/payments")[0]
    assert payment["payment"]["currency"] == "EUR"
    flight = next(b for b in result.bookings if b.target == "flight")
    assert flight.confirmation_ref == "JCLCEN"
    assert flight.hold_ref == "ord_0000BBxVAkPCkSLAMvZP0y"
    # The report never carries a document number in full.
    assert result.travellers and all("AB" not in line for line in result.travellers)
    assert all("*******" in line for line in result.travellers)


async def test_a_slow_group_waits_for_details_and_gets_the_flights_found_again(
    database: Database, settings: Settings, tmp_path: Path
) -> None:
    api = FakeDuffel()
    result = await _run("barcelona_duffel_slow_group", api, database, settings, tmp_path)

    _assert_passed(result)
    # No hold before every passenger had their details; at the start the offer had expired,
    # so the same flights were searched again, read in full, held and paid.
    assert api.calls("POST", "/air/offer_requests") == 2
    assert len(api.bodies("POST", "/air/orders")) == 1
    assert len(api.bodies("POST", "/air/payments")) == 1
    assert result.duffel is not None
    assert any("re-found" in note for note in result.duffel.notes)


@pytest.mark.parametrize("name", ["barcelona_duffel_live", "barcelona_duffel_slow_group"])
async def test_without_live_flights_the_scenarios_are_pending(
    name: str, database: Database, settings: Settings, tmp_path: Path
) -> None:
    world = World.build(database, settings, SCENARIOS[name], Options(out_dir=tmp_path))
    result = await Driver(world).run()
    assert result.outcome == "pending"
    assert "--live-flights" in result.reason
