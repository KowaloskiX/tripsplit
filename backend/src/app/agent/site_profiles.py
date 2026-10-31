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
    FARE = "fare"  # an opened offer: pick the fare (class, refundable or not)
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
    # Recorded flows are kept per host; a second site on the same host (our demo shops share
    # localhost) names its own scope so the two never replay each other's flow.
    flow_scope: str = ""
    # The site sells the whole party under ONE lead name (no per-passenger fields): the
    # summary check then only looks for passenger 1.
    lead_passenger_only: bool = False
    # Page text where the run must stop and hand over to a person even though nothing went
    # wrong (e.g. a sign-in / guest-checkout wall): a planned handoff at `handoff_milestone`.
    # A run ending there still counts as a success for recording the flow.
    handoff_markers: tuple[str, ...] = ()
    handoff_milestone: str = ""
    # Fare buttons inside an opened offer; group 1 = the travel class. The site lists the
    # cheapest (non-refundable) fare of a class first and the flexible one last.
    fare_buttons: str = ""
    # Page text stating the party size the offers are priced for (group 1). When it differs
    # from the goal, offers are not chosen by rule: the party must be changed first.
    party_shown: str = ""
    # Re-observations (1.5 s apart) a flow step waits for a late-rendering target before it
    # counts as a miss; 0 = heal at once (our own sites render synchronously).
    target_patience: int = 0

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
            flow_scope=self.flow_scope,
            lead_passenger_only=self.lead_passenger_only,
            handoff_markers=self.handoff_markers,
            handoff_milestone=self.handoff_milestone,
            fare_buttons=self.fare_buttons,
            party_shown=self.party_shown,
            target_patience=self.target_patience,
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

DEMOTICKETS = SiteProfile(
    name="demotickets",
    path_prefix="/api/demo-supplier/tickets",
    cta={
        Stage.SEARCH: (r"^find time slots$",),
        Stage.PASSENGERS: (r"continue to summary",),
    },
    pay=(r"pay now",),
    review_markers=(r"review your order",),
    confirmation_markers=(r"booking number:",),
    confirmation_ref=r"\bTK-[A-Z0-9]{8}\b",
    # The goal names the planned entry slot ("entry at 14:30"); the shop sells half-hourly
    # entries, so the nearest one is the intended one.
    unmatched_offer=OfferFallback.CLOSEST_DEPARTURE,
    max_passengers_per_purchase=10,
    human_typing=False,
    flow_scope="tickets",
)

INTERCITY = SiteProfile(
    name="intercity",
    hosts=("intercity.pl",),
    cta={
        Stage.SEARCH: (r"^wyszukaj$",),
        Stage.RESULTS: (r"buy a ticket", r"kup bilet"),
        Stage.PASSENGERS: (r"go to payments", r"przejdź do płatności"),
    },
    unavailable=(r"no offers fulfil the criteria", r"przerwa technologiczna"),
    max_passengers_per_purchase=5,
    # "GO TO PAYMENTS" opens a sign-in wall (log in / register / continue as guest). Going on
    # means an e-mail address and accepting the e-IC regulations on someone's behalf, so the
    # agent hands over here: the selection is done, a person continues.
    handoff_markers=(r"continue as (?:a )?guest", r"kontynuuj jako gość"),
    handoff_milestone="guest_screen",
    # "BUY A TICKET" opens fare boxes: Non-refundable (Super Promo) first, Flexible second,
    # per class; an unavailable class has a disabled button.
    fare_buttons=r"^(?:choose|wybierz) (?:class|klas[aęy]) ([12])$",
    # The header reads "3x Passengers 3 x Adults"; the adults count is what gets sold.
    party_shown=r"(\d+)\s*x\s*(?:adults?|dorosł)",
    # The header's CHANGE and the fare boxes render seconds after the page.
    target_patience=4,
)

BLAZEDEMO = SiteProfile(
    # BlazeMeter's public flight-booking demo built for test automation: no real money, the
    # "Purchase Flight" button returns a fake confirmation id. Search (two city selects) ->
    # flights table -> purchase page (reservation + billing/card form) -> confirmation.
    name="blazedemo",
    hosts=("blazedemo.com",),
    cta={Stage.SEARCH: (r"^find flights$",)},
    pay=(r"^purchase flight$",),
    review_markers=(r"has been reserved", r"please submit the form below"),
    confirmation_markers=(r"thank you for your purchase",),
    confirmation_ref=r"\b\d{10,16}\b",
    total=r"total cost\D{0,10}(\d[\d,]*\.\d{2})\s*(USD)?",
    offer_policy=OfferPolicy.CHEAPEST,
    lead_passenger_only=True,
    human_typing=False,
)

PROFILES: tuple[SiteProfile, ...] = (DEMORAIL, DEMOTICKETS, INTERCITY, BLAZEDEMO)


def profile_for(url: str) -> SiteProfile:
    """The most specific matching profile merged with GENERIC (GENERIC alone otherwise)."""
    hits = [p for p in PROFILES if p.matches(url)]
    if not hits:
        return GENERIC
    best = max(hits, key=lambda p: (len(p.path_prefix), len("".join(p.hosts))))
    return best.merged(GENERIC)


def any_match(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)
