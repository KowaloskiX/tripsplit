"""The deterministic layer: unambiguous steps decided without a model.

Given a typed observation, the parsed goal, the vault and the site profile, `RuleEngine.decide`
returns a short PLAN of actions for the current page — or None when it is not confident, and
only then does the runner ask the planner. Confidence is structural, never a guess:

  - consent wall           -> click the single accept control
  - "sold out"/"too many"  -> handoff with the supplier's reason
  - search form            -> type the goal date (and return date), select the party size,
                              click the one CTA
  - offer list             -> click the offer the goal names (or the earliest / cheapest), once
                              the page is priced for the goal's party
  - opened offer's fares   -> the goal's class: the first fare (cheapest) or the flexible one
  - passenger form         -> fill every field whose label maps to a vault key, click the CTA
  - review/summary         -> verify names, count, date and total against the goal; `done`
                              (stop-before-pay) or `handoff` when the supplier total differs
                              from the budget by more than the tolerance
  - confirmation           -> `done` with the booking reference

Anything else (an unknown required field, two plausible CTAs, an offer the goal names but the
page does not show) returns None. The same summary check guards a planner's `done`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.agent.goal import GoalSpec
from app.agent.site_profiles import OfferFallback, SiteProfile, Stage, any_match
from app.agent.summary import SummaryRecord, extract_summary

Element = dict[str, Any]
Action = dict[str, Any]


class FieldKind(StrEnum):
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    EMAIL = "email"
    PHONE = "phone"
    DATE_OF_BIRTH = "date_of_birth"
    NATIONALITY = "nationality"
    DOCUMENT_NUMBER = "document_number"
    DOCUMENT_EXPIRY = "document_expiry"
    TRAVEL_DATE = "travel_date"
    RETURN_DATE = "return_date"
    PARTY_SIZE = "party_size"
    ORIGIN = "origin"
    DESTINATION = "destination"
    OPTIONAL_EXTRA = "optional_extra"


# Order matters: the first pattern that matches wins ("date of birth" before "date").
_FIELD_PATTERNS: tuple[tuple[FieldKind, str], ...] = (
    (FieldKind.OPTIONAL_EXTRA, r"newsletter|promo|voucher|kod rabat|marketing|coupon"),
    (FieldKind.EMAIL, r"e-?mail"),
    (FieldKind.PHONE, r"phone|telefon|\btel\b|mobile|komórk"),
    (FieldKind.DATE_OF_BIRTH, r"birth|urodz"),
    (FieldKind.DOCUMENT_EXPIRY, r"expir|ważno"),
    (FieldKind.DOCUMENT_NUMBER, r"document|passport|paszport|dowód|id number"),
    (FieldKind.NATIONALITY, r"nationality|obywatel"),
    (FieldKind.FIRST_NAME, r"first\s*name|given\s*name|forename|imi[eę]|_first\b|\bfirst\b|fname"),
    (FieldKind.LAST_NAME, r"last\s*name|family\s*name|surname|nazwisk|_last\b|\blast\b|lname"),
    (FieldKind.RETURN_DATE, r"\breturn\b|powr[óo]t"),
    (
        FieldKind.ORIGIN,
        r"\bfrom_?(?:port|city|airport|station)\b|\borigin\b|leaving from|"
        r"departure (?:city|airport|station)|skąd",
    ),
    (
        FieldKind.DESTINATION,
        r"\bto_?(?:port|city|airport|station)\b|\bdestination\b|going to|"
        r"arrival (?:city|airport|station)|dokąd",
    ),
    (FieldKind.PARTY_SIZE, r"passengers|pasażer|pasazer|travell?ers|persons|osób|osoby|liczba"),
    (FieldKind.TRAVEL_DATE, r"\bdate\b|\bdata\b|yyyy|rrrr|departure day|dzień"),
)
_PER_PASSENGER = {
    FieldKind.FIRST_NAME: "first_name",
    FieldKind.LAST_NAME: "last_name",
    FieldKind.DATE_OF_BIRTH: "date_of_birth",
    FieldKind.NATIONALITY: "nationality",
    FieldKind.DOCUMENT_NUMBER: "document_number",
    FieldKind.DOCUMENT_EXPIRY: "document_expiry",
}
_INDEX_IN_LABEL = re.compile(
    r"(?:passenger|pasażer|pasazer|travell?er|osoba|guest|person)\w*\s*(?:no\.?\s*)?#?(\d+)",
    re.I,
)
_INDEX_IN_NAME = re.compile(r"(?:^|[^a-z])p(?:assenger)?[_-]?(\d+)(?:[_-]|$)|[_-](\d+)[_-]", re.I)
_TIME = re.compile(r"\b([0-2]?\d):([0-5]\d)\b(?:\s*([AP]M)\b)?", re.I)
# "123.45 PLN" / "123,45 zł" / "$472.56" / "€ 99.00" / "99.00 USD".
_PRICE = re.compile(
    r"(?:[$€£]\s?(\d[\d,\u00a0]*\.\d{2}))|(\d[\d\s\u00a0]*[.,]\d{2})\s*(?:PLN|zł|EUR|CZK|USD|GBP)",
    re.I,
)
_MAX_WAITS = 4
_MAX_SAME_PLAN = 2


@dataclass(frozen=True, slots=True)
class FieldRole:
    kind: FieldKind
    index: int | None = None


def _money(amount_minor: int) -> str:
    """`113400` -> `"1 134.00"` — the app's money style (`core.domain.bookings.format_money`)."""
    whole, grosze = divmod(abs(amount_minor), 100)
    sign = "-" if amount_minor < 0 else ""
    return f"{sign}{whole:,}".replace(",", " ") + f".{grosze:02d}"


@dataclass(frozen=True, slots=True)
class SummaryCheck:
    ok: bool
    problems: tuple[str, ...]
    record: SummaryRecord
    price_mismatch: bool = False
    notes: tuple[str, ...] = ()

    @property
    def total(self) -> float | None:
        minor = self.record.total_minor
        return minor / 100 if minor is not None else None

    def reason(self, goal: GoalSpec) -> str:
        minor = self.record.total_minor
        total = (
            f"{_money(minor)} {self.record.currency or ''}".strip()
            if minor is not None
            else "unknown"
        )
        if self.ok:
            date = f", date {goal.date}" if goal.date else ""
            notes = "".join(f"; {n}" for n in self.notes)
            return f"summary verified: {goal.passengers} passenger(s){date}, total {total}{notes}"
        problems = "; ".join(self.problems)
        return f"summary does not match the goal ({problems}); supplier total {total}"


@dataclass(slots=True)
class RuleDecision:
    stage: Stage
    actions: list[Action]
    why: str


def vault_placeholder(key: str) -> str:
    return "{{vault." + key + "}}"


def _haystack(el: Element) -> str:
    parts = [el.get("label"), el.get("placeholder"), el.get("name"), el.get("id"), el.get("testid")]
    if not el.get("label"):
        parts.append(el.get("text"))
    return " ".join(str(p) for p in parts if p).lower()


def classify_field(el: Element) -> FieldRole | None:
    """What a form control asks for, from its accessible identity. None = not a form field."""
    role = el.get("role")
    if role not in ("textbox", "combobox", "checkbox", "spinbutton"):
        return None
    if el.get("type") in ("submit", "button", "hidden", "radio"):
        return None
    hay = _haystack(el)
    if el.get("type") == "date" and "birth" not in hay and "urodz" not in hay:
        is_return = re.search(r"\breturn\b|powr[óo]t", hay, re.I)
        return FieldRole(FieldKind.RETURN_DATE if is_return else FieldKind.TRAVEL_DATE)
    for kind, pattern in _FIELD_PATTERNS:
        if re.search(pattern, hay, re.I):
            if role == "checkbox" and kind is not FieldKind.OPTIONAL_EXTRA:
                return FieldRole(FieldKind.OPTIONAL_EXTRA)
            if kind in (FieldKind.ORIGIN, FieldKind.DESTINATION) and el.get("tag") != "select":
                return None  # a typed station/airport box needs its suggestion clicked

            return FieldRole(kind, _passenger_index(el) if kind in _PER_PASSENGER else None)
    return FieldRole(FieldKind.OPTIONAL_EXTRA) if role == "checkbox" else None


def _passenger_index(el: Element) -> int | None:
    for source in (el.get("label"), el.get("text"), el.get("context")):
        if source and (m := _INDEX_IN_LABEL.search(str(source))) is not None:
            return int(m.group(1))
    for source in (el.get("name"), el.get("id")):
        if source and (m := _INDEX_IN_NAME.search(str(source))) is not None:
            return int(m.group(1) or m.group(2))
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _number(raw: str) -> float:
    return float(re.sub(r"[\s\u00a0]", "", raw).replace(",", "."))


def is_button(el: Element) -> bool:
    return el.get("role") == "button"


def button_label(el: Element) -> str:
    return _norm(str(el.get("text") or el.get("label") or ""))


def offer_buttons(elements: list[Element]) -> list[Element]:
    """Per-row "select this offer" buttons: a button whose row carries a time or a price."""
    rows = [
        el
        for el in elements
        if is_button(el)
        and el.get("context")
        and (_TIME.search(el["context"]) or _PRICE.search(el["context"]))
    ]
    return rows if len(rows) >= 2 else []


def _departure(el: Element) -> tuple[int, int]:
    m = _TIME.search(str(el.get("context") or ""))
    if not m:
        return (99, 99)
    hour, minute, half = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
    if half:
        hour = hour % 12 + (12 if half == "PM" else 0)
    return (hour, minute)


def _price(el: Element) -> float:
    m = _PRICE.search(str(el.get("context") or ""))
    if not m:
        return float("inf")
    if m.group(1):  # "$1,234.56": the comma groups thousands
        return float(re.sub(r"[,\s\u00a0]", "", m.group(1)))
    return _number(m.group(2))


def _minutes_from(el: Element, departs: str | None) -> int:
    hour, minute = _departure(el)
    if not departs:
        return hour * 60 + minute
    want_h, want_m = (int(x) for x in departs.split(":"))
    return abs(hour * 60 + minute - (want_h * 60 + want_m))


def choose_offer(elements: list[Element], goal: GoalSpec, profile: SiteProfile) -> Element | None:
    """The offer the goal asks for; the profile's default policy when it names none."""
    offers = offer_buttons(elements)
    if not offers:
        return None
    if goal.train:
        wanted = _compact(goal.train)
        code = _compact(" ".join(goal.train.split()[:2]))
        for needle in (wanted, code):
            hits = [
                o
                for o in offers
                if needle in _compact(f"{o.get('context', '')} {o.get('text', '')}")
            ]
            if len(hits) == 1:
                return hits[0]
        if profile.unmatched_offer != OfferFallback.CLOSEST_DEPARTURE:
            return None
        return min(offers, key=lambda o: _minutes_from(o, goal.departs))
    if goal.rebooking:
        return None  # "the next train after the delayed one" needs judgement -> planner
    if goal.departs and profile.unmatched_offer == OfferFallback.CLOSEST_DEPARTURE:
        return min(offers, key=lambda o: _minutes_from(o, goal.departs))  # a timed entry
    if goal.cheapest or profile.offer_policy == "cheapest":
        return min(offers, key=_price)
    return min(offers, key=_departure)


def fare_buttons(elements: list[Element], profile: SiteProfile) -> list[tuple[Element, int]]:
    """Enabled fare buttons of an opened offer with their travel class, in page order."""
    if not profile.fare_buttons:
        return []
    out = []
    for el in elements:
        if is_button(el) and (m := re.search(profile.fare_buttons, button_label(el), re.I)):
            out.append((el, int(m.group(1))))
    return out


def choose_fare(elements: list[Element], goal: GoalSpec, profile: SiteProfile) -> Element | None:
    """The goal's class (default 2nd); the first fare (cheapest) or, if flexible, the last."""
    wanted = goal.travel_class or 2
    fares = [el for el, travel_class in fare_buttons(elements, profile) if travel_class == wanted]
    if not fares:
        return None
    return fares[-1] if goal.flexible else fares[0]


def _cta(elements: list[Element], stage: Stage, profile: SiteProfile) -> Element | None:
    """The single forward button for this stage: profile copy, generic copy, or the only one."""
    candidates = [
        el
        for el in elements
        if is_button(el)
        and not any_match(profile.pay, button_label(el))
        and not any_match(profile.consent, button_label(el))
    ]
    offers = {id(o) for o in offer_buttons(elements)}
    candidates = [el for el in candidates if id(el) not in offers]
    others = [p for s, p in profile.cta.items() if s != stage]
    for patterns in (profile.cta.get(stage, ()), *others):
        hits = [el for el in candidates if any_match(patterns, button_label(el))]
        if len(hits) == 1:
            return hits[0]
    submits = [
        el
        for el in candidates
        if el.get("type") in ("submit", "") and el["tag"] in ("button", "input")
    ]
    return submits[0] if len(submits) == 1 else None


def _option_named(el: Element, place: str) -> str | None:
    """The select option that IS the named place (case/whitespace-insensitive), else None."""
    wanted = _norm(place)
    hits = [str(o).strip() for o in el.get("options") or [] if _norm(str(o)) == wanted]
    return hits[0] if len(hits) == 1 else None


def _unfilled_form(elements: list[Element]) -> bool:
    """Any empty text field the vault could fill (names, email, billing, card)."""
    return any(
        el.get("role") == "textbox"
        and el.get("type") not in ("hidden", "search")
        and not el.get("value")
        for el in elements
    )


def pay_button(elements: list[Element], profile: SiteProfile) -> Element | None:
    hits = [el for el in elements if is_button(el) and any_match(profile.pay, button_label(el))]
    return hits[0] if len(hits) == 1 else None


def detect_stage(state: dict[str, Any], profile: SiteProfile) -> Stage:
    elements: list[Element] = state.get("elements") or []
    text = str(state.get("text") or state.get("text_preview") or "")
    headings = " ".join(state.get("headings") or [])
    if any_match(profile.confirmation_markers, text) and re.search(profile.confirmation_ref, text):
        return Stage.CONFIRMATION
    consent = [
        el for el in elements if is_button(el) and any_match(profile.consent, button_label(el))
    ]
    if consent and len([el for el in elements if is_button(el)]) <= 3:
        return Stage.CONSENT
    if pay_button(elements, profile) is not None and (
        any_match(profile.review_markers, f"{headings} {text[:400]}")
        or re.search(profile.total, text, re.I)
    ):
        return Stage.REVIEW
    roles = [classify_field(el) for el in elements]
    kinds = {r.kind for r in roles if r is not None}
    if kinds & {FieldKind.FIRST_NAME, FieldKind.LAST_NAME, FieldKind.EMAIL}:
        return Stage.PASSENGERS
    if fare_buttons(elements, profile):
        return Stage.FARE
    if offer_buttons(elements):
        return Stage.RESULTS
    if any_match(profile.unavailable, text):
        return Stage.UNAVAILABLE
    if kinds & {
        FieldKind.TRAVEL_DATE,
        FieldKind.PARTY_SIZE,
        FieldKind.ORIGIN,
        FieldKind.DESTINATION,
    }:
        return Stage.SEARCH
    return Stage.UNKNOWN


def verify_summary(
    state: dict[str, Any], goal: GoalSpec, names: list[tuple[str, str]], profile: SiteProfile
) -> SummaryCheck:
    """Extract the summary record and check it against the goal.

    `names` are vault values: compared here, never echoed into a reason.
    """
    record = extract_summary(state, profile)
    # Names typed into the page's own form (a billing form next to the pay button) count too.
    typed = " | ".join(
        str(el.get("value") or "")
        for el in state.get("elements") or []
        if el.get("role") == "textbox" and el.get("value")
    )
    page = _norm(f"{state.get('text') or state.get('text_preview') or ''} | {typed}")
    problems: list[str] = []
    notes: list[str] = []
    if profile.lead_passenger_only:
        # The site sells the whole party under the lead traveller's name.
        names = names[:1]
        notes.append(f"site books under the lead passenger's name only ({goal.passengers} pax)")
    wanted = [_norm(f"{first} {last}") for first, last in names]
    if record.passengers:
        shown = [_norm(n) for n in record.passengers]
        missing = sum(1 for w in wanted if w not in shown)
        unexpected = sum(1 for n in shown if n not in wanted)
        if missing:
            problems.append(f"{missing} of {len(wanted)} passenger names missing")
        if unexpected:
            problems.append(f"{unexpected} unexpected passenger(s)")
    elif sum(1 for w in wanted if w in page) != len(wanted):
        problems.append("passenger names not all shown")
    if record.passenger_count is not None and record.passenger_count != goal.passengers:
        problems.append(f"passenger count {record.passenger_count} != {goal.passengers}")
    if goal.date and record.date != goal.date:
        problems.append(f"date {record.date or 'missing'} != {goal.date}")
    if goal.return_date and record.return_date != goal.return_date:
        problems.append(
            f"return leg missing: return date {record.return_date or 'missing'} "
            f"!= {goal.return_date}"
        )
    elif not goal.return_date and record.return_date:
        problems.append(f"unexpected return leg on {record.return_date}")
    if goal.train:
        code = _compact(" ".join(goal.train.split()[:2]))
        shown_service = _compact(record.service or "") if record.service else _compact(page)
        if code not in shown_service:
            if profile.unmatched_offer == OfferFallback.CLOSEST_DEPARTURE and record.service:
                notes.append(f"{goal.train} is not offered here; booked {record.service}")
            else:
                problems.append("requested train not shown")
    price_mismatch = False
    if goal.budget is not None:
        total = record.total_minor / 100 if record.total_minor is not None else None
        if total is None:
            problems.append("no total on the summary")
        elif abs(total - goal.budget) > goal.budget * goal.tolerance_percent / 100:
            price_mismatch = True
            delta = (total - goal.budget) / goal.budget * 100 if goal.budget else 0.0
            problems.append(
                f"price changed: supplier total {_money(round(total * 100))} vs expected "
                f"{_money(round(goal.budget * 100))} "
                f"({delta:+.1f}%, tolerance {goal.tolerance_percent:g}%)"
            )
    return SummaryCheck(not problems, tuple(problems), record, price_mismatch, tuple(notes))


@dataclass
class RuleEngine:
    goal: GoalSpec
    profile: SiteProfile
    vault_get: Callable[[str], Any]
    vault_keys: list[str]
    stop_before_pay: bool = True
    _waits: int = 0
    _wait_url: str = ""
    _last_sig: tuple[str, str] | None = None
    _same: int = 0
    _offer_clicked: str = ""
    _offer_waits: int = 0
    last_stage: Stage = Stage.UNKNOWN
    last_summary: SummaryRecord | None = None
    notes: list[str] = field(default_factory=list)

    def names(self) -> list[tuple[str, str]]:
        return [
            (
                str(self.vault_get(f"passenger_{i}_first_name") or ""),
                str(self.vault_get(f"passenger_{i}_last_name") or ""),
            )
            for i in range(1, self.goal.passengers + 1)
        ]

    def decide(self, state: dict[str, Any]) -> RuleDecision | None:
        decision = self._decide(state)
        if decision is None:
            return None
        sig = (str(state.get("url", "")), repr(decision.actions))
        self._same = self._same + 1 if sig == self._last_sig else 0
        self._last_sig = sig
        if self._same > _MAX_SAME_PLAN and decision.actions[0]["action"] not in ("wait",):
            self.notes.append(f"rule plan repeated without progress at stage {decision.stage}")
            return None
        return decision

    def _decide(self, state: dict[str, Any]) -> RuleDecision | None:
        elements: list[Element] = state.get("elements") or []
        stage = detect_stage(state, self.profile)
        self.last_stage = stage
        if not elements and stage is Stage.UNKNOWN:
            url = str(state.get("url", ""))
            self._waits = self._waits + 1 if url == self._wait_url else 1
            self._wait_url = url
            if self._waits > _MAX_WAITS:
                return None
            wait = [{"action": "wait", "ms": 1000, "milestone": None}]
            return RuleDecision(stage, wait, "page not rendered yet")
        self._waits = 0
        if (wall := self._pass_wall(state)) is not None:
            return wall
        handler = {
            Stage.CONFIRMATION: self._confirmation,
            Stage.UNAVAILABLE: self._unavailable,
            Stage.CONSENT: self._consent,
            Stage.REVIEW: self._review,
            Stage.PASSENGERS: self._form,
            Stage.SEARCH: self._form,
            Stage.RESULTS: self._results,
            Stage.FARE: self._fare,
        }.get(stage)
        return handler(state, stage) if handler else None

    def _pass_wall(self, state: dict[str, Any]) -> RuleDecision | None:
        """Click the profile's way through a sign-in wall ("Continue as Guest"), if shown."""
        if not self.profile.handoff_pass:
            return None
        elements: list[Element] = state.get("elements") or []
        hits = [
            el
            for el in elements
            if el.get("role") in ("link", "button")
            and re.search(self.profile.handoff_pass, button_label(el), re.I)
        ]
        if len(hits) != 1 or _unfilled_form(elements):
            return None
        click = {"action": "click", "ref": hits[0]["ref"], "milestone": "guest_screen"}
        return RuleDecision(Stage.UNKNOWN, [click], "through the sign-in wall as a guest")

    def _handoff_form(self, state: dict[str, Any], stage: Stage) -> RuleDecision:
        """Fill what the vault can, then stop BEFORE any checkbox or submit: a planned handoff.

        Checkboxes (the regulations, marketing consents) are never ticked and nothing is
        clicked; an unmapped field is left for the person who takes over.
        """
        fills: list[dict[str, Any]] = []
        positions: dict[FieldKind, int] = {}
        for el in state["elements"]:
            role = classify_field(el)
            if role is None or el.get("role") != "textbox" or el.get("tag") == "select":
                continue
            positions[role.kind] = positions.get(role.kind, 0) + 1
            value = self.field_value(el, role, positions[role.kind])
            if not value or self._current_matches(el, value):
                continue
            fills.append({"ref": el["ref"], "text": value})
        milestone = self.profile.handoff_milestone or "handoff"
        plan: list[Action] = []
        if fills:
            plan.append({"action": "fill_form", "fields": fills, "milestone": stage.value})
        plan.append(
            {
                "action": "handoff",
                "reason": f"planned handoff at {milestone}: the form is filled, nothing "
                "submitted — a person accepts the regulations and pays",
                "milestone": milestone,
            }
        )
        return RuleDecision(stage, plan, f"{len(fills)} field(s) filled, then handoff")

    def _confirmation(self, state: dict[str, Any], stage: Stage) -> RuleDecision:
        m = re.search(self.profile.confirmation_ref, str(state.get("text") or ""))
        ref = m.group(0) if m else ""
        return RuleDecision(
            stage,
            [{"action": "done", "reason": f"booking confirmed {ref}".strip(), "milestone": "done"}],
            "confirmation page",
        )

    def _unavailable(self, state: dict[str, Any], stage: Stage) -> RuleDecision:
        text = str(state.get("text") or "")
        phrase = next(
            (m.group(0) for p in self.profile.unavailable if (m := re.search(p, text, re.I))), ""
        )
        return RuleDecision(
            stage,
            [
                {
                    "action": "handoff",
                    "reason": f"supplier reports: {phrase}",
                    "milestone": "blocked",
                }
            ],
            "nothing to buy",
        )

    def _consent(self, state: dict[str, Any], stage: Stage) -> RuleDecision | None:
        hits = [
            el
            for el in state["elements"]
            if is_button(el)
            and any_match(self.profile.consent, button_label(el))
            and not re.search(r"reject|odrzu|settings|ustawienia|manage", button_label(el))
        ]
        if len(hits) != 1:
            return None
        return RuleDecision(
            stage, [{"action": "click", "ref": hits[0]["ref"], "milestone": "browsing"}], "consent"
        )

    def summary_check(self, state: dict[str, Any]) -> SummaryCheck:
        check = verify_summary(state, self.goal, self.names(), self.profile)
        self.last_summary = check.record
        return check

    def _review(self, state: dict[str, Any], stage: Stage) -> RuleDecision | None:
        check = self.summary_check(state)
        if not check.ok and _unfilled_form(state["elements"]):
            # A pay page that still asks for data (a billing form next to the pay button):
            # filling it is the flow's or the planner's job; the check runs again after.
            self.notes.append("the summary page still has empty form fields to fill")
            return None
        if not check.ok:
            return RuleDecision(
                stage,
                [{"action": "handoff", "reason": check.reason(self.goal), "milestone": "review"}],
                "summary mismatch",
            )
        if self.stop_before_pay:
            return RuleDecision(
                stage,
                [{"action": "done", "reason": check.reason(self.goal), "milestone": "review"}],
                "summary verified",
            )
        pay = pay_button(state["elements"], self.profile)
        if pay is None:
            return None
        click = {"action": "click", "ref": pay["ref"], "milestone": "payment"}
        return RuleDecision(stage, [click], "pay")

    def _party_differs(self, state: dict[str, Any]) -> bool:
        """The page prices offers for a different party than the goal's."""
        if not self.profile.party_shown:
            return False
        m = re.search(self.profile.party_shown, str(state.get("text") or ""), re.I)
        if m is None or int(m.group(1)) == self.goal.passengers:
            return False
        self.notes.append(
            f"the page is set for {m.group(1)} passenger(s), the goal needs "
            f"{self.goal.passengers}: change the party first"
        )
        return True

    def _results(self, state: dict[str, Any], stage: Stage) -> RuleDecision | None:
        if self._party_differs(state):
            return None
        offer = choose_offer(state["elements"], self.goal, self.profile)
        if offer is None:
            return None
        # The same offer still listed right after clicking it: it is opening in place (fare
        # boxes still loading). Clicking again would fold it, so wait a moment instead.
        context = str(offer.get("context") or "")[:60]
        if context and context == self._offer_clicked and self._offer_waits < _MAX_WAITS:
            self._offer_waits += 1
            wait = [{"action": "wait", "ms": 1500, "milestone": None}]
            return RuleDecision(stage, wait, "offer opening")
        self._offer_clicked, self._offer_waits = context, 0
        click = {"action": "click", "ref": offer["ref"], "milestone": "results", "choice": "offer"}
        return RuleDecision(stage, [click], "offer chosen")

    def _fare(self, state: dict[str, Any], stage: Stage) -> RuleDecision | None:
        fare = choose_fare(state["elements"], self.goal, self.profile)
        if fare is None or self._party_differs(state):
            return None  # the wanted class is unavailable on this train: judgement needed
        click = {"action": "click", "ref": fare["ref"], "milestone": "fare", "choice": "fare"}
        return RuleDecision(stage, [click], "fare chosen")

    def field_value(self, el: Element, role: FieldRole, position: int) -> str | None:
        """The placeholder/literal for a field; "" = leave it; None = cannot decide."""
        kind = role.kind
        if kind is FieldKind.OPTIONAL_EXTRA:
            return ""
        if kind is FieldKind.TRAVEL_DATE:
            return self.goal.date if self.goal.date else ("" if el.get("value") else None)
        if kind is FieldKind.RETURN_DATE:
            # A one-way goal leaves it empty; a prefilled return on a one-way goal needs judgement.
            return self.goal.return_date or (None if el.get("value") else "")
        if kind is FieldKind.PARTY_SIZE:
            return str(self.goal.passengers)
        if kind in (FieldKind.ORIGIN, FieldKind.DESTINATION):
            place = self.goal.origin if kind is FieldKind.ORIGIN else self.goal.destination
            return _option_named(el, place) if place else None
        if kind in (FieldKind.EMAIL, FieldKind.PHONE):
            key = kind.value
            if key in self.vault_keys:
                return vault_placeholder(key)
            return None if el.get("required") else ""
        index = role.index or position
        key = f"passenger_{index}_{_PER_PASSENGER[kind]}"
        if index > self.goal.passengers:
            return None
        if key in self.vault_keys:
            return vault_placeholder(key)
        return None if el.get("required") else ""

    def _current_matches(self, el: Element, value: str) -> bool:
        current = str(el.get("value") or "")
        if not current:
            return False
        if value.startswith("{{vault."):
            return current == str(self.vault_get(value[8:-2]))[:40]
        if el.get("tag") == "select":
            return current == value
        return current == value

    def _form(self, state: dict[str, Any], stage: Stage) -> RuleDecision | None:
        if stage is Stage.PASSENGERS and self.profile.handoff_pass:
            return self._handoff_form(state, stage)
        elements: list[Element] = state["elements"]
        fills: list[dict[str, Any]] = []
        actions: list[Action] = []
        positions: dict[FieldKind, int] = {}
        for el in elements:
            role = classify_field(el)
            if role is None:
                if el.get("role") == "textbox" and el.get("required") and not el.get("value"):
                    return None  # a required field we cannot map
                continue
            positions[role.kind] = positions.get(role.kind, 0) + 1
            value = self.field_value(el, role, positions[role.kind])
            if value is None:
                return None
            # A route select is always set explicitly, even when it already shows the goal's
            # city: the recorded flow must carry the step to replay another route.
            route = role.kind in (FieldKind.ORIGIN, FieldKind.DESTINATION)
            if value == "" or (not route and self._current_matches(el, value)):
                continue
            if el.get("tag") == "select":
                options = [str(o).strip() for o in el.get("options") or []]
                if value not in options:
                    return None
                actions.append({"action": "select", "ref": el["ref"], "text": value})
            elif el.get("role") == "textbox":
                fills.append({"ref": el["ref"], "text": value})
        cta = _cta(elements, stage, self.profile)
        if cta is None:
            return None
        plan: list[Action] = []
        if fills:
            plan.append({"action": "fill_form", "fields": fills})
        plan.extend(actions)
        plan.append({"action": "click", "ref": cta["ref"]})
        for action in plan:
            action["milestone"] = stage.value
        return RuleDecision(stage, plan, f"{len(fills)} field(s), {len(actions)} select(s), CTA")
