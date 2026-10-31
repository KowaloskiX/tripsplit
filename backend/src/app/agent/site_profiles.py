"""Per-site knowledge as DATA the rule layer executes — the typed half of a playbook.

The markdown playbooks in `skills/` stay as human documentation and planner context; the
deterministic layer never parses prose. What it needs is here: how to recognise a checkout
stage, which button copy moves each stage forward, which button is the payment (never pressed
before a human approves), how the site says "sold out", and the policy for picking an offer
when the goal does not name one.

Matching is by host suffix plus an optional path prefix, most specific first. Every site
profile is MERGED with `GENERIC` (its patterns come first), so a profile only lists what is
special about the site.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse


class Stage(StrEnum):
    CONSENT = "consent"
    SEARCH = "search"
    RESULTS = "results"
    PASSENGERS = "passengers"
    REVIEW = "review"
    CONFIRMATION = "done"
    UNAVAILABLE = "blocked"
    UNKNOWN = "unknown"


class OfferFallback(StrEnum):
    """What to do when the goal names an offer the site does not list."""

    PLANNER = "planner"  # not confident: ask the planner (real suppliers)
    CLOSEST_DEPARTURE = "closest_departure"  # a stand-in site: take the nearest departure


class OfferPolicy(StrEnum):
    EARLIEST = "earliest"
    CHEAPEST = "cheapest"


@dataclass(frozen=True, slots=True)
class SiteProfile:
    name: str
    hosts: tuple[str, ...] = ()
    path_prefix: str = ""
    # Regexes (case-insensitive) for the button that moves a stage FORWARD.
    cta: dict[Stage, tuple[str, ...]] = field(default_factory=dict)
    # Regexes for the final payment button: never clicked while stop_before_pay is set.
    pay: tuple[str, ...] = ()
    consent: tuple[str, ...] = ()
    # Page text meaning "nothing to buy here" -> handoff with the reason.
    unavailable: tuple[str, ...] = ()
    # Page text on a review/summary page and on a confirmation page.
    review_markers: tuple[str, ...] = ()
    confirmation_markers: tuple[str, ...] = ()
    confirmation_ref: str = r"\b[A-Z]{2,4}-[A-Z0-9]{6,12}\b"
    total: str = (
        r"(?:total|razem|suma|do zapłaty|amount due)\D{0,20}?"
        r"(\d[\d\s\u00a0]*[.,]\d{2})\s*(PLN|zł|EUR|CZK)?"
    )
    offer_policy: OfferPolicy = OfferPolicy.EARLIEST
    unmatched_offer: OfferFallback = OfferFallback.PLANNER
    max_passengers_per_purchase: int | None = None
    # Type at a human pace (bot management watches keystroke timing); off for our own sites.
    human_typing: bool = True

    def matches(self, url: str) -> bool:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
        host_ok = not self.hosts or any(host.endswith(h) for h in self.hosts)
        return host_ok and parsed.path.startswith(self.path_prefix)

    def merged(self, base: "SiteProfile") -> "SiteProfile":
        stages = set(self.cta) | set(base.cta)
        return SiteProfile(
            name=self.name,
            hosts=self.hosts,
            path_prefix=self.path_prefix,
            cta={s: self.cta.get(s, ()) + base.cta.get(s, ()) for s in stages},
            pay=self.pay + base.pay,
            consent=self.consent + base.consent,
            unavailable=self.unavailable + base.unavailable,
            review_markers=self.review_markers + base.review_markers,
            confirmation_markers=self.confirmation_markers + base.confirmation_markers,
            confirmation_ref=self.confirmation_ref,
            total=self.total,
            offer_policy=self.offer_policy,
            unmatched_offer=self.unmatched_offer,
            max_passengers_per_purchase=self.max_passengers_per_purchase,
            human_typing=self.human_typing,
        )


GENERIC = SiteProfile(
    name="generic",
    cta={
        Stage.SEARCH: (r"\bsearch\b", r"\bfind\b", r"szukaj", r"wyszukaj", r"znajdź"),
        Stage.PASSENGERS: (
            r"continue",
            r"\bnext\b",
            r"proceed",
            r"dalej",
            r"kontynuuj",
            r"przejdź",
            r"summary",
            r"podsumowanie",
            r"\bsave\b",
            r"zapisz",
        ),
    },
    pay=(
        r"\bpay\b",
        r"zapłać",
        r"płacę",
        r"buy now",
        r"kupuj",
        r"\bpurchase\b",
        r"place order",
        r"zamawiam",
        r"book now",
        r"confirm and pay",
    ),
    consent=(
        r"accept all",
        r"accept cookies",
        r"allow all",
        r"i accept",
        r"akceptuj",
        r"zaakceptuj",
        r"zgadzam się",
    ),
    unavailable=(
        r"sold out",
        r"no seats",
        r"wyprzedan",
        r"brak miejsc",
        r"no offers",
        r"brak ofert",
        r"too many passengers",
        r"no longer available",
    ),
    review_markers=(r"review", r"summary", r"podsumowanie", r"sprawdź"),
    confirmation_markers=(
        r"booking number",
        r"numer rezerwacji",
        r"reservation number",
        r"booking confirmed",
        r"thank you",
    ),
)

DEMORAIL = SiteProfile(
    name="demorail",
    path_prefix="/api/demo-supplier/rail",
    cta={
        Stage.SEARCH: (r"^search$", r"szukaj połączeń"),
        Stage.PASSENGERS: (r"continue to summary", r"dalej: podsumowanie", r"^next"),
    },
    pay=(r"pay now", r"zapłać i kupuję"),
    review_markers=(r"review your booking",),
    confirmation_markers=(r"booking number:",),
    confirmation_ref=r"\bDR-[A-Z0-9]{8}\b",
    # The demo site stands in for the real carrier: its three trains never carry the real
    # train numbers a proposal names, so the nearest departure is the intended substitute.
    unmatched_offer=OfferFallback.CLOSEST_DEPARTURE,
    max_passengers_per_purchase=5,
    human_typing=False,
)

INTERCITY = SiteProfile(
    name="intercity",
    hosts=("intercity.pl",),
    cta={
        Stage.SEARCH: (r"^wyszukaj$",),
        Stage.RESULTS: (r"buy a ticket", r"kup bilet"),
        Stage.PASSENGERS: (r"go to payments", r"przejdź do płatności", r"continue as guest"),
    },
    unavailable=(r"no offers fulfil the criteria", r"przerwa technologiczna"),
    max_passengers_per_purchase=5,
)

PROFILES: tuple[SiteProfile, ...] = (DEMORAIL, INTERCITY)


def profile_for(url: str) -> SiteProfile:
    """The most specific matching profile merged with GENERIC (GENERIC alone otherwise)."""
    hits = [p for p in PROFILES if p.matches(url)]
    if not hits:
        return GENERIC
    best = max(hits, key=lambda p: (len(p.path_prefix), len("".join(p.hosts))))
    return best.merged(GENERIC)


def any_match(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)
