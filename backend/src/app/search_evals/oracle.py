"""The oracle: every offer the suppliers had for a brief, and the best combinations of them.

It asks every transport supplier of an allowed mode for a return journey and for one-way legs
out and back (so mixed-mode and two-one-ways combinations count), every stay and every activity
supplier — through the same (recorded) suppliers the research uses. The cheapest COMPLETE combo
(transport both ways + a stay) is what the research's cheapest package is measured against;
the cheapest one that also passes every schedule check is preferred when there is one.
"""

import itertools
from dataclasses import dataclass, field, replace

from app.core.domain.packages import per_person
from app.core.domain.trips import BookingKind, TransportMode
from app.search_evals.checks import Journey, schedule_ok
from app.search_evals.dataset import ALLOWED_MODES, EvalBrief
from app.suppliers.ports import Offer, SearchRequest, Segment
from app.suppliers.registry import SupplierRegistry

# One-way legs kept per direction when pairing them (cheapest first).
MAX_ONE_WAYS = 12


@dataclass(frozen=True, slots=True)
class Priced:
    offer: Offer
    mode: TransportMode | None


@dataclass
class RawOffers:
    returns: list[Priced] = field(default_factory=list)
    outs: list[Priced] = field(default_factory=list)
    backs: list[Priced] = field(default_factory=list)
    stays: list[Offer] = field(default_factory=list)
    activities: list[Offer] = field(default_factory=list)

    def all_offers(self) -> list[Offer]:
        transport = [p.offer for p in [*self.returns, *self.outs, *self.backs]]
        return [*transport, *self.stays, *self.activities]


@dataclass(frozen=True, slots=True)
class TransportOption:
    legs: tuple[Priced, ...]

    @property
    def total(self) -> int:
        return sum(leg.offer.price_minor for leg in self.legs)

    @property
    def segments(self) -> list[Segment]:
        return [segment for leg in self.legs for segment in leg.offer.segments]

    def describe(self) -> str:
        return " + ".join(leg.offer.title for leg in self.legs)


@dataclass(frozen=True, slots=True)
class Oracle:
    options: int  # transport options considered
    stays: int
    cheapest_total: int | None  # transport + stay, any schedule
    cheapest_sane_total: int | None  # transport + stay, every schedule check passing
    cheapest_description: str
    feasible: bool | None  # within budget at all; None = no budget
    complete_possible: bool

    @property
    def reference_total(self) -> int | None:
        return self.cheapest_sane_total if self.cheapest_sane_total else self.cheapest_total


def _allowed(mode: TransportMode | None, wanted: TransportMode | None) -> bool:
    return wanted is None or mode is wanted


def journey_of(brief: EvalBrief) -> Journey:
    return Journey(
        origin=brief.origin,
        destination=brief.destination,
        date_from=brief.date_from,
        date_to=brief.date_to,
        earliest_departure_hour=brief.earliest_departure_hour,
    )


async def collect(brief: EvalBrief, suppliers: SupplierRegistry) -> RawOffers:
    """Everything every supplier has for the brief — every transport mode, whatever the wish
    (so a research that falls back to another mode replays from the same recordings); the
    wish filters the combinations in `transport_options`."""
    raw = RawOffers()
    base = SearchRequest(
        origin=brief.origin,
        destination=brief.destination,
        depart_date=brief.date_from,
        return_date=brief.date_to,
        party_size=brief.party,
        budget_per_person_minor=brief.budget_per_person_minor,
    )
    there = replace(base, return_date=None)
    home = replace(
        base, origin=brief.destination, destination=brief.origin, depart_date=brief.date_to
    )
    home = replace(home, return_date=None)
    for adapter in suppliers.of_kind(BookingKind.TRANSPORT):
        mode = adapter.capabilities.mode
        raw.returns.extend(Priced(o, mode) for o in await adapter.search(base))
        raw.outs.extend(Priced(o, mode) for o in await adapter.search(replace(there, mode=mode)))
        raw.backs.extend(Priced(o, mode) for o in await adapter.search(replace(home, mode=mode)))
    for adapter in suppliers.of_kind(BookingKind.STAY):
        raw.stays.extend(await adapter.search(base))
    for adapter in suppliers.of_kind(BookingKind.ACTIVITY):
        raw.activities.extend(await adapter.search(base))
    return raw


def transport_options(brief: EvalBrief, raw: RawOffers) -> list[TransportOption]:
    """Return journeys and one-way pairs in the modes the brief wishes."""
    out_mode, back_mode = ALLOWED_MODES[brief.mode]
    options = [
        TransportOption((leg,))
        for leg in raw.returns
        if _allowed(leg.mode, out_mode) and _allowed(leg.mode, back_mode)
    ]
    outs = sorted(
        (p for p in raw.outs if _allowed(p.mode, out_mode)), key=lambda p: p.offer.price_minor
    )[:MAX_ONE_WAYS]
    backs = sorted(
        (p for p in raw.backs if _allowed(p.mode, back_mode)), key=lambda p: p.offer.price_minor
    )[:MAX_ONE_WAYS]
    options.extend(TransportOption((out, back)) for out, back in itertools.product(outs, backs))
    return sorted(options, key=lambda option: (option.total, option.describe()))


def solve(brief: EvalBrief, raw: RawOffers) -> Oracle:
    options = transport_options(brief, raw)
    journey = journey_of(brief)
    cheapest_stay = min((stay.price_minor for stay in raw.stays), default=None)
    sane = [option for option in options if schedule_ok(option.segments, journey)]
    complete = bool(options) and cheapest_stay is not None
    cheapest = options[0].total + cheapest_stay if complete and cheapest_stay is not None else None
    cheapest_sane = sane[0].total + cheapest_stay if sane and cheapest_stay is not None else None
    reference = cheapest_sane or cheapest
    budget = brief.budget_per_person_minor
    feasible = None
    if budget is not None:
        feasible = reference is not None and per_person(reference, brief.party) <= budget
    best = sane[0] if sane else (options[0] if options else None)
    return Oracle(
        options=len(options),
        stays=len(raw.stays),
        cheapest_total=cheapest,
        cheapest_sane_total=cheapest_sane,
        cheapest_description=best.describe() if best else "",
        feasible=feasible,
        complete_possible=complete,
    )
