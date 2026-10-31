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

## 3. Outcomes

| Outcome | Meaning | What to do |
|---|---|---|
| `done` | the planner reached the goal (with `stop_before_pay`: a populated, ready-to-submit summary) | check the `-done.png` frame matches the goal |
| `handoff` | a human-only gate: CAPTCHA, login required, secure payment iframe, BLIK/SMS code | expected; the UI shows the frame and a person takes over |
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

## Traps

- `OPENAI_API_KEY` must be set in `.env` at the repo root (the CLI loads `../.env` then `.env`).
- The first run needs the stealth browser: `uv run python -m camoufox fetch` (and
  `uv run playwright install chromium` for `--engine chromium`).
- `https://www.saucedemo.com` is the safe smoke target. Username `standard_user`, password
  `secret_sauce` — public demo credentials, fine to put in a local vault file.
- **Never run with `--pay` against a real supplier.** The default stop-before-pay is the
  product's safety rule.
- CAPTCHA, OTP and 3-D Secure are deliberately **not** bypassed — they produce `handoff`. Do
  not add workarounds.
- `backend/var/` is gitignored; vault JSON files must never be committed.
