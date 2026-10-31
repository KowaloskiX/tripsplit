# DemoRail (local fake supplier at /api/demo-supplier/rail)

A deterministic test site served by our own backend. No cookie banner, no login, no CAPTCHA,
no JavaScript — every step is a plain HTML form submitted with a button.

Checkout shape (a breadcrumb at the top shows the current step):
1. **Search** (milestone `search`): fields From, To, Date (type `YYYY-MM-DD`, e.g.
   2026-11-20) and a native Passengers `<select>`. Set the passenger count to the group size
   with a select action, then click "Search".
2. **Results** (milestone `results`): a table of three trains with departure/arrival times
   and a price per person; each row has its own "Select" button. Pick the train that matches
   the requested time window; with no window, take the earliest departure. For a REBOOKING
   goal, take the next departure later than the delayed train.
3. **Passenger details** (milestone `passengers`): "Passenger N first name" / "Passenger N
   last name" per traveller, then "Contact email". Use `{{vault.passenger_N_first_name}}`,
   `{{vault.passenger_N_last_name}}` and `{{vault.email}}`. Then "Continue to summary".
4. **Review your booking** (milestone `review`): route, date, train, passenger list, contact
   email and the total. Verify it matches the goal. This IS the stop-before-pay page: call
   `done` here and do NOT click "Pay now".
5. **Confirmation** (milestone `done`): "Booking number: DR-XXXXXXXX". Only reached when
   paying is allowed; call `done` with the booking number in the reason.

If a page says "Train not found", start again from the search page.
