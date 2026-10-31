# PKP Intercity (intercity.pl / bilet.intercity.pl) — DRAFT playbook

Draft from the site's known structure, not yet verified by a live recon run. Keep only the
stable shape here; refine with browser-harness before trusting it in a demo.

- Consent: a cookie dialog appears on first visit. Accept all ("Akceptuję" / "Zaakceptuj
  wszystkie" / "Accept all"). The site may also offer a language switch — Polish is fine.
- Search form (milestone `search`): "Skąd" (from) and "Dokąd" (to) are autocomplete inputs —
  type the station name, then click the matching suggestion (e.g. "Warszawa Centralna",
  "Praha hl.n."); typing alone does not select a station. Date and time pickers: prefer
  typing into the field if it accepts text, otherwise pick the day tile. Passengers: open the
  passenger panel and set the number of "Normalny" (full-fare) adults to the group size; do
  not add discounts unless the goal names them. Then "Wyszukaj" / "Szukaj połączenia".
- Connection list (milestone `results`): rows with departure/arrival time, duration, number
  of changes, train category (EIC / EC / IC / TLK) and the price. Pick the connection inside
  the requested time window with the fewest changes. International trains to Praha are EC.
  Click the row's "Kup bilet" / "Wybierz" button.
- Class and seats: choose 2nd class ("Klasa 2") unless told otherwise. Seat preferences
  (window/aisle, compartment) are optional — keep the defaults. Skip upsells (insurance,
  "Bilet+" extras, meals).
- Passenger data (milestone `passengers`): first and last name per traveller and the buyer's
  email (often entered twice — "E-mail" and "Powtórz e-mail"). Use the vault keys
  `passenger_N_first_name`, `passenger_N_last_name`, `email`. Tick only the REQUIRED terms
  checkboxes (regulamin); leave marketing consents unticked.
- Account: if "Kup bez logowania" / guest purchase is offered, take it. If a login is
  REQUIRED and the profile is not logged in, call handoff (log in once with `agent-login`).
- Summary (milestone `review`): route, date/time, class, passenger count and total price.
  Verify against the goal; this is where stop_before_pay ends — call done, do NOT press
  "Kupuję i płacę" / "Przejdź do płatności".
- HANDOFF on: CAPTCHA, an SMS/BLIK code, a payment-operator iframe (Przelewy24, PayU, card
  form), or a login wall.
