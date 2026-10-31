# TripSplit — the 3-minute demo

One presenter, one laptop, six phones on screen. The **demo director** plays the five friends
(join, chat, vote, pay) through the real services, so every rule of the product holds on
stage — it just saves you five browsers.

## Before you go on stage (T-10 min)

```bash
docker compose up -d                                   # Mongo :27018 + Redis :6380
cd backend && uv run trip-harness run all              # sanity: every scenario PASS (~10 s)
DEMO_SUPPLIER_URL=http://localhost:8000 \
  SUPPLIERS=pkp_intercity,demo_rail,sim_stay,sim_activity \
  uv run uvicorn app.main:app --port 8000              # backend (APP_ENV=dev: demo routes on)
pnpm dev                                               # frontend -> http://localhost:3000
```

- `cd backend && uv run seed-demo` creates (or keeps) the demo account
  **demo@tripsplit.app / TripSplitDemo2026!** (organization "Łukasz Demo") and tops its wallet
  up to 5 000 zł — idempotent, dev/test only. Log in with it on stage.
- Register the presenter account (or use the demo account), then do a **full dry run** with `pace: "fast"` (below) and
  throw that trip away. A warm run also warms the PKP browser and the agent's trajectory cache
  (the agent then replays the checkout with zero planner LLM calls).
- Keep a terminal open with the cURL snippets below and the fallback section at hand.

## The script (what to click, what to say)

| Time | Click | Say |
|---|---|---|
| 0:00 | Landing page | "Every group trip dies in the group chat: 300 messages, and one person ends up fronting €1,500 for everyone. TripSplit takes it from the group chat to tickets." |
| 0:15 | **New trip**: "Weekend in Prague", Warszawa → Prague, 20–22 Nov, 6 people, budget | "I type one brief, like I'd write it to my friends." |
| 0:30 | Trip room → **Director: full / stage** (or the cURL below) | "My five friends are going to join — these are real accounts, real votes, real payments; the director just drives them for the demo." |
| 0:35 | Watch the six phones | Friends join one by one, "I'm in!", "Prague in Nov 🍻". "The agent is now researching live: real PKP Intercity trains, real stays." |
| 1:00 | Packages appear | "Three ready packages, priced per person, every price linked to its source." |
| 1:10 | Votes come in | "Votes are split at first… and the group converges. Nobody had to organise a poll." |
| 1:30 | Vote closes, shares appear | "The total is split to the grosz. Here is the key rule: **nobody fronts the money** — the agent does not buy anything until every share is paid." |
| 1:40 | Payments land one by one ("paid with BLIK", "paid from wallet") | "Each friend pays their own share, with their own method." |
| 2:00 | Last payment → booking starts (AUTO_BOOK) or click **Book everything** | "The last payment unlocks the purchase. This is the agent buying the train, live, in a real browser — and it asks me once before it pays." Approve. |
| 2:30 | Disruption (the director's last scene, or **Simulate delay**) | "And the part nobody else does: post-purchase care. The train is delayed 95 minutes — the agent rebooks a later one, re-splits the price difference, and the friends top up." |
| 2:50 | Feed + phones all green | "From group chat to tickets, and it keeps looking after the trip. Thank you." |

With `leave_organizer_payment: true` the director stops before your own share and waits — you
make the decisive last payment by hand on stage (a stronger moment, one more click).

## Driving the director

Dev/test only (`APP_ENV=dev` or `test`); everywhere else these routes answer 404. The caller
must be the trip's organizer (the session cookie of the presenter's browser).

```bash
# Start: script = full | vote_and_pay | disruption, pace = stage (~1.5-3 s/beat) | fast
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -X POST localhost:8000/api/trips/$TRIP/demo/director \
  -d '{"script":"full","pace":"stage","leave_organizer_payment":false,"with_disruption":true}'

curl -b cookies.txt localhost:8000/api/trips/$TRIP/demo/director     # live progress (beats)
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" -X DELETE \
  localhost:8000/api/trips/$TRIP/demo/director                         # stop (effects stay)
curl -b cookies.txt localhost:8000/api/trips/$TRIP/demo/phones        # the six-phone grid
```

| Script | Starts from | Plays |
|---|---|---|
| `full` | a new trip (COLLECTING) | friends join (+2 chat lines) → research → spread vote converging on one package → vote close → payments one by one → booking hand-over → disruption + top-ups |
| `vote_and_pay` | VOTING (or PAYING) | the vote and the payments only |
| `disruption` | a CONFIRMED train | the delay, the rebooking re-split, the friends' top-ups |

Every phase skips itself when the trip is already past it, so a script can be restarted after a
stop. Booking: when the AUTO_BOOK feature is on, the last payment starts the purchase by itself
(the director only narrates it); otherwise it says "over to you" and the disruption waits up to
10 minutes (stage) for a confirmed train before skipping itself. The progress response reports
the detected features (`auto_book`, `wallet`).

## Fallback plan

| What fails | Do this (≤ 20 s) |
|---|---|
| PKP search slow/blocked | Restart the backend with `SUPPLIERS=sim_rail,sim_stay,sim_activity` (all simulators) — the trip flow is supplier-agnostic, nothing else changes. Say: "the same flow on our supplier simulators". |
| The agent stalls at a real carrier | Bookings for trains go to our **demo rail site** when `DEMO_SUPPLIER_URL` is set and `demo_rail` is in `SUPPLIERS`: show `http://localhost:8000/api/demo-supplier/rail` — the same agent, a supplier we control. |
| A booking hands off (CAPTCHA/OTP) | That is the feature: "the agent never bypasses a gate — it hands over to a human". Click **Complete manually**. |
| The director fails | `GET .../demo/director` shows `error`; `DELETE` it, then use the demo panel buttons (seed / vote-all / pay-all / disruption) — same services. |
| Everything is on fire | Play the recording; run `uv run trip-harness run prague_happy_path` live in a terminal — the whole trip with invariants in ~2 s. |

## Real vs simulated

| Part | Real | Simulated / demo |
|---|---|---|
| Train search + re-quote | PKP Intercity (`pkp_intercity`): live fares from the e-IC gateway (re-quote at purchase only with `QUOTES=live`; default `static` keeps the searched price) | `sim_rail` |
| Train purchase | — (with `DEMO_SUPPLIER_URL` set, intercity.pl is never used) | the browser agent on our demo rail site (`/api/demo-supplier/rail`) at PKP's real fare; it stops at "Pay now", the final click is simulated |
| Flights | Duffel **test** API (`duffel`): real offers, real orders with a booking reference (`HOLDS=off`: an instant order at the approval) | `sim_flight` |
| Stays | LiteAPI **sandbox** (`liteapi`): real hotels, prebook + book, a real booking id | `sim_stay` (only when LiteAPI finds nothing; the package says it is an example), `sim_stay_site` |
| Sights / ideas | `osm_activities`: real sights near the centre (Wikipedia geo search), shown as free ideas, never bought | — |
| Activities / tickets | — | `sim_activity` (do not enable in the real-data demo: its agent purchase URL does not resolve), `sim_tickets` + `sim_sights` (bought by the agent on our demo ticket shop) |
| Package research | deterministic catalogue over live supplier offers (optionally worded by Claude) | fixture research in the harness |
| Payments | — | the simulated licensed partner "TripSplit Pay" (`PAYMENTS=wallet`): wallets, BLIK/card top-ups, trip escrow, payouts, single-use virtual cards, KYC light, deadline refunds |
| Friends | real accounts, real votes / payments through the services | driven by the demo director / demo panel; seeded users can never sign in (they get made-up document details) |
| Disruption | Duffel airline-initiated changes — only for held orders (`HOLDS=on`); instant orders do not record the order id yet | `POST .../demo/disruption` (the director's last scene) |

Verified runs with numbers and supplier references: [`DEMO-CASES.md`](./DEMO-CASES.md).

## Reset

```bash
# A fresh trip is the simplest reset: create a new one in the UI.
# Wipe the local database entirely (accounts included):
docker compose exec db mongosh --quiet --eval 'db.getSiblingDB("app").dropDatabase()'
# Forget agent runs / screenshots (keeps the trajectory cache under var/agent/trajectories):
rm -rf backend/var/agent/runs
# Re-check everything before going back on stage:
cd backend && uv run trip-harness run all
```

Check the database name (`MONGODB_DATABASE`) and the compose service name in your `.env` /
`docker-compose.yml` before dropping anything.
