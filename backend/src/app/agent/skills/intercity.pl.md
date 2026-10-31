# PKP Intercity (intercity.pl -> ebilet.intercity.pl, e-IC 2.0) — playbook

Verified by a manual recon on 2026-10-31 for an international trip (Warszawa Centralna ->
Praha hl.n.) up to the guest-data step. Steps after that are marked UNVERIFIED.

## Fastest path: skip the search form

The search lands on a deterministic URL. If the goal names stations, a date and a time, `goto`
it directly instead of filling the form (station codes come from
`https://www.intercity.pl/station/get/?q=<name>`, field `h`):

    https://ebilet.intercity.pl/polaczenia-miedzynarodowe?dwyj=YYYY-MM-DD&swyj=<from code>&sprzy=<to code>&time=HH%3AMM&przy=0&sprzez=&ticket100=1010&ticket50=&polbez=0

Warszawa Centralna = 5100065, Praga Gł./Praha hl.n. = 5400014. Domestic trips use a sibling path
(`/polaczenia` — UNVERIFIED).

The URL always carries ONE adult (`ticket100=1010`). Do not put more passengers into the URL
(`ticket100=1010;1010;1010` lists "3x Passengers" but "1 x Adults", and the summary then crashes
with "Oops! Something went wrong", verified 2026-10-31). For a group, open the header's
"CHANGE" (next to "1x Passenger 1 x Adults"), raise the adults to the party size, confirm, and
check the header reads "N x Adults" before choosing a connection.

## Search form (only if you must)

- Fields: `#stname-0` "Jadę z", `#stname-1` "Jadę do", `#date_picker` (RRRR-MM-DD, accepts
  text), `#ic-seek-time`. Station inputs are autocomplete: type part of the name, then CLICK the
  suggestion ("Warszawa Centralna", "Praga Gł./Praha hl.n.") — typing alone selects nothing.
- Then "Wyszukaj" (milestone `search`). No cookie banner was shown on this visit.

## Connection list (milestone `results`)

- One card per connection: times, travel time, "Direct", train (e.g. "EC 131 Batory"), price per
  class. Pick the one in the requested window; Warszawa -> Praha direct EC trains run in the
  morning (EC 116 05:28, EC 131 07:52) and midday (EC 112 12:44), plus a night EN.
- Click the card's "BUY A TICKET" / "KUP BILET". The card expands into fare boxes:
  "Non-refundable offer" (Super Promo International, cheapest) and "Flexible offer" (eNRT,
  refundable) per class. Unavailable classes show a grey "Unavailable" button.
- Choose the fare the goal asks for; default to 2nd class. A non-refundable fare opens a
  "Confirmation" modal — press "CONFIRM" (it confirms the fare, it is NOT a payment).

## Seats (milestone `review` is NOT here yet)

- URL `.../wybormiejsc`. "Seat selection preferences" + "Choose a place" (optional — keep the
  automatic assignment), "Additional tickets" (bicycle, dog — leave at 0).
- Press "GO TO PAYMENTS". Despite the label this opens the sign-in step, not a payment.

## Account (milestone `guest_screen` = planned handoff)

- URL `.../podsumowanie` shows a "Sign in" modal: Google / Facebook / Apple / LOG IN / REGISTER
  and a "Continue as Guest" link. The run STOPS here (the site profile hands off as soon as
  "Continue as Guest" is visible): going on means an e-mail address and accepting the e-IC
  regulations on someone's behalf. The steps below are what a person does next.
- Guest goes to `sso.intercity.pl/oauth_server/oauth/register?client_id=eic_guest...` with
  `email`, `email-repeat` and consent toggles. Fill `{{vault.email}}` twice. Tick ONLY the
  mandatory "I declare that I am familiar with the e-IC Regulations..." toggle; leave profiling
  and marketing consents off. Then "SAVE".

## UNVERIFIED after the guest step

- Passenger names (`passenger_N_first_name` / `passenger_N_last_name`), possibly a date of
  birth for international fares, then the summary with the final total. Stop there
  (stop_before_pay) — the final prices are only binding in the summary.
- Payment runs through an external operator (BLIK / PayU / Przelewy24 / card iframe) -> handoff.

## Hard rules learned

- **At most 5 passengers per online international purchase.** A 6-person request returns "No
  offers fulfil the criteria". Split a larger group into several purchases (e.g. 3 + 3) — one
  agent run per purchase.
- **No sales 23:45-00:30** (until 01:00 on the 1st of the month) — the "technological break".
  Do not schedule a run then.
- Listed prices are indicative and cached for up to 5 minutes; the binding price is in the
  summary. Compare it with the expected amount before calling done.
- The site sits behind Akamai bot management. Act at a human pace; on any challenge page or
  CAPTCHA call handoff, never retry in a loop.
- HANDOFF on: CAPTCHA, SMS/BLIK code, a payment-operator iframe, a required login.
