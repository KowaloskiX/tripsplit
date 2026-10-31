# AGENTS.md — operational cheat sheet

**TripSplit — "from group chat to tickets".** An agent proposes trip packages to a group of
friends, collects votes and each person's share, books train + stay live, and rebooks on
disruption. Monorepo: TanStack Start frontend + FastAPI/Beanie/MongoDB backend + a
Playwright-driven booking agent.

- Engineering rules: [`CLAUDE.md`](./CLAUDE.md) (and [`frontend/CLAUDE.md`](./frontend/CLAUDE.md)).
- Product, architecture, phases, work split: [`docs/PLAN.md`](./docs/PLAN.md).
- Skills (step-by-step playbooks): `.claude/skills/` and `.devin/skills/` (same content).

## Environment

Node 24 (`.nvmrc`) + pnpm 11 via corepack, Python 3.12 + uv 0.9.11, Docker.
`mise install` (reads `mise.toml`) is the optional shortcut to exactly those versions.

## Setup

```bash
cp .env.example .env            # set AUTH_SECRET (openssl rand -hex 32) and OPENAI_API_KEY
docker compose up -d            # MongoDB (replica set) :27018 + Redis :6380
cd backend && uv sync && uv run python -m camoufox fetch && uv run playwright install chromium
cd .. && pnpm install
```

## Run

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000   # backend
pnpm dev                                                          # frontend -> :3000
WEB_PORT=3100 API_PORT=8100 pnpm dev                              # other ports (turbo passes both through)
curl localhost:8000/api/health                                    # {"status":"ok",...}
```

## Verify

```bash
pnpm verify                     # frontend: biome -> tsc -> dependency-cruiser -> vitest -> build
cd backend && uv run ruff check src tests scripts && uv run ruff format --check src tests scripts \
  && uv run mypy && uv run lint-imports && uv run pytest        # pytest needs Docker (testcontainers)
```

## Agent CLI

```bash
cd backend && uv run agent-run --url https://www.saucedemo.com --goal "..." --run-id demo --headful
```

Artifacts land in `backend/var/agent/runs/<run-id>/` (per-step `NN.png`, `status.json`,
`trace.json`, `result.json`, `live.jpg` on Chromium). Env knobs: `OPENAI_API_KEY`,
`PLANNER_MODEL`, `ENGINE`, `HEADLESS`, `AGENT_VAR_DIR`. Details: `.devin/skills/run-agent/SKILL.md`.

## Trip harness

```bash
cd backend && uv run trip-harness list
uv run trip-harness run all                                  # fast: fixture research, scripted agent (~10 s)
uv run trip-harness run prague_happy_path --live-search      # real PKP Intercity train prices (~15 s)
uv run trip-harness run prague_happy_path --live-agent       # real agent on its own demo rail supplier (~30 s)
```

Whole group trips through the real services and a fresh `harness_<timestamp>_<scenario>`
database (dropped unless `--keep-db`), invariants checked after every step. Scenarios live in
`backend/src/app/harness/scenarios/`; reports in `backend/var/harness/<timestamp>/`. Steps that
need an unmerged domain feature are `pending`; scenarios documenting a bug are `xfail`. The
same scenarios run in pytest (`tests/e2e/test_trip_scenarios.py`). Exit code 1 = an unexpected
step failure or invariant violation.

## Suppliers (plugins)

The trip flow is supplier-agnostic: rail, flights, buses, stays and activities are adapters
behind `backend/src/app/suppliers/ports.py` (`SupplierAdapter`), each declaring
`SupplierCapabilities` (kind/mode, channel `api`/`agent`/`manual`, purchase cap, holds, quote
TTL, required traveller fields). Services read capabilities, never supplier names. Enable them
with `SUPPLIERS=` (simulators `sim_*`, real `pkp_intercity`, `demo_rail`, `duffel`).

**Duffel (real flights, test mode).** `SUPPLIERS=...,duffel` plus `DUFFEL_API_KEY=duffel_test_...`
in `.env` enables `suppliers/duffel.py`: real offer search, a named HOLD order at Duffel, payment
of the held order on approval, airline-initiated changes as disruptions. A live key is refused
unless `DUFFEL_ALLOW_LIVE=true`; without a usable key the supplier is simply not registered.
EUR prices are converted to PLN at `DUFFEL_FX_EUR_PLN` (default 4.30) — Duffel is always paid
its own EUR amount. An airline hold names every passenger, so it is placed at voting close only
when everyone's details (name, birth date, **gender**, passport fields) are in, otherwise when
the purchase starts (`hold_needs_traveller_details`). Offers expire after ~30 min; the adapter
re-finds the same flights by number + departure time. City -> airport codes: `suppliers/airports.py`.

```bash
cd backend && uv run trip-harness run all            # simulated suppliers, scripted agent
cd backend && uv run trip-harness run prague_happy_path --live-search   # real PKP (~20 s)
uv run trip-harness run barcelona_duffel_live --live-flights        # real Duffel test API (~6 s)
uv run trip-harness run barcelona_duffel_slow_group --live-flights  # expired offer re-found
DUFFEL_LIVE=1 uv run pytest tests/test_duffel.py                    # + the live search smoke test
uv run beanie migrate -uri "$MONGODB_URL" -db "$MONGODB_DATABASE" -p migrations
```

## Demo on real data

The app itself (not only the harness) can run on real suppliers. In the repo-root `.env`:

```bash
SUPPLIERS=pkp_intercity,duffel,sim_stay,sim_activity   # + liteapi once feat/liteapi is merged
DUFFEL_API_KEY=duffel_test_...                          # a TEST token; live is refused
DEMO_SUPPLIER_URL=http://localhost:8000
HOLDS=off
PKP_TRANSPORT=browser                                   # the default
```

- **Real:** PKP Intercity train search and re-quotes (unofficial e-IC JSON gateway through one
  shared headless Camoufox in the API process — ~5 s warm-up on the first PKP call, then about
  1 s per call; a 6-person return trip needs ~25 s of research), Duffel flight search, quotes and
  orders in **test mode** (Duffel Airways etc., nothing is charged).
- **Simulated:** stays and activities (`sim_*`), the group's payments (`PAYMENTS=fake`) and the
  train *purchase* — with `DEMO_SUPPLIER_URL` set, train bookings point the agent at our own
  demo rail site, never at intercity.pl.
- **No real money moves anywhere.** Duffel test orders are free, payments are fake, and the
  agent stops before any real payment page.
- `HOLDS=off`: nothing is held at voting close; each purchase re-quotes right before it starts
  (a moved price re-splits the shares, `price_changed`), and an API supplier books when the
  basket is approved (Duffel instant order). `HOLDS=on` restores holds at voting close.
- One click each in the room: **Book everything** (`POST /trips/{id}/bookings/start-all`) and
  **Approve basket** (`POST /trips/{id}/bookings/approve-all`, refused unless every share is
  paid). The live agent panel draws the run's plan from `GET /agent-runs/{run_id}/graph`.

## API bridge

```bash
cd backend && uv run dump-openapi      # backend/openapi.json
pnpm --filter web generate:api         # frontend/src/lib/api/generated
```

Both artifacts are committed. Never hand-edit the generated client.

## Gotchas

- **A train for more than 5 is several PKP bookings.** `purchase_cap()` in
  `core/domain/bookings.py` is the single place that knows per-supplier caps; each part has its
  own `passenger_user_ids` and the agent vault holds only those passengers (`passenger_1..N`).
- **Every start re-quotes first** (`QUOTES=static` by default = stored amount). A price change
  beyond `PRICE_TOLERANCE_PERCENT` re-splits the shares (`services/resplit.py`); a rise sends
  the trip back to `paying` and the start answers 409 `price_changed`.
- **A disruption replaces every purchase of the train** (all CONFIRMED parts sharing
  `proposal_item_index`), each repriced on its own, then one re-split. After top-ups the trip
  resumes REBOOKING while a replacement is unbought (`resume_status()`), otherwise BOOKING.
- **Approving a summary is a purchase:** refused with 409 `trip_not_ready` unless the trip is
  BOOKING/REBOOKING and every current share is paid; the run keeps waiting.
- **Refunds are paid out when the trip reaches BOOKED** (`BookingService._settle_refunds`
  through `PaymentProvider.refund`, one `refund_issued` event each) — not at re-split time,
  because a later rebooking could still need the money.
- **Demo bookings go to the fake rail site only if `DEMO_SUPPLIER_URL` is set** (dev/test,
  e.g. `http://localhost:8000`): it enables the `demo_rail` supplier AND makes `pkp_intercity`
  offers point their purchase at `/api/demo-supplier/rail` (real PKP price, fake checkout — the
  site lists its own three trains, so the agent books the closest one there). Without it, a PKP
  booking would send the agent to the real intercity.pl. Agent-channel stays/activities (e.g.
  `sim_stay_site`) still point at real sites — do not start them in a demo.
- **Bookings stuck after a backend restart heal on the next listing:** a still-alive agent
  (`agent.pid`) is re-attached, a `result.json` is applied, anything else fails the booking.

- **The repo path contains a space.** Always quote paths in shell commands; in Node configs use
  `fileURLToPath(import.meta.url)` rather than `new URL(...).pathname`.
- **Ports 27018 / 6380 are shifted on purpose** so a locally installed `mongod` / `redis-server`
  on the default ports cannot silently win over Docker.
- **CI runs on `workflow_dispatch` only** during the hackathon; run the verification commands
  above locally before opening a PR.
- **`backend/var/` is gitignored** agent output (screenshots, traces, trajectory cache).
- **Never commit `.env` or any vault JSON** — vault files hold traveller data and credentials.
- **Everything in the repo is in English:** code, comments, docs, commits, UI copy.
