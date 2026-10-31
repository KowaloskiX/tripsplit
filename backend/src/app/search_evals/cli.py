"""`search-eval` — the package research over the eval dataset, scored against an oracle.

    uv run search-eval list
    uv run search-eval run                                   # replay (default): free, deterministic
    uv run search-eval run --mode record --liteapi-src ../../tripsplit-l/backend/src/app/suppliers
    uv run search-eval run --mode live --briefs waw-prg      # live suppliers, nothing recorded
    uv run search-eval compare var/search-evals/<a> var/search-evals/<b>

Cassettes live in `var/search-evals/cassettes/`, reports in `var/search-evals/<timestamp>/`
(`report.md`, `report.json`). Exit code 1 when a brief errored (e.g. a cassette miss in
replay), 2 when the research made an LLM call.
"""

import argparse
import asyncio
import logging
import sys
import time
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

from app.search_evals.cassette import CassetteMode, CassetteStore
from app.search_evals.dataset import BRIEFS, select
from app.search_evals.metrics import BriefResult, summarise
from app.search_evals.report import brief_table, compare, summary_lines, write
from app.search_evals.runner import run_brief, stats_of
from app.search_evals.suppliers import BACKEND_DIR, build

VAR_DIR = BACKEND_DIR / "var" / "search-evals"
CASSETTES = VAR_DIR / "cassettes"


def _csv(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


async def _run(args: argparse.Namespace) -> int:
    mode = CassetteMode(args.mode)
    store = CassetteStore(Path(args.cassettes))
    briefs = select(_csv(args.briefs))
    started_at = datetime.now(UTC)
    out_dir = Path(args.out) if args.out else VAR_DIR / started_at.strftime("%Y%m%dT%H%M%SZ")
    results: list[BriefResult] = []
    started = time.monotonic()
    async with AsyncExitStack() as stack:
        registry, wrapped = await build(
            mode,
            store,
            stack,
            _csv(args.suppliers) or None,
            liteapi_src=Path(args.liteapi_src) if args.liteapi_src else None,
            refresh_empty=args.refresh_empty,
        )
        print(f"{mode} with {', '.join(registry.ids)} over {len(briefs)} briefs", flush=True)
        for brief in briefs:
            result = await run_brief(brief, registry, quotes=args.quotes)
            results.append(result)
            status = result.error or f"score {100 * result.score:.0f}"
            print(f"  {brief.id}: {status} ({result.seconds:.1f} s)", flush=True)
        stats = stats_of(wrapped)
    summary = summarise(results, stats)
    config = {
        "mode": mode.value,
        "suppliers": registry.ids,
        "briefs": [brief.id for brief in briefs],
        "started_at": started_at.isoformat(),
        "wall_seconds": round(time.monotonic() - started, 1),
        "cassettes": str(store.root),
    }
    write(out_dir, results, summary, config)
    print("\n".join(["", *summary_lines(summary), "", *brief_table(results)]))
    print(f"\nreport: {out_dir / 'report.md'}")
    if summary.llm_calls:
        return 2
    return 1 if summary.errors else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="search-eval", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the briefs of the dataset")
    run = commands.add_parser("run", help="run the dataset and write a report")
    run.add_argument("--mode", choices=[m.value for m in CassetteMode], default="replay")
    run.add_argument("--briefs", help="comma-separated brief ids or prefixes (default: all)")
    run.add_argument("--suppliers", help="comma-separated supplier ids (default: per mode)")
    run.add_argument("--cassettes", default=str(CASSETTES))
    run.add_argument("--out", help="report directory (default: var/search-evals/<timestamp>)")
    run.add_argument("--liteapi-src", help="a directory with liteapi.py, if not merged yet")
    run.add_argument("--quotes", action="store_true", help="re-quote what the packages chose")
    run.add_argument(
        "--refresh-empty", action="store_true", help="record: ask again where nothing was found"
    )
    cmp = commands.add_parser("compare", help="deltas between two report directories")
    cmp.add_argument("before")
    cmp.add_argument("after")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if args.command == "list":
        for brief in BRIEFS:
            print(f"{brief.id:30} {brief.text()}")
        return
    if args.command == "compare":
        print(compare(Path(args.before), Path(args.after)), end="")
        return
    sys.exit(asyncio.run(_run(args)))
