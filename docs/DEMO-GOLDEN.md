# The golden path — live demo script

One chat at `/plan`: one sentence → offer cards → pick → pay → the agent buys → tickets.
Everything runs on simulators (no real money, no LLM): the train is bought by the real
booking agent on our own demo rail site (rules + recorded flow, 0 LLM calls), the stay and
the flight through simulated APIs.

Covered by `frontend/e2e/chat-flow.spec.ts` (train + flight, fresh account each run).

## Setup (once, before the audience arrives)

Repo-root `.env` (the values that matter):

```bash
APP_ENV=dev
SUPPLIERS=sim_rail,sim_flight,sim_stay,sim_activity,sim_tickets,sim_sights,demo_rail
DEMO_SUPPLIER_URL=http://localhost:8830   # = the backend's own URL: trains are bought on the demo rail site
PLANNER=none                              # no LLM anywhere
RESEARCHER=catalog
HOLDS=off
AUTO_BOOK=true                            # purchases start by themselves once everything is paid
API_PORT=8830
WEB_PORT=3830
```

```bash
docker compose up -d
cd backend && uv run seed-demo                        # demo account + 5 000 zł in the wallet
uv run uvicorn app.main:app --port 8830               # terminal 1
cd .. && WEB_PORT=3830 API_PORT=8830 pnpm dev         # terminal 2
```

Warm-up (do ONE full train run before going live — the first agent launch starts the
browser engine cold): follow the script below once, then reset.

## The script (exact clicks and text)

1. Open <http://localhost:3830/login> → **Email** `demo@tripsplit.app`, **Password**
   `TripSplitDemo2026!` → **Sign in**.
2. Open <http://localhost:3830/plan> ("Where are we going?").
3. Type in **Message** and press **Send**:

   ```text
   Weekend in Prague for 4, 20-22 Nov, under 900 zł each, by train
   ```

   → "Got it…" + chips (From Warszawa, To Prague, 20–22 Nov, People 4, Budget 900 PLN pp,
   Train) → supplier ticks ✓ → "Found 5 ways to get there, 4 stays…" (~1–3 s).
4. **How do you want to get there?** → **Pick** on the first card ("PKP Intercity train +
   Demo rail train", ~345 zł pp).
5. **Where do you want to stay?** → **Stay here** on the first card (Central hostel).
6. **Anything to do while you're there?** → **Skip**.
7. **Summary** ("Total for 4 people 1 818.60 PLN · 454.65 PLN per person · within budget") →
   **Looks good**.
8. If **Your details** appears (fresh account only): **Name on the document** `Demo
   Organizer` → **Save my details**.
9. **Who pays** → **I'll pay for everyone**. If **Verify my ID** appears (an account whose
   top-ups exceed 1 000 zł): **Full name** `Demo Organizer`, **Date of birth** `1990-05-17`
   → **Verify my ID**.
10. **Pay for everyone** → **BLIK code** `123456` → **Pay 1 818.60 PLN**.
    → "Every share is paid…", "Everyone paid. The agent can book now." → **Booking
    everything…** with the live strip (the agent on the demo rail site).
11. ~15–20 s later: "Everything is ready at the suppliers. Nothing is paid until you
    approve." → **Approve basket (total 1 818.60 PLN)**.
12. ~3–5 s: "Done — all 3 booked. Here are your tickets." — three ticket cards with
    booking refs (`SIM-xxxxxx` ×2 for the trains, `SIMSTAY-00nn` for the hostel).

### Flight variant (no browser agent — the fastest)

Same steps with:

```text
Weekend in Barcelona for 2, 13-15 Nov, by plane
```

An airline needs documents: on a fresh account **Your details** asks for name, date of
birth, nationality (`PL`), passport (`EH1234567`), expiry and gender. The demo account
already has them after the first run. Tickets: `SIMFLIGHT-000n` + `SIMSTAY-00nn`.

## Expected timings (measured, scripted clicks)

| Case | Brief → cards | Pay → "Approve basket" | Approve → tickets | Whole run |
|---|---|---|---|---|
| Train (agent) | 1–3 s | 15–25 s | 3–5 s | 28–46 s (5/5 passes) |
| Flight (API) | 1–3 s | 2–3 s | 1–2 s | 11–17 s (3/3 passes) |

At a human pace add ~30 s of talking and clicking: about 60–75 s for the train.

## 30-second reset (between runs)

1. Open <http://localhost:3830/plan> again (plain URL, no `?trip=`) — the next message
   creates a fresh trip; old trips are never reused.
2. Refill the wallet: `cd backend && uv run seed-demo` (idempotent, < 1 s; tops the demo
   wallet back up to 5 000 zł).
3. Nothing else: no restart needed. Do not reuse a `?trip=` URL from a finished run.

## If something goes wrong on stage

- **"I couldn't finish … Try again"** in the Booking bubble: click **Try again** (it restarts
  the failed purchase; nothing was paid for it). If it fails again, **Open trip room**, or
  switch to the flight variant.
- **"The options didn't load"**: **Try again**, or **Open trip room** for the ready-made
  packages.
- **Stuck on "Booking everything…" > 60 s**: the agent's artifacts are in
  `backend/var/agent/runs/<run-id>/` (`agent.log`, `status.json`, screenshots); start a fresh
  trip (reset above) and use the flight variant.
- Pre-flight smoke test: `cd frontend && WEB_PORT=3830 API_PORT=8830 pnpm exec playwright test
  e2e/chat-flow.spec.ts` (≈ 1 min, both cases on fresh accounts).
