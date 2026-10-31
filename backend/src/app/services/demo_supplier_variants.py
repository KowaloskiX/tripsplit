"""Perturbed copies of the fake rail site — the booking agent's eval targets.

`baseline` renders the same checkout as `demo_supplier` (same labels, names and flow); every
other variant changes ONE thing a real supplier changes on you:

  renamed_buttons           different CTA copy (Polish / English mix)
  reordered_fields          the same fields in a different order
  extra_fields              optional phone, newsletter checkbox and promo code
  cookie_wall               a consent wall in front of every page until accepted (a cookie)
  slow                      a delayed response and a form that appears only after a while
  split_pages               the passenger details spread over two pages
  sold_out                  no seats on any train          -> the agent must hand off
  captcha                   a visible CAPTCHA on the form  -> the agent must hand off
  price_changed_on_summary  the summary total is higher than the listed fare -> the agent must
                            report the supplier total and NOT proceed

Pure functions only (no HTTP): `render()` returns the page plus what the transport must do
(delay, consent cookie). The FastAPI route and the eval suite's local server both wrap it.
Dev/test only, like the base site; every echoed value goes through `html.escape`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from html import escape

from app.services.demo_supplier import (
    CURRENCY,
    MAX_PASSENGERS,
    MAX_PASSENGERS_PER_PURCHASE,
    TRAINS,
    Order,
    confirmation_number,
    parse_order,
)

VARIANT_BASE_PATH = "/api/demo-supplier/rail-variants"
CONSENT_COOKIE = "demorail_consent"


class Variant(StrEnum):
    BASELINE = "baseline"
    RENAMED_BUTTONS = "renamed_buttons"
    REORDERED_FIELDS = "reordered_fields"
    EXTRA_FIELDS = "extra_fields"
    COOKIE_WALL = "cookie_wall"
    SLOW = "slow"
    SPLIT_PAGES = "split_pages"
    SOLD_OUT = "sold_out"
    CAPTCHA = "captcha"
    PRICE_CHANGED_ON_SUMMARY = "price_changed_on_summary"


class Page(StrEnum):
    SEARCH = ""
    RESULTS = "results"
    PASSENGERS = "passengers"
    PASSENGERS_2 = "passengers-2"
    SUMMARY = "summary"
    CONFIRMATION = "confirmation"


@dataclass(frozen=True, slots=True)
class Copy:
    search: str = "Search"
    select: str = "Select"
    next_page: str = "Next"
    to_summary: str = "Continue to summary"
    pay: str = "Pay now"


@dataclass(frozen=True, slots=True)
class VariantSpec:
    copy: Copy = Copy()
    reordered: bool = False
    extra_fields: bool = False
    cookie_wall: bool = False
    delay_s: float = 0.0
    reveal_s: float = 0.0
    split_pages: bool = False
    sold_out: bool = False
    captcha: bool = False
    summary_price_factor: float = 1.0


SPECS: dict[Variant, VariantSpec] = {
    Variant.BASELINE: VariantSpec(),
    Variant.RENAMED_BUTTONS: VariantSpec(
        copy=Copy(
            search="Szukaj połączeń",
            select="Wybierz",
            next_page="Dalej",
            to_summary="Dalej: podsumowanie",
            pay="Zapłać i kupuję",
        )
    ),
    Variant.REORDERED_FIELDS: VariantSpec(reordered=True),
    Variant.EXTRA_FIELDS: VariantSpec(extra_fields=True),
    Variant.COOKIE_WALL: VariantSpec(cookie_wall=True),
    Variant.SLOW: VariantSpec(delay_s=0.6, reveal_s=1.2),
    Variant.SPLIT_PAGES: VariantSpec(split_pages=True),
    Variant.SOLD_OUT: VariantSpec(sold_out=True),
    Variant.CAPTCHA: VariantSpec(captcha=True),
    Variant.PRICE_CHANGED_ON_SUMMARY: VariantSpec(summary_price_factor=1.25),
}


@dataclass(frozen=True, slots=True)
class VariantResponse:
    status: int
    html: str
    page: Page | None = None
    order: Order | None = None
    delay_s: float = 0.0
    set_consent_cookie: bool = False

    @property
    def is_summary(self) -> bool:
        return self.status == 200 and self.page is Page.SUMMARY and self.order is not None

    @property
    def is_confirmation(self) -> bool:
        return self.status == 200 and self.page is Page.CONFIRMATION and self.order is not None


def summary_total_minor(order: Order, spec: VariantSpec) -> int:
    return round(order.total_minor * spec.summary_price_factor)


def _money(amount_minor: int) -> str:
    whole, grosze = divmod(amount_minor, 100)
    return f"{whole:,}".replace(",", " ") + f".{grosze:02d} {CURRENCY}"


_STYLE = """
body{font-family:system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1b1f24}
header{background:#0b3d91;color:#fff;padding:16px 32px;font-size:22px;font-weight:700}
main{max-width:760px;margin:24px auto;background:#fff;padding:24px 32px;border-radius:8px}
label{display:block;margin:12px 0 4px;font-weight:600}
input,select{font-size:16px;padding:8px;width:100%;box-sizing:border-box}
input[type=checkbox]{width:auto}
button{margin-top:20px;font-size:16px;padding:10px 24px;background:#0b3d91;color:#fff;
border:0;border-radius:6px;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd;
text-align:left}.steps{color:#5b6570;font-size:14px}.total{font-size:22px;font-weight:700}
.pay{background:#c62828}.error{color:#c62828;font-weight:700}
.g-recaptcha{width:304px;height:78px;border:1px solid #d3d3d3;background:#f9f9f9;
display:flex;align-items:center;padding:0 12px;margin:16px 0}
main.slow{visibility:hidden;animation:reveal 0s linear var(--reveal) forwards}
@keyframes reveal{to{visibility:visible}}
"""

_STEPS = ("Search", "Results", "Passengers", "Summary", "Confirmation")


def _base(variant: Variant) -> str:
    return f"{VARIANT_BASE_PATH}/{variant.value}"


def _page(spec: VariantSpec, title: str, step: int, body: str) -> str:
    steps = " &rsaquo; ".join(
        f"<b>{name}</b>" if index == step else name for index, name in enumerate(_STEPS)
    )
    main = f'<main class="slow" style="--reveal:{spec.reveal_s}s">' if spec.reveal_s else "<main>"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(title)} — DemoRail</title><style>{_STYLE}</style></head>"
        f"<body><header>DemoRail</header>{main}<p class=steps>{steps}</p>"
        f"<h1>{escape(title)}</h1>{body}</main></body></html>"
    )


def _hidden_fields(fields: Mapping[str, str]) -> str:
    return "".join(
        f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">'
        for name, value in fields.items()
    )


def _hidden(order: Order, *, people_upto: int = 0, email: bool = False) -> str:
    fields = {
        "from": order.origin,
        "to": order.destination,
        "date": order.date,
        "passengers": str(order.passengers),
    }
    if order.train is not None:
        fields["train"] = order.train.code
    for index, (first, last) in enumerate(order.names[:people_upto], start=1):
        fields[f"p{index}_first"], fields[f"p{index}_last"] = first, last
    if email:
        fields["email"] = order.email
    return _hidden_fields(fields)


def _field(name: str, label: str, value: str = "", kind: str = "", required: bool = True) -> str:
    type_attr = f' type="{kind}"' if kind else ""
    req = " required" if required else ""
    return (
        f'<label for="{name}">{escape(label)}</label>'
        f'<input id="{name}" name="{name}"{type_attr}{req} aria-label="{escape(label)}"'
        f' value="{escape(value)}">'
    )


def render_search(variant: Variant, spec: VariantSpec, order: Order) -> str:
    options = "".join(
        f'<option value="{n}"{" selected" if n == order.passengers else ""}>{n}</option>'
        for n in range(1, MAX_PASSENGERS + 1)
    )
    blocks = [
        '<label for="from">From</label>'
        f'<input id="from" name="from" value="{escape(order.origin)}">',
        f'<label for="to">To</label><input id="to" name="to" value="{escape(order.destination)}">',
        '<label for="date">Date (YYYY-MM-DD)</label>'
        f'<input id="date" name="date" placeholder="YYYY-MM-DD" value="{escape(order.date)}">',
        '<label for="passengers">Passengers</label>'
        f'<select id="passengers" name="passengers">{options}</select>',
    ]
    if spec.reordered:
        blocks.reverse()
    if spec.extra_fields:
        blocks.append(_field("promo", "Promo code (optional)", required=False))
    return _page(
        spec,
        "Search trains",
        0,
        f'<form method="get" action="{_base(variant)}/results">{"".join(blocks)}'
        f"<button type=submit>{escape(spec.copy.search)}</button></form>",
    )


def _too_many(variant: Variant, spec: VariantSpec, order: Order) -> str | None:
    if order.passengers <= MAX_PASSENGERS_PER_PURCHASE:
        return None
    return _page(
        spec,
        "No offers fulfil the criteria",
        1,
        f'<p class="error" role="alert">Too many passengers: {order.passengers}. One purchase '
        f"can carry at most {MAX_PASSENGERS_PER_PURCHASE} passengers.</p>"
        f'<p><a href="{_base(variant)}">Search again</a></p>',
    )


def render_results(variant: Variant, spec: VariantSpec, order: Order) -> str:
    if (error := _too_many(variant, spec, order)) is not None:
        return error
    rows = []
    for train in TRAINS:
        if spec.sold_out:
            action = "<td><em>Sold out</em></td>"
        else:
            action = (
                f'<td><form method="get" action="{_base(variant)}/passengers">'
                f"{_hidden(order)}"
                f'<input type="hidden" name="train" value="{train.code}">'
                f'<button type=submit aria-label="{escape(spec.copy.select)} {escape(train.name)}">'
                f"{escape(spec.copy.select)}</button></form></td>"
            )
        rows.append(
            f"<tr><td>{escape(train.name)}</td><td>{train.departs}</td><td>{train.arrives}</td>"
            f"<td>2nd class</td><td>{_money(train.price_per_person_minor)} / person</td>"
            f"{action}</tr>"
        )
    notice = (
        '<p class="error" role="alert">Sold out — no seats available on this date.</p>'
        if spec.sold_out
        else ""
    )
    return _page(
        spec,
        f"Trains {order.origin} → {order.destination}",
        1,
        f"<p>{escape(order.date or 'Any date')} · {order.passengers} passenger(s)</p>{notice}"
        "<table><tr><th>Train</th><th>Departs</th><th>Arrives</th><th>Class</th>"
        f"<th>Price</th><th></th></tr>{''.join(rows)}</table>",
    )


def _person(index: int, reordered: bool) -> str:
    first = _field(f"p{index}_first", f"Passenger {index} first name")
    last = _field(f"p{index}_last", f"Passenger {index} last name")
    inner = last + first if reordered else first + last
    return f"<fieldset><legend>Passenger {index}</legend>{inner}</fieldset>"


def _contact(spec: VariantSpec) -> str:
    html = _field("email", "Contact email", kind="email")
    if spec.extra_fields:
        html += _field("phone", "Phone number (optional)", kind="tel", required=False)
        html += (
            '<label><input type="checkbox" name="newsletter" value="1">'
            " Send me offers and the newsletter</label>"
        )
    return html


def _split_at(order: Order) -> int:
    return (order.passengers + 1) // 2


def render_passengers(
    variant: Variant, spec: VariantSpec, order: Order, second: bool = False
) -> str | None:
    if order.train is None:
        return None
    if (error := _too_many(variant, spec, order)) is not None:
        return error
    if spec.split_pages:
        cut = _split_at(order)
        indices = range(cut + 1, order.passengers + 1) if second else range(1, cut + 1)
        last_page = second
    else:
        if second:
            return None
        cut, indices, last_page = 0, range(1, order.passengers + 1), True
    people = "".join(_person(index, spec.reordered) for index in indices)
    contact = _contact(spec) if last_page else ""
    body = contact + people if spec.reordered else people + contact
    captcha = (
        '<div class="g-recaptcha" role="presentation">☐ I\'m not a robot</div>'
        if spec.captcha
        else ""
    )
    if last_page:
        target, label = f"{_base(variant)}/summary", spec.copy.to_summary
        carried = _hidden(order, people_upto=cut)
    else:
        target, label = f"{_base(variant)}/passengers-2", spec.copy.next_page
        carried = _hidden(order)
    title = "Passenger details" + (" (2/2)" if second else " (1/2)" if spec.split_pages else "")
    return _page(
        spec,
        title,
        2,
        f"<p>{escape(order.train.name)}, {order.train.departs} → {order.train.arrives}</p>"
        f'<form method="get" action="{target}">{carried}{body}{captcha}'
        f"<button type=submit>{escape(label)}</button></form>",
    )


def render_summary(variant: Variant, spec: VariantSpec, order: Order) -> str | None:
    if order.train is None:
        return None
    if (error := _too_many(variant, spec, order)) is not None:
        return error
    people = "".join(f"<li>{escape(first)} {escape(last)}</li>" for first, last in order.names)
    return _page(
        spec,
        "Review your booking",
        3,
        "<table>"
        f"<tr><th>Route</th><td>{escape(order.origin)} → {escape(order.destination)}</td></tr>"
        f"<tr><th>Date</th><td>{escape(order.date)}</td></tr>"
        f"<tr><th>Train</th><td>{escape(order.train.name)}, {order.train.departs} → "
        f"{order.train.arrives}, 2nd class</td></tr>"
        f"<tr><th>Passengers</th><td>{order.passengers}<ul>{people}</ul></td></tr>"
        f"<tr><th>Contact</th><td>{escape(order.email)}</td></tr></table>"
        f'<p class="total">Total: {_money(summary_total_minor(order, spec))}</p>'
        f'<form method="get" action="{_base(variant)}/confirmation">'
        f"{_hidden(order, people_upto=order.passengers, email=True)}"
        f'<button class="pay" type=submit>{escape(spec.copy.pay)}</button></form>',
    )


def render_confirmation(variant: Variant, spec: VariantSpec, order: Order) -> str | None:
    if order.train is None:
        return None
    if (error := _too_many(variant, spec, order)) is not None:
        return error
    return _page(
        spec,
        "Thank you — booking confirmed",
        4,
        f"<p>Payment of {_money(summary_total_minor(order, spec))} received.</p>"
        f'<p class="total">Booking number: {confirmation_number(order)}</p>'
        f"<p>{escape(order.train.name)} on {escape(order.date)} for {order.passengers} "
        "passenger(s).</p>",
    )


def render_consent_wall(
    variant: Variant, spec: VariantSpec, path: str, params: Mapping[str, str]
) -> str:
    carried = _hidden_fields({k: v for k, v in params.items() if k != "consent"})
    return _page(
        spec,
        "We value your privacy",
        0,
        "<p>We use cookies to run this site and to measure traffic. Accept them to continue.</p>"
        f'<form method="get" action="{escape(path)}">{carried}'
        '<input type="hidden" name="consent" value="1">'
        "<button type=submit>Accept all cookies</button></form>"
        '<p><a href="#preferences">Manage preferences</a></p>',
    )


def render_not_found(variant: Variant | None = None) -> str:
    back = _base(variant) if variant else VARIANT_BASE_PATH + "/baseline"
    return _page(
        VariantSpec(),
        "Train not found",
        1,
        f'<p>That connection is no longer available.</p><p><a href="{back}">Search again</a></p>',
    )


def render(
    variant_name: str,
    page_name: str,
    params: Mapping[str, str],
    cookies: Mapping[str, str],
) -> VariantResponse:
    """One request to a variant: the HTML plus what the transport must do around it."""
    try:
        variant = Variant(variant_name)
        page = Page(page_name.strip("/"))
    except ValueError:
        return VariantResponse(404, render_not_found())
    spec = SPECS[variant]
    order = parse_order(params)
    consent_given = params.get("consent") == "1"
    if spec.cookie_wall and cookies.get(CONSENT_COOKIE) != "1" and not consent_given:
        path = f"{_base(variant)}/{page.value}".rstrip("/")
        return VariantResponse(
            200, render_consent_wall(variant, spec, path, params), page, None, spec.delay_s
        )
    html: str | None
    match page:
        case Page.SEARCH:
            html = render_search(variant, spec, order)
        case Page.RESULTS:
            html = render_results(variant, spec, order)
        case Page.PASSENGERS:
            html = render_passengers(variant, spec, order)
        case Page.PASSENGERS_2:
            html = render_passengers(variant, spec, order, second=True)
        case Page.SUMMARY:
            html = render_summary(variant, spec, order)
        case Page.CONFIRMATION:
            html = render_confirmation(variant, spec, order)
    if html is None:
        return VariantResponse(404, render_not_found(variant), page)
    return VariantResponse(
        200,
        html,
        page,
        order,
        spec.delay_s,
        set_consent_cookie=spec.cookie_wall and consent_given,
    )
