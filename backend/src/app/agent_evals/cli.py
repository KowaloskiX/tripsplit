"""`agent-eval` — run the booking agent's eval matrix and write a report.

    uv run agent-eval run --mode replay                    # all variants, party 1/3/5
    uv run agent-eval run --mode rules_only --variants baseline,slow --party 3
    uv run agent-eval run --mode live_llm --variants baseline,split_pages --party 3 \\
        --max-llm-calls 20                                  # opt-in, uses PLANNER (rate-limited)
    uv run agent-eval list

Reports land in `var/agent-evals/<timestamp>/report.{md,json}`. Exit code 1 when any case
fails, 2 when a deterministic mode made an LLM call.
"""

import argparse
import os
import sys
import time
from datetime import UTC, datetime

from app.agent_evals.cases import DEFAULT_PARTIES, EvalCase, EvalMode, matrix
from app.agent_evals.harness import CaseResult, LlmCallInDeterministicMode, baseline_flow, run_case
from app.agent_evals.report import summarise, write_report
from app.agent_evals.server import VariantServer
from app.services.demo_supplier_variants import Variant

DEFAULT_MAX_LLM_CALLS = 40
_LIMIT_MARKERS = (
    "planner unavailable",
    "session limit",
    "429",
    "rate limit",
    "usage limit",
    "limit reached",
)


def _csv(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def _out_dir(root: str) -> str:
    return os.path.join(root, datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))


def run_matrix(
    cases: list[EvalCase],
    *,
    out_dir: str,
    engine: str,
    headless: bool,
    max_llm_calls: int,
    log: bool = True,
) -> tuple[list[CaseResult], list[str]]:
    """Run cases in order; live LLM cases share ONE call budget and stop on a rate limit."""
    flow = baseline_flow()
    results: list[CaseResult] = []
    skipped: list[str] = []
    budget = max_llm_calls
    limit_hit = False
    with VariantServer() as server:
        for case in cases:
            if case.mode.allows_llm and (budget <= 0 or limit_hit):
                skipped.append(
                    f"{case.id}: {'rate limit hit' if limit_hit else 'LLM budget spent'}"
                )
                continue
            result = run_case(
                case,
                server,
                flow=flow,
                var_dir=os.path.join(out_dir, "runs"),
                engine=engine,
                headless=headless,
                max_llm_calls=budget if case.mode.allows_llm else 0,
            )
            budget -= result.llm_calls
            results.append(result)
            if case.mode.allows_llm and any(m in result.reason.lower() for m in _LIMIT_MARKERS):
                limit_hit = True
            if log:
                mark = "PASS" if result.success else "FAIL"
                print(
                    f"[{mark}] {case.id:<44} {result.outcome:<9} llm={result.llm_calls} "
                    f"steps={result.steps} flow={result.flow_steps} rules={result.rule_steps} "
                    f"{result.seconds}s  {result.verdict}",
                    flush=True,
                )
    return results, skipped


def _cmd_run(args: argparse.Namespace) -> int:
    mode = EvalMode(args.mode)
    variants = [Variant(v) for v in _csv(args.variants)] or list(Variant)
    parties = [int(p) for p in _csv(args.party)] or list(DEFAULT_PARTIES)
    cases = matrix(variants, parties, [mode])
    out_dir = _out_dir(args.out)
    if mode.allows_llm:
        print(f"[eval] live LLM run: at most {args.max_llm_calls} model calls in total")
    started = time.monotonic()
    try:
        results, skipped = run_matrix(
            cases,
            out_dir=out_dir,
            engine=args.engine,
            headless=not args.headful,
            max_llm_calls=args.max_llm_calls if mode.allows_llm else 0,
        )
    except LlmCallInDeterministicMode as exc:
        print(f"[eval] ZERO-LLM GUARANTEE BROKEN: {exc}", file=sys.stderr)
        return 2
    meta = {
        "mode": mode.value,
        "engine": args.engine,
        "variants": ",".join(v.value for v in variants),
        "parties": ",".join(map(str, parties)),
        "max_llm_calls": args.max_llm_calls if mode.allows_llm else 0,
        "planner": os.getenv("PLANNER", "") if mode.allows_llm else "none",
        "wall_seconds": round(time.monotonic() - started, 1),
        "skipped": "; ".join(skipped) or "none",
    }
    path = write_report(out_dir, results, meta)
    for name, s in summarise(results).items():
        print(
            f"[eval] {name}: {s['passed']}/{s['cases']} passed, llm_calls={s['llm_calls']}, "
            f"mean {s['mean_seconds']}s"
        )
    if skipped:
        print(f"[eval] skipped {len(skipped)} case(s): {skipped[0]}")
    print(f"[eval] report: {path}")
    return 0 if all(r.success for r in results) else 1


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv("../.env")
    load_dotenv()
    ap = argparse.ArgumentParser(prog="agent-eval", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run the eval matrix for one mode")
    run_p.add_argument("--mode", required=True, choices=[m.value for m in EvalMode])
    run_p.add_argument("--variants", help="comma-separated; default: all")
    run_p.add_argument("--party", help="comma-separated party sizes; default: 1,3,5")
    run_p.add_argument("--engine", default="chromium", choices=["chromium", "camoufox", "firefox"])
    run_p.add_argument("--headful", action="store_true")
    run_p.add_argument("--max-llm-calls", type=int, default=DEFAULT_MAX_LLM_CALLS)
    run_p.add_argument("--out", default=os.path.join("var", "agent-evals"))
    sub.add_parser("list", help="list the variants")
    args = ap.parse_args()
    if args.command == "list":
        for variant in Variant:
            print(variant.value)
        sys.exit(0)
    sys.exit(_cmd_run(args))


if __name__ == "__main__":
    main()
