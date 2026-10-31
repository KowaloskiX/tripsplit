"""Canned `observe()` states for the rule layer and flows — no browser needed."""

from typing import Any

Element = dict[str, Any]


def el(ref: int, tag: str, role: str, **fields: Any) -> Element:
    base: Element = {
        "ref": ref,
        "tag": tag,
        "type": "",
        "role": role,
        "name": "",
        "id": "",
        "testid": "",
        "text": "",
        "label": "",
        "placeholder": "",
        "href": "",
        "value": "",
        "required": False,
        "checked": False,
        "context": "",
        "options": None,
    }
    base.update(fields)
    return base


def textbox(ref: int, name: str, label: str, **fields: Any) -> Element:
    return el(ref, "input", "textbox", name=name, id=name, label=label, text=label, **fields)


def button(ref: int, text: str, **fields: Any) -> Element:
    return el(ref, "button", "button", type="submit", text=text, **fields)


def state(elements: list[Element], text: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "url": extra.pop("url", "http://127.0.0.1/api/demo-supplier/rail-variants/baseline"),
        "title": "DemoRail",
        "headings": extra.pop("headings", []),
        "text_preview": text[:1200],
        "text": text,
        "rows": extra.pop("rows", []),
        "elements": elements,
        **extra,
    }


def search_page(cta: str = "Search", party_value: str = "1") -> dict[str, Any]:
    return state(
        [
            textbox(1, "from", "From", value="Warszawa Centralna"),
            textbox(2, "to", "To", value="Praha hl.n."),
            textbox(3, "date", "Date (YYYY-MM-DD)", placeholder="YYYY-MM-DD"),
            el(
                4,
                "select",
                "combobox",
                name="passengers",
                id="passengers",
                label="Passengers",
                text=party_value,
                value=party_value,
                options=[str(n) for n in range(1, 10)],
            ),
            button(5, cta),
        ],
        "Search trains From To Date Passengers",
        headings=["Search trains"],
    )


def passengers_page(
    count: int,
    *,
    reordered: bool = False,
    extras: bool = False,
    cta: str = "Continue to summary",
    first_index: int = 1,
    with_email: bool = True,
) -> dict[str, Any]:
    elements: list[Element] = []
    ref = 0

    def nxt() -> int:
        nonlocal ref
        ref += 1
        return ref

    for i in range(first_index, first_index + count):
        first = textbox(
            0, f"p{i}_first", f"Passenger {i} first name", required=True, context=f"Passenger {i}"
        )
        last = textbox(
            0, f"p{i}_last", f"Passenger {i} last name", required=True, context=f"Passenger {i}"
        )
        for field in [last, first] if reordered else [first, last]:
            field["ref"] = nxt()
            elements.append(field)
    if with_email:
        email = textbox(nxt(), "email", "Contact email", type="email", required=True)
        elements = [email, *elements] if reordered else [*elements, email]
    if extras:
        elements.append(textbox(nxt(), "phone", "Phone number (optional)", type="tel"))
        elements.append(
            el(nxt(), "input", "checkbox", type="checkbox", name="newsletter", label="Newsletter")
        )
    elements.append(button(nxt(), cta))
    return state(elements, "Passenger details", headings=["Passenger details"])


def results_page(select: str = "Select", sold_out: bool = False) -> dict[str, Any]:
    trains = [
        ("EC 111 Praha", "06:20", "14:05", "189.00"),
        ("EC 113 Vltava", "10:25", "18:10", "219.00"),
        ("EN 407 Chopin", "22:40", "07:05", "249.00"),
    ]
    elements = (
        []
        if sold_out
        else [
            button(
                i + 1,
                f"{select} {name}",
                context=f"{name} {dep} {arr} 2nd class {price} PLN / person {select}",
            )
            for i, (name, dep, arr, price) in enumerate(trains)
        ]
    )
    notice = "Sold out — no seats available on this date. " if sold_out else ""
    return state(elements, f"Trains Warszawa → Praha {notice}EC 111 Praha 06:20")


def summary_page(
    names: list[tuple[str, str]],
    *,
    date: str = "2026-12-04",
    total: str = "657.00",
    train: str = "EC 113 Vltava",
    pay: str = "Pay now",
) -> dict[str, Any]:
    people = [f"{f} {last}" for f, last in names]
    text = (
        f"Review your booking Route Warszawa → Praha Date {date} Train {train}, 10:25 → 18:10 "
        f"Passengers {len(names)} {' '.join(people)} Contact a@b.c Total: {total} PLN {pay}"
    )
    rows = [
        {"label": "Route", "value": "Warszawa → Praha", "items": []},
        {"label": "Date", "value": date, "items": []},
        {"label": "Train", "value": f"{train}, 10:25 → 18:10, 2nd class", "items": []},
        {"label": "Passengers", "value": f"{len(names)} {' '.join(people)}", "items": people},
    ]
    return state([button(1, pay)], text, rows=rows, headings=["Review your booking"])
