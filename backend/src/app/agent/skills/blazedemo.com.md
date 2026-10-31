# BlazeDemo (blazedemo.com) — playbook

BlazeMeter's public flight-booking demo, built for test automation. No real money: the
"Purchase Flight" button returns a fake confirmation id. Safe target for end-to-end checks.

## Shape

1. Home: two selects, departure city (`fromPort`) and destination city (`toPort`), then
   "Find Flights". Pick the cities the goal names; there is no date and no party size.
2. Flights table: one row per flight (flight #, airline, departs, arrives, price in USD) with a
   "Choose This Flight" button. Take the cheapest unless the goal names a flight.
3. Purchase page: "Your flight from ... has been reserved", price, fees, "Total Cost", then ONE
   form for the whole party: Name, Address, City, State, Zip Code, Card Type, Credit Card
   Number, Month, Year, Name on Card, "Remember me".
   - Name = the lead passenger: `{{vault.passenger_1_first_name}} {{vault.passenger_1_last_name}}`.
   - Address / City / State / Zip: `{{vault.billing_address}}`, `{{vault.billing_city}}`,
     `{{vault.billing_state}}`, `{{vault.billing_zip}}` when the vault has them.
   - Credit Card Number: `{{vault.card_number}}`; Name on Card: `{{vault.card_holder}}`.
     Month/Year are prefilled — leave them. Leave "Remember me" unticked.
   - Fill everything in ONE `fill_form`, then stop: "Purchase Flight" is the final click and
     is only pressed after a human approves.
4. Confirmation: "Thank you for your purchase today!" with an Id (13 digits), status, amount.

## Notes

- The site sells the party under one name: the passenger count does not appear anywhere.
- The total on the purchase page is static demo data (it does not follow the chosen flight).
