# Search evals

The package research (`app.ai.catalog_research.CatalogResearcher`) run over a fixed dataset of
24 trip briefs against recorded supplier answers, scored against an oracle of the best possible
combinations. Deterministic, free, ~1 s for the whole dataset in replay.

```bash
cd backend
uv run search-eval list                                   # the briefs
uv run search-eval run                                    # replay (default) -> var/search-evals/<ts>/
uv run search-eval run --briefs waw-prg,krk-vie           # a subset (id prefixes)
uv run search-eval compare var/search-evals/<a> var/search-evals/<b>
# record what is missing, live (PKP via Camoufox ~15 s/search, Duffel test ~4 s, LiteAPI sandbox ~6 s):
uv run search-eval run --mode record --quotes
uv run search-eval run --mode live --briefs waw-prg       # live, nothing written
```

Exit code 1 = a brief errored (in replay: a search that was never recorded), 2 = the research
made an LLM call (it must make none; `llm_guard.py` refuses and counts them).

## Pieces

| module | what |
|---|---|
| `dataset.py` | `EvalBrief`s: origin Warszawa/Kraków/Gdańsk, 7 destinations, party 2/4/6/8, budget tight (800 PLN pp) / medium (1600) / none, weekend vs midweek Nov-Dec 2026, mode any / rail / flight / fly there + train back, optional earliest departure hour |
| `cassette.py` | `RecordingSupplier` around any `SupplierAdapter`: `record` / `replay` / `live`; `var/search-evals/cassettes/<supplier>/<hash>.json` + `suppliers.json` (replay needs no adapter, key or browser) |
| `suppliers.py` | live: `pkp_intercity` (BrowserTransport), `duffel` (test key), `liteapi` (sandbox key), `sim_activity`; `sim_stay` without a LiteAPI key |
| `oracle.py` | every supplier's return + one-way offers (all modes), stays, activities -> the cheapest complete and the cheapest schedule-sane combination in the wished modes, budget feasibility |
| `checks.py` | schedule checks (day one / arrival / checkout day / connections / city-level places / ≤ 14 h per way / no 00-05 departure / earliest hour) |
| `metrics.py` | per brief: completeness, budget, optimality, diversity, schedule, consistency, mode (+ quote drift, latency, LLM calls); weighted score; summary |
| `report.py` | `report.md` / `report.json`, `compare` |

Metric definitions are in `metrics.py` (and in every `report.md`). The cassette key leaves out
the budget and a mode equal to the supplier's own, so briefs share recordings; the oracle asks
every transport mode whatever the wish, so a research that falls back to another mode replays.
Recordings carry offers only — no traveller data; the wrapper never holds or buys.
