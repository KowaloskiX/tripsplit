# Default booking playbook (any supplier)

- Cookie/consent: a best-effort auto-dismiss runs each step. If a banner still blocks the
  page, click the accept control yourself ("Accept all" / "Akceptuję" / "Zaakceptuj wszystkie")
  — in any language.
- Prefer guest / no-account checkout ("Kup bez konta", "Kup jako gość", "Continue as guest").
  If an account is REQUIRED to continue, call handoff.
- Fill traveller data from the vault. One field per step, a single value per field. If street
  and house number are SEPARATE fields, never put the whole address in one.
- Trains: pick the connection matching the requested departure date and time window; choose
  2nd class unless told otherwise; set the passenger count to the group size; skip seat
  reservation upsells unless they are mandatory.
- Stays: pick the room option matching the requested dates and guest count; prefer free
  cancellation when the price difference is small.
- Verify the summary matches the goal (date, route or dates, passenger/guest count, total)
  BEFORE calling done.
- STOP before the final pay/submit button (this is stop_before_pay). A fully populated,
  ready-to-submit summary is the goal — a human approves it.
- HANDOFF (do not fight) when: a CAPTCHA/bot-check appears; a login is required; a card field
  sits inside a secure payment iframe (Adyen / Stripe / Przelewy24 / PayU) you cannot fill; a
  BLIK code or SMS code is requested.
