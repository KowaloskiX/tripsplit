"""A deterministic fake rail-booking site — the agent's target for the live demo and for manual
end-to-end tests. It never blocks, never changes and never takes money.

search -> results (3 trains) -> passenger details -> summary with "Pay now" -> confirmation

Like PKP Intercity, one purchase carries at most 5 passengers: a bigger party gets a clear
error on every page past the search and can never reach "Pay now" — the backend buys a train
for six as two purchases of three.

Plain HTML forms with GET only: state travels in the query string, so there is no session, no
JavaScript and no CSRF token to fight (the API's CSRF guard covers mutating methods only).
Every echoed value goes through `html.escape`.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape

from app.core.domain.bookings import PKP_INTERCITY_PURCHASE_CAP

BASE_PATH = "/api/demo-supplier/rail"
# What the search form offers; a purchase itself is capped at MAX_PASSENGERS_PER_PURCHASE.
MAX_PASSENGERS = 9
MAX_PASSENGERS_PER_PURCHASE = PKP_INTERCITY_PURCHASE_CAP
_FIELD_MAX = 100
CURRENCY = "PLN"


@dataclass(frozen=True, slots=True)
class Train:
    code: str
    name: str
    departs: str
    arrives: str
    price_per_person_minor: int


TRAINS: tuple[Train, ...] = (
    Train("EC-111", "EC 111 Praha", "06:20", "14:05", 18_900),
    Train("EC-113", "EC 113 Vltava", "10:25", "18:10", 21_900),
    Train("EN-407", "EN 407 Chopin", "22:40", "07:05", 24_900),
)


@dataclass(frozen=True, slots=True)
class Order:
    origin: str
    destination: str
    date: str
    passengers: int
    train: Train | None
    names: tuple[tuple[str, str], ...]
    email: str

    @property
    def total_minor(self) -> int:
        return self.passengers * self.train.price_per_person_minor if self.train else 0


def _clean(value: str | None) -> str:
    return (value or "").strip()[:_FIELD_MAX]


def parse_order(params: Mapping[str, str]) -> Order:
    try:
        passengers = int(params.get("passengers") or 1)
    except ValueError:
        passengers = 1
    passengers = min(max(passengers, 1), MAX_PASSENGERS)
    code = params.get("train")
    return Order(
        origin=_clean(params.get("from")) or "Warszawa Centralna",
        destination=_clean(params.get("to")) or "Praha hl.n.",
        date=_clean(params.get("date")),
        passengers=passengers,
        train=next((train for train in TRAINS if train.code == code), None),
        names=tuple(
            (_clean(params.get(f"p{index}_first")), _clean(params.get(f"p{index}_last")))
            for index in range(1, passengers + 1)
        ),
        email=_clean(params.get("email")),
    )


def _money(amount_minor: int) -> str:
    whole, grosze = divmod(amount_minor, 100)
    return f"{whole:,}".replace(",", " ") + f".{grosze:02d} {CURRENCY}"


def _hidden(order: Order, *, with_people: bool) -> str:
    fields = {
        "from": order.origin,
        "to": order.destination,
        "date": order.date,
        "passengers": str(order.passengers),
    }
    if order.train is not None:
        fields["train"] = order.train.code
    if with_people:
        for index, (first, last) in enumerate(order.names, start=1):
            fields[f"p{index}_first"], fields[f"p{index}_last"] = first, last
        fields["email"] = order.email
    return "".join(
        f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'
        for name, value in fields.items()
    )


_STYLE = """
body{font-family:system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1b1f24}
header{background:#0b3d91;color:#fff;padding:16px 32px;font-size:22px;font-weight:700}
main{max-width:760px;margin:24px auto;background:#fff;padding:24px 32px;border-radius:8px}
label{display:block;margin:12px 0 4px;font-weight:600}
input,select{font-size:16px;padding:8px;width:100%;box-sizing:border-box}
button{margin-top:20px;font-size:16px;padding:10px 24px;background:#0b3d91;color:#fff;
border:0;border-radius:6px;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd;
text-align:left}.steps{color:#5b6570;font-size:14px}.total{font-size:22px;font-weight:700}
.pay{background:#c62828}.error{color:#c62828;font-weight:700}
"""

_STEPS = ("Search", "Results", "Passengers", "Summary", "Confirmation")


def _page(title: str, step: int, body: str) -> str:
    steps = " &rsaquo; ".join(
        f"<b>{name}</b>" if index == step else name for index, name in enumerate(_STEPS)
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(title)} — DemoRail</title><style>{_STYLE}</style></head>"
        f"<body><header>DemoRail</header><main><p class=steps>{steps}</p>"
        f"<h1>{escape(title)}</h1>{body}</main></body></html>"
    )


def render_search(order: Order) -> str:
    options = "".join(
        f'<option value="{n}"{" selected" if n == order.passengers else ""}>{n}</option>'
        for n in range(1, MAX_PASSENGERS + 1)
    )
    return _page(
        "Search trains",
        0,
        f'<form method="get" action="{BASE_PATH}/results">'
        '<label for="from">From</label>'
        f'<input id="from" name="from" value="{escape(order.origin)}">'
        f'<label for="to">To</label><input id="to" name="to" value="{escape(order.destination)}">'
        f'<label for="date">Date (YYYY-MM-DD)</label>'
        f'<input id="date" name="date" placeholder="YYYY-MM-DD" value="{escape(order.date)}">'
        f'<label for="passengers">Passengers</label>'
        f'<select id="passengers" name="passengers">{options}</select>'
        "<button type=submit>Search</button></form>",
    )


def _too_many(order: Order) -> str | None:
    """The error page for a party one purchase cannot carry; None when it fits."""
    if order.passengers <= MAX_PASSENGERS_PER_PURCHASE:
        return None
    return _page(
        "No offers fulfil the criteria",
        1,
        f'<p class="error" role="alert">Too many passengers: {order.passengers}. One purchase '
        f"can carry at most {MAX_PASSENGERS_PER_PURCHASE} passengers — split the group into "
        "several purchases.</p>"
        f'<p><a href="{BASE_PATH}">Search again</a></p>',
    )


def render_results(order: Order) -> str:
    if (error := _too_many(order)) is not None:
        return error
    rows = "".join(
        f"<tr><td>{escape(train.name)}</td><td>{train.departs}</td><td>{train.arrives}</td>"
        f"<td>2nd class</td><td>{_money(train.price_per_person_minor)} / person</td>"
        f'<td><form method="get" action="{BASE_PATH}/passengers">'
        f"{_hidden(order, with_people=False)}"
        f'<input type="hidden" name="train" value="{train.code}">'
        f'<button type=submit aria-label="Select {escape(train.name)}">Select</button>'
        "</form></td></tr>"
        for train in TRAINS
    )
    return _page(
        f"Trains {order.origin} → {order.destination}",
        1,
        f"<p>{escape(order.date or 'Any date')} · {order.passengers} passenger(s)</p>"
        "<table><tr><th>Train</th><th>Departs</th><th>Arrives</th><th>Class</th>"
        f"<th>Price</th><th></th></tr>{rows}</table>",
    )


def render_passengers(order: Order) -> str | None:
    if order.train is None:
        return None
    if (error := _too_many(order)) is not None:
        return error
    people = "".join(
        f"<fieldset><legend>Passenger {index}</legend>"
        f'<label for="p{index}_first">Passenger {index} first name</label>'
        f'<input id="p{index}_first" name="p{index}_first" required'
        f' aria-label="Passenger {index} first name">'
        f'<label for="p{index}_last">Passenger {index} last name</label>'
        f'<input id="p{index}_last" name="p{index}_last" required'
        f' aria-label="Passenger {index} last name"></fieldset>'
        for index in range(1, order.passengers + 1)
    )
    return _page(
        "Passenger details",
        2,
        f"<p>{escape(order.train.name)}, {order.train.departs} → {order.train.arrives}</p>"
        f'<form method="get" action="{BASE_PATH}/summary">{_hidden(order, with_people=False)}'
        f"{people}"
        '<label for="email">Contact email</label>'
        '<input id="email" name="email" type="email" required aria-label="Contact email">'
        "<button type=submit>Continue to summary</button></form>",
    )


def render_summary(order: Order) -> str | None:
    if order.train is None:
        return None
    if (error := _too_many(order)) is not None:
        return error
    people = "".join(f"<li>{escape(first)} {escape(last)}</li>" for first, last in order.names)
    return _page(
        "Review your booking",
        3,
        "<table>"
        f"<tr><th>Route</th><td>{escape(order.origin)} → {escape(order.destination)}</td></tr>"
        f"<tr><th>Date</th><td>{escape(order.date)}</td></tr>"
        f"<tr><th>Train</th><td>{escape(order.train.name)}, {order.train.departs} → "
        f"{order.train.arrives}, 2nd class</td></tr>"
        f"<tr><th>Passengers</th><td>{order.passengers}<ul>{people}</ul></td></tr>"
        f"<tr><th>Contact</th><td>{escape(order.email)}</td></tr></table>"
        f'<p class="total">Total: {_money(order.total_minor)}</p>'
        f'<form method="get" action="{BASE_PATH}/confirmation">'
        f"{_hidden(order, with_people=True)}"
        '<button class="pay" type=submit>Pay now</button></form>',
    )


def confirmation_number(order: Order) -> str:
    seed = "|".join(
        [order.origin, order.destination, order.date, str(order.passengers), order.email]
        + [order.train.code if order.train else ""]
        + [f"{first} {last}" for first, last in order.names]
    )
    return "DR-" + hashlib.sha256(seed.encode()).hexdigest()[:8].upper()


def render_confirmation(order: Order) -> str | None:
    if order.train is None:
        return None
    if (error := _too_many(order)) is not None:
        return error
    return _page(
        "Thank you — booking confirmed",
        4,
        f"<p>Payment of {_money(order.total_minor)} received.</p>"
        f'<p class="total">Booking number: {confirmation_number(order)}</p>'
        f"<p>{escape(order.train.name)} on {escape(order.date)} for {order.passengers} "
        "passenger(s). Tickets were sent to the contact email.</p>",
    )


def render_not_found() -> str:
    return _page(
        "Train not found",
        1,
        "<p>That connection is no longer available.</p>"
        f'<p><a href="{BASE_PATH}">Search again</a></p>',
    )
