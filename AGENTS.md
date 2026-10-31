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

## API bridge

```bash
cd backend && uv run dump-openapi      # backend/openapi.json
pnpm --filter web generate:api         # frontend/src/lib/api/generated
```

Both artifacts are committed. Never hand-edit the generated client.

## Gotchas

- **The repo path contains a space.** Always quote paths in shell commands; in Node configs use
  `fileURLToPath(import.meta.url)` rather than `new URL(...).pathname`.
- **Ports 27018 / 6380 are shifted on purpose** so a locally installed `mongod` / `redis-server`
  on the default ports cannot silently win over Docker.
- **CI runs on `workflow_dispatch` only** during the hackathon; run the verification commands
  above locally before opening a PR.
- **`backend/var/` is gitignored** agent output (screenshots, traces, trajectory cache).
- **Never commit `.env` or any vault JSON** — vault files hold traveller data and credentials.
- **Everything in the repo is in English:** code, comments, docs, commits, UI copy.
