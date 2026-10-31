---
name: run-agent
description: Run the booking agent against a supplier URL from the CLI, read its artifacts, debug a run, or write a supplier playbook. Use when the user asks to test the agent on a site, inspect why a run stopped, or teach the agent a new supplier.
---

# Run the booking agent

The agent (`backend/src/app/agent/`) is a browser-driving loop: observe -> decide -> act ->
recover. An LLM planner with vision sees a screenshot plus a compact list of interactive
elements and returns exactly one action per step. It stops before the final pay click and
hands the summary to a human.

## 1. Run it

```bash
cd backend
uv run agent-run --url https://www.saucedemo.com \
  --goal "Log in, add the backpack to the cart and reach the checkout summary" \
  --run-id demo --headful
```

| Flag | Meaning |
|---|---|
| `--url` | the supplier page to start on (required) |
| `--goal` | what to achieve, in plain English (required) |
| `--run-id` | artifacts directory name; defaults to `cli-<timestamp>` |
| `--pay` | do NOT stop before the final pay click (default is to stop) |
| `--max-steps` | step cap, default 40 |
| `--headful` | show the browser window (default headless) |
| `--engine` | `camoufox` (stealth Firefox, default) / `chromium` (enables `live.jpg`) / `firefox` |
| `--vault <file.json>` | flat JSON with values the agent may type; never committed |
| `--no-cache` | ignore the trajectory cache and ask the planner every step |
| `--json` | print a machine-readable result line prefixed with `__AGENT_RESULT__ ` |
| `--await-approval` | at a stop-before-pay `done`, wait for a human decision (see below) |

## 2. Read the artifacts

Everything lands in `backend/var/agent/runs/<run-id>/` (override with `AGENT_VAR_DIR`):

| File | What it is |
|---|---|
| `NN.png` | screenshot before step NN |
| `NN-done.png` / `NN-handoff.png` / `NN-stuck.png` | the terminal frame, named after the outcome |
| `live.jpg` | continuously refreshed frame — only with `ENGINE=chromium` |
| `status.json` | current `milestone`, `reached` milestones, `step`, `reason`, `planner_calls`, `tokens`, `cost_usd` |
| `trace.json` | per step: url, the page render shown to the planner, the chosen action |
| `result.json` | the final `RunResult`: outcome, reason, steps, milestones, tokens, cost, cache hits |

Successful runs also save a trajectory under `backend/var/agent/trajectories/`; the next run
on the same URL replays it and falls back to the planner on the first mismatch.

### The demo supplier

With the backend running on dev (`uv run uvicorn app.main:app --port 8200`), a deterministic
fake rail site lives at `http://localhost:8200/api/demo-supplier/rail` (search -> results ->
passengers -> summary -> confirmation; playbook `skills/localhost.md`). It never blocks, so it
is the target for the live demo and for end-to-end checks:

```bash
uv run agent-run --url http://localhost:8200/api/demo-supplier/rail \
  --goal "Book 6 2nd-class tickets Warszawa -> Praha on 2026-11-20 for the passengers in the vault, stop at the summary" \
  --run-id e2e-rail --vault /tmp/vault.json --max-steps 25
```

### Approval of the final click (`--await-approval`)

This is how the backend runs the agent (`app.agent.launcher.SubprocessLauncher`). When the
loop ends with `done` at the summary, the runner writes `status.json` with
`"outcome": "awaiting_approval"`, keeps the browser open and polls
`runs/<run-id>/approval.json` every second for `{"approved": true|false}`
(timeout `AGENT_APPROVAL_TIMEOUT_S`, default 900 s).

- approved, `AGENT_FINAL_CLICK=simulate` (**the default**): no pay click. A final frame is
  taken and the run ends `done` with reason `simulated confirmation` and a
  `confirmation_ref` like `SIM-1A2B3C` in `result.json`.
- approved, `AGENT_FINAL_CLICK=real`: the same browser session continues with the goal
  "Submit the order / pay now and wait for the confirmation" (up to 10 more steps). Never on a
  real supplier during a demo. Those pay steps are never saved to the trajectory cache.
- rejected or timed out: the run ends `handoff`.

To approve a CLI run by hand: `echo '{"approved": true}' > var/agent/runs/<run-id>/approval.json`.

### A logged-in profile (`AGENT_PROFILE_DIR`)

Set `AGENT_PROFILE_DIR` (e.g. `var/agent/profile`, gitignored with the rest of `var/`) and
Camoufox launches as a persistent context in that directory, so runs reuse cookies and logins.
Log in once by hand:

```bash
AGENT_PROFILE_DIR=var/agent/profile uv run agent-login --url https://www.intercity.pl
```

A visible window opens; log in (PKP Intercity, Booking.com...), accept the cookie banner,
close the window. The agent never sees the password. Only one process can use a profile at a
time — do not run two agents on the same `AGENT_PROFILE_DIR` concurrently.

## 3. Outcomes

| Outcome | Meaning | What to do |
|---|---|---|
| `done` | the planner reached the goal (with `stop_before_pay`: a populated, ready-to-submit summary) | check the `-done.png` frame matches the goal |
| `handoff` | a human-only gate: CAPTCHA, login required, secure payment iframe, BLIK/SMS code | expected; the UI shows the frame and a person takes over |
| `handoff` at a planned milestone | the site profile's `handoff_markers` matched (e.g. e-IC's sign-in / "Continue as Guest" wall -> `guest_screen`) | success by design: the selection is done, the flow is saved, a person continues |
| `stuck` | the same action repeated five times with no visible progress | look at `-stuck.png` and `trace.json`; usually a banner or a playbook gap |
| `max_steps` | step cap hit without a terminal state | raise `--max-steps` or tighten the goal / playbook |
| `error` | an exception in the loop (browser crash, network, missing key); `reason` holds the repr | fix the environment, rerun with `--headful` |

## 4. The vault

A flat JSON file of `key -> value`:

```json
{
  "first_name": "Anna",
  "last_name": "Nowak",
  "email": "anna@example.com",
  "phone": "+48600000000",
  "username": "standard_user",
  "password": "secret_sauce"
}
```

The planner sees **key names only** and emits `{{vault.key}}` placeholders; `act.py`
substitutes the real values at action time, so secrets never reach the model. Empty values are
dropped. The CLI also accepts the same JSON through the `AGENT_VAULT_JSON` env variable.

## 5. Write a supplier playbook

Playbooks live in `backend/src/app/agent/skills/<host>.md` and are injected into the planner
prompt for matching hosts. Matching is by host suffix: `intercity.pl.md` applies to
`www.intercity.pl` and `bilet.intercity.pl`; an exact `<host>.md` wins, then the longest
suffix; `_default.md` is the fallback for every other site.

Good playbook content:

- the **stable shape** of the site: the order of checkout steps, how the search form behaves,
  where the guest-checkout option hides, which upsells to skip;
- which controls are mandatory and which are decoys;
- when to call `handoff` on this site specifically.

Never put in a playbook:

- pixel coordinates or element indices — they change on every render;
- narration or step-by-step logs from one run;
- secrets or traveller data — those belong in the vault.

Do reconnaissance with `browser-harness` (CDP in your own Chrome) and distil what you learned
into a few bullet points. Keep it under ~4000 characters; the loader truncates beyond that.

## 6. The engine: flows, rules, LLM — and the eval suite

DECIDE is a cascade, cheapest and most certain first: a pending macro plan -> the compiled
**flow** (`agent/flows.py`) -> the **rule layer** (`agent/rules.py`, driven by the typed site
profile in `agent/site_profiles.py`) -> the **LLM planner**, which then returns a short plan
(up to `PLANNER_MAX_PLAN`, default 4 actions) instead of one action. A `done` at a summary is
always re-checked by the deterministic summary verifier, and the pay button is never pressed
while `stop_before_pay` is on.

| `--mode` | layers | LLM |
|---|---|---|
| `auto` (default, `AGENT_MODE`) | flow + rules + planner | yes |
| `replay` | flow + rules | no |
| `rules` | rules only | no |
| `llm` | rules + planner | yes |
| `planner` | planner only (the pre-engine behaviour) | yes |

`--max-llm-calls N` caps model calls for a run. Screenshots go to the planner only when the
text is thin (`PLANNER_SCREENSHOT=auto|always|never`); otherwise it gets the accessibility tree.

Flows are stored in `var/agent/trajectories/<host>.flow.json` (version 2): stable descriptors,
values bound to `{{vault.*}}` / `{{goal.*}}`, passenger blocks as a loop, offer clicks as a
choice resolved from the goal. A legacy `<host>.json` trajectory is compiled on load. A run
that healed a flow miss saves the re-compiled flow.

New artifacts and fields (additive): `runs/<id>/flow_graph.json` (nodes/edges, variable names
only); `status.json.steps[]` (`index, node_id, kind, status, duration_ms, source`);
`result.json` adds `mode, llm_calls, flow_steps, rule_steps, plan_steps, heal_steps,
flow_misses, wall_s, final_stage, summary` (the supplier summary as read, names masked).

Evals — perturbed demo sites under `/api/demo-supplier/rail-variants/<variant>` (dev/test) and
a self-contained local server for the CLI:

```bash
uv run agent-eval list
uv run agent-eval run --mode replay                 # 10 variants x party 1/3/5, 0 LLM calls
uv run agent-eval run --mode rules_only --variants baseline,slow --party 3
uv run agent-eval run --mode live_llm --variants baseline,split_pages --party 3 --max-llm-calls 20
```

Reports: `backend/var/agent-evals/<ts>/report.{md,json}`. `replay`/`rules_only` exit 2 if a
model was ever called; `live_llm` stops at the call budget or the first rate limit.

Real third-party sites (BlazeDemo end to end, intercity.pl to the guest screen): exact
commands and findings in AGENTS.md, section "Real sites (real_sites)".

## Traps

- With `PLANNER=openai`, `OPENAI_API_KEY` must be set in `.env` at the repo root (the CLI
  loads `../.env` then `.env`). `PLANNER=claude-cli` needs a logged-in `claude` instead.
- The first run needs the stealth browser: `uv run python -m camoufox fetch` (and
  `uv run playwright install chromium` for `--engine chromium`).
- `https://www.saucedemo.com` is the safe smoke target. Username `standard_user`, password
  `secret_sauce` — public demo credentials, fine to put in a local vault file.
- **Never run with `--pay` against a real supplier.** The default stop-before-pay is the
  product's safety rule.
- CAPTCHA, OTP and 3-D Secure are deliberately **not** bypassed — they produce `handoff`. Do
  not add workarounds.
- `backend/var/` is gitignored; vault JSON files must never be committed.
