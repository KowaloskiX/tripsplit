"""A deterministic fake attraction-ticket shop — where the booking agent buys the group's
timed-entry tickets in demos and tests. It never blocks, never changes and never takes money.

visit (attraction, date, tickets) -> entry slots -> visitors -> summary with "Pay now" ->
confirmation with a booking number

One order carries at most `MAX_TICKETS_PER_PURCHASE` tickets, like many real shops: a bigger
party gets a clear error and can never reach "Pay now". Plain HTML forms with GET only (state in
the query string: no session, no JavaScript, no CSRF token). Every echoed value goes through
`html.escape`. Real attraction websites are never driven by the agent — only this shop.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from app.suppliers.attraction_catalogue import CITIES, CatalogueAttraction, find_attraction
from app.suppliers.sim_tickets import BASE_PATH, MAX_TICKETS_PER_PURCHASE

MAX_TICKETS = 12  # what the form offers; one order is capped at MAX_TICKETS_PER_PURCHASE
SLOT_MINUTES = 30
LAST_ENTRY_BEFORE_CLOSING = timedelta(minutes=60)
_FIELD_MAX = 100
CURRENCY = "PLN"


@dataclass(frozen=True, slots=True)
class TicketOrder:
    attraction: CatalogueAttraction | None
    date: str
    tickets: int
    slot: str  # "HH:MM", "" before one is picked
    names: tuple[tuple[str, str], ...]
    email: str

    @property
    def total_minor(self) -> int:
        return self.tickets * self.attraction.price_pp_minor if self.attraction else 0


def _clean(value: str | None) -> str:
    return (value or "").strip()[:_FIELD_MAX]


def parse_order(params: Mapping[str, str]) -> TicketOrder:
    try:
        tickets = int(params.get("tickets") or 1)
    except ValueError:
        tickets = 1
    tickets = min(max(tickets, 1), MAX_TICKETS)
    return TicketOrder(
        attraction=find_attraction(_clean(params.get("attraction"))),
        date=_clean(params.get("date")),
        tickets=tickets,
        slot=_clean(params.get("slot")),
        names=tuple(
            (_clean(params.get(f"p{index}_first")), _clean(params.get(f"p{index}_last")))
            for index in range(1, tickets + 1)
        ),
        email=_clean(params.get("email")),
    )


def entry_slots(attraction: CatalogueAttraction) -> list[str]:
    """Half-hourly entries from opening until an hour before closing."""
    opens = datetime.strptime(attraction.opens, "%H:%M")
    last = datetime.strptime(attraction.closes, "%H:%M") - LAST_ENTRY_BEFORE_CLOSING
    slots, moment = [], opens
    while moment <= last:
        slots.append(f"{moment:%H:%M}")
        moment += timedelta(minutes=SLOT_MINUTES)
    return slots


def _left(attraction: CatalogueAttraction, slot: str) -> int:
    """Deterministic "tickets left" per slot — always enough for a group of twelve."""
    seed = hashlib.sha256(f"{attraction.code}|{slot}".encode()).digest()[0]
    return 14 + seed % 40


def _money(amount_minor: int) -> str:
    whole, grosze = divmod(amount_minor, 100)
    return f"{whole:,}".replace(",", " ") + f".{grosze:02d} {CURRENCY}"


def _hidden(order: TicketOrder, *, with_slot: bool, with_people: bool) -> str:
    fields = {"date": order.date, "tickets": str(order.tickets)}
    if order.attraction is not None:
        fields["attraction"] = order.attraction.code
    if with_slot:
        fields["slot"] = order.slot
    if with_people:
        for index, (first, last) in enumerate(order.names, start=1):
            fields[f"p{index}_first"], fields[f"p{index}_last"] = first, last
        fields["email"] = order.email
    return "".join(
        f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'
        for name, value in fields.items()
    )


_STYLE = """
body{font-family:system-ui,sans-serif;margin:0;background:#fbf7f2;color:#2a2320}
header{background:#7a2e1d;color:#fff;padding:16px 32px;font-size:22px;font-weight:700}
main{max-width:760px;margin:24px auto;background:#fff;padding:24px 32px;border-radius:10px}
label{display:block;margin:12px 0 4px;font-weight:600}
input,select{font-size:16px;padding:8px;width:100%;box-sizing:border-box}
button{margin-top:20px;font-size:16px;padding:10px 24px;background:#7a2e1d;color:#fff;
border:0;border-radius:6px;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #e5dcd2;
text-align:left}.steps{color:#7b6d64;font-size:14px}.total{font-size:22px;font-weight:700}
.pay{background:#1f6f43}.error{color:#b3261e;font-weight:700}
"""

_STEPS = ("Visit", "Entry time", "Visitors", "Summary", "Confirmation")


def _page(title: str, step: int, body: str) -> str:
    steps = " &rsaquo; ".join(
        f"<b>{name}</b>" if index == step else name for index, name in enumerate(_STEPS)
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(title)} — CityPass Tickets</title><style>{_STYLE}</style></head>"
        f"<body><header>CityPass Tickets</header><main><p class=steps>{steps}</p>"
        f"<h1>{escape(title)}</h1>{body}</main></body></html>"
    )


def render_search(order: TicketOrder) -> str:
    chosen = order.attraction.code if order.attraction else ""
    attractions = "".join(
        f'<option value="{a.code}"{" selected" if a.code == chosen else ""}>'
        f"{escape(a.title)} ({escape(city.name)})</option>"
        for city in CITIES
        for a in city.attractions
        if a.ticketed
    )
    counts = "".join(
        f'<option value="{n}"{" selected" if n == order.tickets else ""}>{n}</option>'
        for n in range(1, MAX_TICKETS + 1)
    )
    return _page(
        "Plan your visit",
        0,
        f'<form method="get" action="{BASE_PATH}/slots">'
        '<label for="attraction">Attraction</label>'
        f'<select id="attraction" name="attraction">{attractions}</select>'
        '<label for="date">Visit date (YYYY-MM-DD)</label>'
        f'<input id="date" name="date" placeholder="YYYY-MM-DD" value="{escape(order.date)}">'
        '<label for="tickets">Number of tickets (persons)</label>'
        f'<select id="tickets" name="tickets">{counts}</select>'
        "<button type=submit>Find time slots</button></form>",
    )


def _too_many(order: TicketOrder) -> str | None:
    if order.tickets <= MAX_TICKETS_PER_PURCHASE:
        return None
    return _page(
        "Order not possible",
        1,
        f'<p class="error" role="alert">Too many tickets: {order.tickets}. One order can '
        f"carry at most {MAX_TICKETS_PER_PURCHASE} tickets — split the group into several "
        f'orders.</p><p><a href="{BASE_PATH}">Start again</a></p>',
    )


def render_slots(order: TicketOrder) -> str | None:
    attraction = order.attraction
    if attraction is None:
        return None
    if (error := _too_many(order)) is not None:
        return error
    rows = "".join(
        f"<tr><td>{slot}</td><td>{_left(attraction, slot)} tickets left</td>"
        f"<td>{_money(attraction.price_pp_minor)} / person</td>"
        f'<td><form method="get" action="{BASE_PATH}/visitors">'
        f"{_hidden(order, with_slot=False, with_people=False)}"
        f'<input type="hidden" name="slot" value="{slot}">'
        f'<button type=submit aria-label="Select {slot}">Select</button></form></td></tr>'
        for slot in entry_slots(attraction)
    )
    return _page(
        f"{attraction.title}: entry times",
        1,
        f"<p>{escape(order.date or 'Any date')} · {order.tickets} ticket(s)</p>"
        "<table><tr><th>Entry</th><th>Availability</th><th>Price</th><th></th></tr>"
        f"{rows}</table>",
    )


def render_visitors(order: TicketOrder) -> str | None:
    attraction = order.attraction
    if attraction is None or order.slot not in entry_slots(attraction):
        return None
    if (error := _too_many(order)) is not None:
        return error
    people = "".join(
        f"<fieldset><legend>Guest {index}</legend>"
        f'<label for="p{index}_first">Guest {index} first name</label>'
        f'<input id="p{index}_first" name="p{index}_first" required'
        f' aria-label="Guest {index} first name">'
        f'<label for="p{index}_last">Guest {index} last name</label>'
        f'<input id="p{index}_last" name="p{index}_last" required'
        f' aria-label="Guest {index} last name"></fieldset>'
        for index in range(1, order.tickets + 1)
    )
    return _page(
        "Who is visiting?",
        2,
        f"<p>{escape(attraction.title)}, {escape(order.date)}, entry {escape(order.slot)}</p>"
        f'<form method="get" action="{BASE_PATH}/summary">'
        f"{_hidden(order, with_slot=True, with_people=False)}{people}"
        '<label for="email">Contact email</label>'
        '<input id="email" name="email" type="email" required aria-label="Contact email">'
        "<button type=submit>Continue to summary</button></form>",
    )


def render_summary(order: TicketOrder) -> str | None:
    attraction = order.attraction
    if attraction is None or order.slot not in entry_slots(attraction):
        return None
    if (error := _too_many(order)) is not None:
        return error
    people = "".join(f"<li>{escape(first)} {escape(last)}</li>" for first, last in order.names)
    return _page(
        "Review your order",
        3,
        "<table>"
        f"<tr><th>Attraction</th><td>{escape(attraction.title)}</td></tr>"
        f"<tr><th>Date</th><td>{escape(order.date)}</td></tr>"
        f"<tr><th>Entry time</th><td>{escape(order.slot)}</td></tr>"
        f"<tr><th>Ticket holders (travellers)</th><td>{order.tickets}<ul>{people}</ul></td></tr>"
        f"<tr><th>Contact</th><td>{escape(order.email)}</td></tr></table>"
        f'<p class="total">Total: {_money(order.total_minor)}</p>'
        f'<form method="get" action="{BASE_PATH}/confirmation">'
        f"{_hidden(order, with_slot=True, with_people=True)}"
        '<button class="pay" type=submit>Pay now</button></form>',
    )


def confirmation_number(order: TicketOrder) -> str:
    seed = "|".join(
        [order.attraction.code if order.attraction else "", order.date, order.slot]
        + [str(order.tickets), order.email]
        + [f"{first} {last}" for first, last in order.names]
    )
    return "TK-" + hashlib.sha256(seed.encode()).hexdigest()[:8].upper()


def render_confirmation(order: TicketOrder) -> str | None:
    attraction = order.attraction
    if attraction is None or order.slot not in entry_slots(attraction):
        return None
    if (error := _too_many(order)) is not None:
        return error
    return _page(
        "Thank you — order confirmed",
        4,
        f"<p>Payment of {_money(order.total_minor)} received.</p>"
        f'<p class="total">Booking number: {confirmation_number(order)}</p>'
        f"<p>{order.tickets} ticket(s) for {escape(attraction.title)} on {escape(order.date)}, "
        f"entry {escape(order.slot)}. The tickets were sent to the contact email.</p>",
    )


def render_not_found() -> str:
    return _page(
        "Attraction not found",
        1,
        "<p>That attraction or entry time is no longer available.</p>"
        f'<p><a href="{BASE_PATH}">Start again</a></p>',
    )
