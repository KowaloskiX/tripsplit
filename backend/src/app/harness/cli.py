"""`uv run trip-harness list` / `uv run trip-harness run <name>|all [--live-search] [--live-agent]
[--keep-db]` — runs scenarios against the local Mongo, one fresh database per scenario."""

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import Settings
from app.db.client import Database
from app.documents import DOCUMENT_MODELS
from app.harness.driver import Driver, ScenarioResult
from app.harness.report import summary_table, write_reports
from app.harness.scenarios import SCENARIOS
from app.harness.world import BACKEND_DIR, Options, World

FAST_TIMEOUT_S = 15.0
LIVE_TIMEOUT_S = 600.0
SUPPLIER_PATH = "/api/demo-supplier/rail"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@contextlib.contextmanager
def demo_supplier(database: str, log_path: Path) -> Iterator[str]:
    """Our own backend on a free port, so the live agent has a rail supplier to drive. It uses a
    throwaway database and in-memory rate limits; it is stopped when the run ends."""
    port = _free_port()
    env = {
        **os.environ,
        "APP_ENV": "dev",
        "MONGODB_DATABASE": database,
        "RATE_LIMIT_STORAGE_URL": "",
    }
    log = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://localhost:{port}"
    try:
        deadline = time.monotonic() + 30
        while True:
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(base_url + SUPPLIER_PATH, timeout=2).status_code == 200:
                    break
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"the demo supplier did not come up (log: {log.name})")
            time.sleep(0.3)
        yield base_url
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        log.close()


async def run_one(
    name: str,
    base: Settings,
    stamp: str,
    out_dir: Path,
    *,
    live_search: bool,
    live_agent_url: str | None,
    keep_db: bool,
) -> ScenarioResult:
    database_name = f"harness_{stamp}_{name}"[:63]
    settings = base.model_copy(update={"mongodb_database": database_name})
    db = Database.from_settings(settings)
    try:
        await db.init_documents(DOCUMENT_MODELS, create_indexes=True)
        options = Options(
            out_dir=out_dir / name,
            live_search=live_search,
            live_agent_base_url=live_agent_url,
            poll_s=0.5 if live_agent_url else 0.02,
        )
        world = World.build(db, settings, SCENARIOS[name], options)
        modes = [
            m for m, on in (("live-search", live_search), ("live-agent", live_agent_url)) if on
        ]
        driver = Driver(
            world,
            wait_timeout_s=LIVE_TIMEOUT_S if live_agent_url else FAST_TIMEOUT_S,
            mode=" + ".join(modes) or "fast (simulated suppliers, scripted agent)",
        )
        return await driver.run()
    finally:
        if not keep_db:
            await db.client.drop_database(database_name)
        await db.dispose()


async def run_all(names: Sequence[str], args: argparse.Namespace) -> list[ScenarioResult]:
    started = datetime.now()
    stamp = started.strftime("%Y%m%d-%H%M%S")
    out_dir = BACKEND_DIR / "var" / "harness" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Settings()
    results: list[ScenarioResult] = []
    with contextlib.ExitStack() as stack:
        live_url = (
            stack.enter_context(
                demo_supplier(f"harness_{stamp}_supplier", out_dir / "supplier.log")
            )
            if args.live_agent
            else None
        )
        for name in names:
            print(f"-> {name}", flush=True)
            result = await run_one(
                name,
                base,
                stamp,
                out_dir,
                live_search=args.live_search,
                live_agent_url=live_url,
                keep_db=args.keep_db,
            )
            print(f"   {result.outcome.upper()} in {result.seconds:.1f}s {result.reason[:90]}")
            results.append(result)
    if args.live_agent:
        supplier_db = Database.from_settings(
            base.model_copy(update={"mongodb_database": f"harness_{stamp}_supplier"})
        )
        await supplier_db.client.drop_database(f"harness_{stamp}_supplier")
        await supplier_db.dispose()
    summary = write_reports(out_dir, results, started)
    print()
    print(summary_table(results))
    print(f"\nreports: {summary}")
    return results


def _list() -> None:
    width = max(len(name) for name in SCENARIOS)
    for name, scenario in SCENARIOS.items():
        flag = " [documents a bug]" if scenario.xfail else ""
        print(f"{name.ljust(width)}  {scenario.title}{flag}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="trip-harness", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the scenarios")
    run = commands.add_parser("run", help="run one scenario or all")
    run.add_argument("name", help="a scenario name or 'all'")
    run.add_argument(
        "--live-search", action="store_true", help="the real PKP Intercity adapter for rail"
    )
    run.add_argument(
        "--live-agent",
        action="store_true",
        help="the real agent subprocess on the demo rail supplier for rail bookings",
    )
    run.add_argument("--keep-db", action="store_true", help="keep each scenario's database")
    args = parser.parse_args()
    if args.command == "list":
        _list()
        return
    names = list(SCENARIOS) if args.name == "all" else [args.name]
    unknown = [name for name in names if name not in SCENARIOS]
    if unknown:
        parser.error(f"unknown scenario {unknown[0]!r}; try `trip-harness list`")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    results = asyncio.run(run_all(names, args))
    sys.exit(1 if any(result.outcome == "fail" for result in results) else 0)


if __name__ == "__main__":
    main()
