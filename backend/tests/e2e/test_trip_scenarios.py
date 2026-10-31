"""Every harness scenario in fast mode (fixture research, scripted agent) against the test Mongo.

A scenario fails the suite only on an UNEXPECTED problem: a step that fails without being
expected to, or an invariant violation nobody has explained. Scenarios waiting for a domain
feature (pending) and scenarios documenting a known bug are reported as xfail (strict=False).
"""

from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.client import Database
from app.harness.driver import Driver
from app.harness.scenarios import SCENARIOS
from app.harness.world import Options, World


@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_scenario(name: str, database: Database, settings: Settings, tmp_path: Path) -> None:
    world = World.build(database, settings, SCENARIOS[name], Options(out_dir=tmp_path))
    result = await Driver(world, wait_timeout_s=10.0).run()

    if result.outcome in ("pending", "xfail"):
        pytest.xfail(result.reason)
    unexpected = [f"{v.invariant}: {v.message}" for v in result.violations if v.known is None]
    failed = [
        f"step {s.index} {s.label}: {s.detail}" for s in result.steps if s.outcome == "failed"
    ]
    assert result.outcome in ("pass", "known", "xpass"), (result.reason, failed, unexpected)
    assert not unexpected
    assert not failed
