# Demo cases — verified end to end on real data

Every number below comes from a real run on 31 Oct 2026 (worktree `tripsplit-n`, backend :8840,
web :3840, `SUPPLIERS=pkp_intercity,duffel,liteapi,sim_stay,sim_activity,osm_activities,sim_tickets,sim_sights`,
`HOLDS=off`, `AUTO_BOOK=true`, `DEMO_SUPPLIER_URL` set). Screenshots and JSON dumps from the run
are in `/tmp/tripsplit-cases/<case>/` (not committed). Supplier references were checked
**at the supplier** (Duffel `GET /air/orders/{id}`, LiteAPI `GET /bookings/{id}`), not only in
our database.

**Ground rules for what we say:** PKP prices are live. Duffel and LiteAPI are real APIs in
**test / sandbox** mode (real offers and orders, no money). The train *purchase* runs on our own
demo rail site (real PKP price, fake checkout); the agent stops at "Pay now" and the final click
is simulated. All money moves inside the simulated payment partner "TripSplit Pay".

## Before going on stage (T-15 min)

```bash
cd backend && uv run seed-demo        # demo@tripsplit.app / TripSplitDemo2026!, 5 000 zł, traveller details filled
# Warm-up: run case 1 and case 2 once, fast, and throw the trips away. Search results are cached
# IN THE API PROCESS: do not restart the backend after the warm-up.
```

- A cold LiteAPI search for Stockholm took > 15 s (the sandbox answers `429` on prebook under
  load) and the package then showed an **example** stay; warm, the same search took 0.6 s.
- Use `seed-demo` again between rehearsals: the demo wallet drains (each run pays shares).

## Ranking

| # | Case | Real | Wow | Risk |
|---|---|---|---|---|
| 1 | Prague by train for 6: pay → agent buys 3+3 → delay → rebook → re-split | PKP live prices, LiteAPI sandbox booking | highest | low (after fix 6957f85) |
| 2 | Poznań → Stockholm by plane for 4 | Duffel test order + LiteAPI sandbox, verified at both | high | medium (cold LiteAPI) |
| 3 | One sentence to tickets (quick brief) | Duffel + LiteAPI | high | **medium: friends must join first** |
| 4 | The money trail (escrow, single-use cards, payouts, refunds, deadline) | simulated partner, real ledgers | high (trust) | low |
| 5 | The agent refuses: rule #1, CAPTCHA, sold out, price moved | demo site variants, 0 LLM calls | medium-high | low |
| 6 | Attractions vote → day plan → agent buys museum tickets | sim tickets on our demo shop | medium | medium (see bugs) |

---

## 1. Warszawa → Praha by train for six — buy, then look after the trip

**Say:** "Six friends, one weekend. These are live PKP Intercity fares. Everyone pays their own
share into an escrow; the last payment starts the agent, which buys the train as two orders of
three — PKP sells at most five per order — and the hotel through a real booking API. Then the
train is delayed: the agent rebooks, re-splits the difference to the grosz, and the friends top up."

**Clicks** (UI) — or the API calls in brackets:
1. New trip: Warszawa → Praha, 20–22 Nov, 6 people, train (`POST /api/trips`).
2. Demo panel → seed members ×5 (`POST .../demo/seed-members {"count":5}`), research
   (`POST .../proposals/generate`). Research: **14 s** cold (PKP + LiteAPI live).
3. Vote Budget for all, close voting (`.../demo/vote-all`, `.../voting/close`).
4. Wallet top-up with BLIK `777123` (completed in **1.6 s**), friends pay (`.../demo/pay-all`),
   "Pay my share" → AUTO_BOOK starts every purchase.
5. Bookings → **Approve basket** (`.../bookings/approve-all`): BOOKED **7.9 s** later.
6. **Simulate disruption** (+12 %, 95 min) → friends + you top up → AUTO_BOOK rebooks → approve.

**Numbers from the run** (trip `6ae5aad8ab24fd29880e8a0d`):

| | |
|---|---|
| Package (Budget) | 4 330.26 PLN = 721.71 PLN × 6 |
| Train out, EC 131 Batory 07:52 | PKP live 155.65 PLN/person → 2 orders × 466.95 |
| Train back, EC 113 Silesia 06:08 | PKP live 178.40 PLN/person → 2 orders × 535.20 |
| Train total | 2 004.30 PLN = sum of the four orders = the PKP fares × 6 (checked) |
| Stay | Mama Shelter Prague, 3 × Medium Mama Double, 2 325.96 PLN — LiteAPI **`tzf-Cxm2H`, CONFIRMED, sandbox=1, 3 rooms** (verified at LiteAPI) |
| Agent | 4 runs, summary verified (3 passengers, date, total), **0 LLM calls**, ~25–45 s each |
| Payment | 4 single-use virtual cards (`card_…`, •••• 4242) activated at the approval for exactly the amount, captured once, closed; LiteAPI paid by payout `po_419b6b08b02ee1c6` |
| Disruption +12 % | outbound 2 × 466.95 → 2 × 522.98; total 4 442.32; shares +18.68 / +18.67; refunded card charges back into the escrow (held 933.90) |
| Rebooked | `SIM-F04A95`, `SIM-608192`; escrow spent = collected = 4 442.32 |

**Real vs simulated:** PKP search and fares — real (live e-IC gateway). LiteAPI search, prebook
and book — real sandbox. Train checkout — our demo rail site (lists its own trains, so the agent
books "EC 111" there at PKP's price: the run reason says so); final click simulated. Payments,
escrow, cards — simulated partner. Friends — seeded accounts driven by the demo panel/director.

**Honest notes:**
- The catalogue picked two **one-way** singles (≥ 5 % cheaper than the PKP return), so the train
  is 4 orders, not "one return order". A real return (one order per 3+3 part) exists: the
  Splurge package of case 6 shows "EC 131 Batory · return" for 1 693.00 PLN bought as one order.
- The cheap single home leaves Praha at **06:08** on Sunday.
- The rebooked train on the demo site is the same EC 111 (the site has three fixed trains).

**Fallback:** `uv run trip-harness run prague_happy_path --live-search` (real PKP, ~20 s) or
the same flow on simulators (`SUPPLIERS=sim_rail,sim_stay`).

## 2. Poznań → Stockholm by plane for four — real airline order, real hotel booking

**Say:** "Different city, different mode, same product. The flight is a real Duffel order —
here is the airline booking reference — and the hotel a real LiteAPI booking. Sights come from
Wikipedia, as free ideas."

**Clicks:** new trip Poznań → Sztokholm, 13–15 Nov, 4, plane; seed 3; research; Budget; close;
friends pay; pay my share; approve basket.

**Numbers** (trip `6ae5afbc2a417b26ce50f31f`): research **0.6 s warm** (15.2 s cold, without
LiteAPI); total 5 267.60 PLN, 1 316.90 each. From the last payment to both summaries **3.4 s**;
approve → BOOKED **5.9 s**.

| | |
|---|---|
| Flight | Duffel Airways ZZ 7426 POZ → VST (Västerås) return, 1 445.66 PLN = **336.20 EUR × 4.30**; booking ref **`BFC7XT`** = order `ord_0000BBxy56Pste0bZGY4DI`, `live_mode: false`, type instant, 4 passengers, paid (verified via `GET /air/orders/{id}`) |
| Stay | Clarion Hotel Sign, 2 × Superior Twin, 3 821.94 PLN — LiteAPI **`kQpG09Uvi`, CONFIRMED, sandbox=1, 2 rooms** |
| Ideas | Nationalmuseum, Gamla Stan, Moderna Museet, Royal Dramatic Theatre, House of Nobility (Wikipedia geo search, not bought) |
| Money | payouts `po_0125f09c00fcc018` (Duffel), `po_2874694c01e3beff` (LiteAPI); escrow 5 267.60 → 0 |

**Real vs simulated:** Duffel offers and order — real test mode (Duffel Airways is Duffel's test
airline). LiteAPI — real sandbox. Ideas — real Wikipedia. Payouts — simulated partner.

**Fallback:** `uv run trip-harness run barcelona_duffel_live --live-flights` (PASS, 34.6 s in
this run). To show the order exists at Duffel: `GET https://api.duffel.com/air/orders?booking_reference=BFC7XT`
with the test token from `.env` (never print the token), then `GET /air/orders/{id}`.

## 3. One sentence to tickets

**Say:** "I type one sentence in Polish. The trip exists, three packages are researched, my
friends join, I pay for everyone, and it is booked."

**Clicks:** `/plan` → type `weekend w Barcelonie dla 4, 13-15.11, do 2000 zł/os, samolotem` →
packages (0.2 s warm). **Then open the trip room and let the friends join first** (Demo panel →
seed members ×3) → back to the package → "I'll pay for everyone" → approve basket.
API: `POST /api/trips/quick {text}` (**0.03–0.07 s**, origin defaults to Warszawa) →
`.../demo/seed-members` → vote/close → `POST .../contributions/pay-all-shares {"method":"blik","blik_code":"777123"}`
→ `.../bookings/approve-all`.

**Numbers** (trip `6ae5b1072a417b26ce50f39e`): 4 795.86 PLN (1 198.97 / person); pay-all-shares
topped the wallet up by BLIK (4 591.72) and paid 4 shares; summaries **6.2 s** after; BOOKED
**12.2 s** after the vote. British Airways BA 0107 WAW–BCN via Duffel, **`FFGDIL`** = 
`ord_0000BBxyZmZtezJnKM0K4y`, 638.48 EUR × 4.30 = 2 745.46 PLN; LiteAPI **`nXdty-bQ_`**
(Ilunion Les Corts Spa, 2 rooms, 2 050.40 PLN, CONFIRMED). Both verified at the supplier.

**Do not** click "I'll pay for everyone" before anybody joined: the vote closes with one member,
one share of the 4-person total is paid, and every purchase is re-quoted for **one** traveller
(seen live: flight 2 745.46 → 671.57, a 3 119.41 PLN refund due). Reported to the lead.

**Fallback:** `uv run trip-harness run quick_solo_trip` (PASS).

## 4. The money trail — nobody fronts the money, and it always comes back

**Say:** "TripSplit never holds your money: a licensed partner does. Shares sit in a trip escrow.
The agent gets a single-use card for exactly one purchase, funded only at my approval. APIs are
paid out directly. When something fails or gets cheaper, the money goes back by itself."

Show, in order (all from this run):
1. **Held:** room → Trip money: `escrow wlt_…`, funded 4 330.26 of 4 330.26 before anything is bought.
2. **Card used once:** feed "The agent paid PKP Intercity 522.98 PLN with a single-use virtual
   card •••• 4242 funded from the trip escrow; the card is closed now." Ledger: `card_funding`
   52 298 → `card_capture` 52 298, card status `used`, a card whose run handed off is `closed`
   with 0 spent.
3. **Payouts:** Duffel `po_0125f09c00fcc018`, LiteAPI `po_2874694c01e3beff`.
4. **A payout reversed:** Duffel re-priced 671.57 → 678.84 PLN between quote and order; the
   order was refused (never pay more than approved) and `po_a5ff3d71d0387fe2` came back as a
   `payout_reversal` — escrow intact.
5. **Refund after a cheaper rebooking:** Prague, return train delayed, −15 %: shares 740.39 →
   713.63, trip straight to REBOOKING, rebooked (`SIM-C365A8`, `SIM-6050DB`), then
   **160.56 PLN refunded** (6 × 26.76) to the wallets; escrow 0.
6. **Deadline refund:** trip "Unpaid Prague" (`6ae5b3fe2a417b26ce50f4c9`): 3 of 4 paid
   (2 116.44 PLN), pay-by moved to +15 s (`POST .../pay-by`), the sweep expired the trip within
   ~30 s and returned all 2 116.44 PLN ("Not everyone paid by the deadline, so nothing was booked…").

**Real vs simulated:** all of it runs in the simulated partner (`FakePartner`, its own ledger
with idempotency keys); the production mapping is in AGENTS.md (Mangopay / Stripe Issuing).

**Fallback:** `uv run trip-harness run escrow_happy_path` and `funding_deadline_refund` (PASS).

## 5. The agent refuses — and says why

**Say:** "The agent never pays before everyone has, never bypasses a CAPTCHA, and never pays a
price nobody approved."

| Situation | How | Result in this run |
|---|---|---|
| Rule #1 | one share unpaid → **Book everything** | 409 `trip_not_ready` "Booking starts only once everyone has paid their share." |
| CAPTCHA | `agent-run --url .../api/demo-supplier/rail-variants/captcha?...` | handoff "visible captcha challenge (.g-recaptcha)" in **8.3 s**, 0 LLM calls |
| Sold out | variant `sold_out` | handoff "supplier reports: Sold out", 5.9 s |
| Price moved on the summary | variant `price_changed_on_summary` | handoff "supplier total 236.25 vs expected 149.00 (+58.6 %, tolerance 1 %)" |
| Price moved before the purchase (live) | LiteAPI re-quote at start | "The Julius Prague raised the price … 9.73 PLN more each. Top up and I will buy it." → trip back to PAYING → top-ups → AUTO_BOOK resumes |
| Split train, one part gone | `pytest tests/test_lifecycle.py -k split_train` | 2 passed: no part starts, every part SOLD_OUT (simulated supplier only — `QUOTES=static` means PKP is not re-quoted live) |

Command for the variants (vault values are fake):

```bash
cd backend && AGENT_VAULT_JSON='{"passenger_1_first_name":"Ola","passenger_1_last_name":"Nowak","email":"demo@tripsplit.app","passengers":"1"}' \
  uv run agent-run --url "http://localhost:8840/api/demo-supplier/rail-variants/captcha?from=Warszawa+Centralna&to=Praha+hl.n.&date=2026-11-20" \
  --goal "Find and book EC 111 Warszawa Centralna -> Praha hl.n. on 2026-11-20 for 1 passenger. Stop at the final summary, before paying." --run-id demo-captcha
```

**Fallback:** harness `missing_payment`, `captcha_handoff`, `price_jump`, `card_amount_mismatch` (all PASS).

## 6. Attractions → day plan → the agent buys museum tickets

**Say:** "While the group pays, everyone votes on what to see. The plan is built around the
trains and opening hours, and the agent buys the tickets."

**Clicks:** room → Things to do there → vote → Generate plan; pay; approve basket.

**Numbers** (trip `6ae5b1a92a417b26ce50f3f6`, Splurge, 4 people): 12 attractions; plan in
**0.05 s**: Fri Charles Bridge 18:45 after the 07:52–17:52 train; Sat Jewish Museum 10:00,
Prague Castle 13:30; Sun National Museum 10:00 before the 14:08 train. Tickets added 820 PLN to
the total (re-split +205.00 each). Agent bought 3 ticket orders on the demo shop (`SIM-B726BE`,
`SIM-D7D447`, `SIM-A8AEC6`; 360 + 180 + 280 PLN; 0 LLM calls, 5 steps each) and the PKP
**return** as ONE order (`SIM-BA5BCD`, 1 693.00 PLN for 4).

**Real vs simulated:** attractions and tickets are simulated (`sim_tickets`/`sim_sights` with real
coordinates and hours); the plan is deterministic code; PKP fare live.

**Honest notes:** this trip did not reach BOOKED — see bugs 4 and 5 (the "Vltava cruise" from
`sim_activity` cannot be bought by the agent, and the LiteAPI stay failed on a price flip).
Pick the **Budget** package for this case, or drop `sim_activity` from `SUPPLIERS`.

**Fallback:** `uv run trip-harness run attraction_tickets --live-agent`.

---

## Bugs found

| # | Bug | Status |
|---|---|---|
| 1 | Disruption with a price change: the replacement train kept the search-time `fare=` in its purchase URL, the demo site showed the old total and the agent **handed off every rebooking** (the director uses +8 %) | **fixed** 6957f85 (`priced_purchase_url`, tests) |
| 2 | "6/6 paid" read "4 442.00 PLN of 4 442.32 PLN" (count-up rounded the final value) | **fixed** 8df9d73 (+ test) |
| 3 | Seeded friends had no document details → a flight trip never auto-booked the Duffel flight | **fixed** 25999ca (+ test) |
| 3b | `seed-demo` left the demo account without traveller details → AUTO_BOOK skipped the train parts with the organizer | **fixed** 68bea73 (+ test) |
| 4 | `sim_activity` is an AGENT supplier at `https://sim.tripsplit.invalid` → every Comfort/Splurge activity fails in the real app | reported (env/sim) |
| 5 | LiteAPI sandbox flips between two prices; the purchase refuses any difference, even a lower one (`suppliers/liteapi.py:767`) | reported (liteapi) |
| 6 | Quick brief + "I'll pay for everyone" before anybody joined collapses the trip to one traveller | reported (product call) |
| 7 | Duffel instant orders (HOLDS=off) never store the order id → airline-initiated changes are never checked | reported (duffel) |
| 8 | `Vault.mask` masks the 2-letter nationality "PL", so run reasons read "466.95 •••N" | reported (agent-runtime) |
| 9 | A cheaper rebooking goes straight to REBOOKING but nothing auto-starts the replacements (AUTO_BOOK fires only on a last payment) — click Book everything | noted |
| 10 | Approval card for a 3-person part says "For 6 people" | noted (UI) |

## Gates (this branch)

`ruff check`, `ruff format --check`, `mypy`, `lint-imports` (7 contracts kept), `pytest`,
`trip-harness run all` (all PASS, live ones pending without flags; `barcelona_duffel_live
--live-flights` PASS 34.6 s, `prague_liteapi_live --live-stays` PASS 43.0 s), `pnpm verify`
(146 tests) — exit code 0.
