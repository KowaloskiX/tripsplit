"""Metrics of one brief's research, and the summary over all briefs.

Every metric is a score in [0, 1] (None = does not apply to this brief) plus the raw numbers
behind it. Definitions (also in the report):

- **completeness** — the share of the 3 expected packages that have transport both ways and a
  stay; an activity is reported (`activity_rate`) but not required.
- **budget** — with a budget the oracle can meet: 1 when at least one package fits it. With a
  budget nobody can meet: 1 only when the cheapest package is the cheapest possible (within 1%)
  AND a package says so ("budget" in its summary). No budget: None.
- **optimality** — 1 - gap, where gap = (cheapest package's transport + stay) / (the oracle's
  cheapest schedule-sane transport + stay) - 1, capped to [0, 1].
- **diversity** — distinct stays and distinct transports across the packages, each
  (distinct - 1) / (packages - 1), averaged.
- **schedule** — the share of schedule checks passed over all packages (`checks.py`).
- **consistency** — prices positive and in PLN, per-person = ceil(total / party), segment and
  stay dates inside the trip, the activity inside the trip.
- **mode** — every package honours the mode wish (rail / flight / fly there, train back).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.ai.research import PACKAGES_PER_RESEARCH, PackageItemPlan, PackagePlan
from app.core.domain.packages import per_person
from app.core.domain.trips import BookingKind, TransportMode
from app.search_evals.checks import schedule_checks, split_directions, travel_hours
from app.search_evals.dataset import ALLOWED_MODES, EvalBrief, ModeWish
from app.search_evals.oracle import Oracle, RawOffers, journey_of
from app.suppliers.ports import Offer

type Json = dict[str, Any]

WEIGHTS: dict[str, float] = {
    "completeness": 0.25,
    "budget": 0.15,
    "optimality": 0.15,
    "diversity": 0.10,
    "schedule": 0.15,
    "consistency": 0.10,
    "mode": 0.10,
}
CHEAPEST_TOLERANCE = 0.01


@dataclass
class PackageFacts:
    title: str
    total_minor: int
    per_person_minor: int
    complete: bool
    has_activity: bool
    within_budget: bool | None
    travel_hours: float
    checks: dict[str, bool]
    consistency: dict[str, bool]
    modes: list[str]

    def json(self) -> Json:
        return {
            "title": self.title,
            "total_minor": self.total_minor,
            "per_person_minor": self.per_person_minor,
            "complete": self.complete,
            "has_activity": self.has_activity,
            "within_budget": self.within_budget,
            "travel_hours": self.travel_hours,
            "failed_checks": [name for name, ok in self.checks.items() if not ok],
            "failed_consistency": [name for name, ok in self.consistency.items() if not ok],
            "modes": self.modes,
        }


@dataclass
class BriefResult:
    brief_id: str
    error: str | None = None
    scores: dict[str, float | None] = field(default_factory=dict)
    packages: list[PackageFacts] = field(default_factory=list)
    oracle: Oracle | None = None
    gap_percent: float | None = None
    activity_rate: float = 0.0
    quote_drift_percent: float | None = None
    llm_calls: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        if self.error is not None:
            return 0.0
        present = {k: v for k, v in self.scores.items() if v is not None}
        weight = sum(WEIGHTS[k] for k in present)
        return sum(WEIGHTS[k] * v for k, v in present.items()) / weight if weight else 0.0

    def json(self) -> Json:
        oracle = self.oracle
        return {
            "brief_id": self.brief_id,
            "error": self.error,
            "score": round(self.score, 4),
            "scores": {k: (round(v, 4) if v is not None else None) for k, v in self.scores.items()},
            "gap_percent": self.gap_percent,
            "activity_rate": self.activity_rate,
            "quote_drift_percent": self.quote_drift_percent,
            "llm_calls": self.llm_calls,
            "seconds": round(self.seconds, 3),
            "notes": self.notes,
            "packages": [package.json() for package in self.packages],
            "oracle": None
            if oracle is None
            else {
                "options": oracle.options,
                "stays": oracle.stays,
                "cheapest_total_minor": oracle.cheapest_total,
                "cheapest_sane_total_minor": oracle.cheapest_sane_total,
                "cheapest": oracle.cheapest_description,
                "feasible": oracle.feasible,
                "complete_possible": oracle.complete_possible,
            },
        }


def _transport(package: PackagePlan) -> list[PackageItemPlan]:
    return [item for item in package.items if item.kind is BookingKind.TRANSPORT]


def _of_kind(package: PackagePlan, kind: BookingKind) -> list[PackageItemPlan]:
    return [item for item in package.items if item.kind is kind]


def _core_total(package: PackagePlan) -> int:
    """Transport + stay, the part the oracle prices."""
    return sum(item.price_minor for item in package.items if item.kind is not BookingKind.ACTIVITY)


def _stay_dates_ok(item: PackageItemPlan, brief: EvalBrief) -> bool:
    data = item.supplier_data
    checkin, checkout = data.get("checkin"), data.get("checkout")
    if checkin is None or checkout is None:
        return True  # the stay was searched with the trip's dates; nothing else to compare
    trip = (brief.date_from.isoformat(), brief.date_to.isoformat())
    return (str(checkin), str(checkout)) == trip


def _in_trip(day: date, brief: EvalBrief) -> bool:
    return brief.date_from <= day <= brief.date_to


def consistency_checks(
    package: PackagePlan, brief: EvalBrief, offers: Mapping[tuple[str, str], Offer]
) -> dict[str, bool]:
    items = package.items
    known = [offers.get((item.supplier_id, item.offer_ref)) for item in items]
    total = package.total_minor
    share = per_person(total, brief.party) if total > 0 else 0
    segments = [segment for item in _transport(package) for segment in item.segments]
    activities = _of_kind(package, BookingKind.ACTIVITY)
    return {
        "prices_positive": all(item.price_minor > 0 for item in items),
        "currency_pln": all(offer is not None and offer.currency == "PLN" for offer in known),
        "price_matches_offer": all(
            offer is not None and offer.price_minor == item.price_minor
            for offer, item in zip(known, items, strict=True)
        ),
        "per_person_rounds_up": 0 <= share * brief.party - total < brief.party,
        "segment_dates_in_trip": all(
            _in_trip(s.departs_at.date(), brief) and _in_trip(s.arrives_at.date(), brief)
            for s in segments
        ),
        "stay_dates_match": all(
            _stay_dates_ok(item, brief) for item in _of_kind(package, BookingKind.STAY)
        ),
        "activity_in_trip": all(
            item.starts_at is None or _in_trip(item.starts_at.date(), brief) for item in activities
        ),
    }


def _modes(package: PackagePlan) -> list[TransportMode | None]:
    """Transport modes in travel order: outbound first."""
    ordered = sorted(
        _transport(package),
        key=lambda item: item.segments[0].departs_at.isoformat() if item.segments else "",
    )
    return [item.mode for item in ordered]


def mode_ok(package: PackagePlan, brief: EvalBrief) -> bool:
    out_mode, back_mode = ALLOWED_MODES[brief.mode]
    modes = _modes(package)
    if not modes:
        return False
    if brief.mode is ModeWish.FLY_THERE_TRAIN_BACK:
        return len(modes) == 2 and modes[0] is out_mode and modes[1] is back_mode
    return all(
        wanted is None or mode is wanted for mode in modes for wanted in (out_mode, back_mode)
    )


def package_facts(
    package: PackagePlan, brief: EvalBrief, offers: Mapping[tuple[str, str], Offer]
) -> PackageFacts:
    transport = _transport(package)
    segments = [segment for item in transport for segment in item.segments]
    out, back = split_directions(segments)
    complete = bool(out) and bool(back) and bool(_of_kind(package, BookingKind.STAY))
    budget = brief.budget_per_person_minor
    share = per_person(package.total_minor, brief.party) if package.total_minor > 0 else 0
    return PackageFacts(
        title=package.title,
        total_minor=package.total_minor,
        per_person_minor=share,
        complete=complete,
        has_activity=bool(_of_kind(package, BookingKind.ACTIVITY)),
        within_budget=None if budget is None else share <= budget,
        travel_hours=travel_hours(segments),
        checks=schedule_checks(segments, journey_of(brief)),
        consistency=consistency_checks(package, brief, offers),
        modes=[mode.value if mode else "?" for mode in _modes(package)],
    )


def _distinct(keys: Sequence[object], packages: int) -> float:
    if packages <= 1:
        return 1.0
    return (len(set(keys)) - 1) / (packages - 1)


def _stay_key(package: PackagePlan) -> tuple[str, ...]:
    return tuple(
        str(item.supplier_data.get("hotel_id") or item.title)
        for item in _of_kind(package, BookingKind.STAY)
    )


def _transport_key(package: PackagePlan) -> tuple[str, ...]:
    return tuple(item.offer_ref or item.title for item in _transport(package))


def _budget_score(
    brief: EvalBrief, packages: Sequence[PackagePlan], facts: Sequence[PackageFacts], oracle: Oracle
) -> float | None:
    if brief.budget_per_person_minor is None:
        return None
    if oracle.feasible:
        return 1.0 if any(f.within_budget and f.complete for f in facts) else 0.0
    complete = [p for p, f in zip(packages, facts, strict=True) if f.complete]
    reference = oracle.reference_total
    if not complete or reference is None:
        return 0.0
    cheapest = min(_core_total(p) for p in complete)
    is_cheapest = cheapest <= reference * (1 + CHEAPEST_TOLERANCE)
    explained = any("budget" in p.summary.casefold() for p in packages)
    return (0.5 if is_cheapest else 0.0) + (0.5 if explained else 0.0)


def evaluate(
    brief: EvalBrief, packages: Sequence[PackagePlan], raw: RawOffers, oracle: Oracle
) -> BriefResult:
    offers = {(offer.supplier_id, offer.offer_ref): offer for offer in raw.all_offers()}
    facts = [package_facts(package, brief, offers) for package in packages]
    result = BriefResult(brief_id=brief.id, oracle=oracle, packages=facts)
    complete = [p for p, f in zip(packages, facts, strict=True) if f.complete]
    result.scores["completeness"] = min(len(complete), PACKAGES_PER_RESEARCH) / (
        PACKAGES_PER_RESEARCH
    )
    result.activity_rate = (
        round(sum(f.has_activity for f in facts) / len(facts), 3) if facts else 0.0
    )
    result.scores["budget"] = _budget_score(brief, packages, facts, oracle)
    reference = oracle.reference_total
    if complete and reference:
        cheapest = min(_core_total(p) for p in complete)
        gap = cheapest / reference - 1
        result.gap_percent = round(gap * 100, 2)
        result.scores["optimality"] = max(0.0, min(1.0, 1 - gap))
    else:
        result.scores["optimality"] = 0.0 if reference else None
    if packages:
        n = len(packages)
        result.scores["diversity"] = (
            _distinct([_stay_key(p) for p in packages], n)
            + _distinct([_transport_key(p) for p in packages], n)
        ) / 2
        all_checks = [ok for f in facts for ok in f.checks.values()]
        result.scores["schedule"] = sum(all_checks) / len(all_checks) if all_checks else 0.0
        consistent = [ok for f in facts for ok in f.consistency.values()]
        result.scores["consistency"] = sum(consistent) / len(consistent) if consistent else 0.0
        result.scores["mode"] = sum(mode_ok(p, brief) for p in packages) / n
    else:
        for name in ("diversity", "schedule", "consistency", "mode"):
            result.scores[name] = 0.0
    return result


@dataclass
class Summary:
    briefs: int
    errors: int
    score: float  # 0..100
    metrics: dict[str, float | None]
    mean_gap_percent: float | None
    llm_calls: int
    seconds: float
    supplier_stats: dict[str, Json]

    def json(self) -> Json:
        return {
            "briefs": self.briefs,
            "errors": self.errors,
            "score": round(self.score, 2),
            "metrics": {
                k: (round(v, 4) if v is not None else None) for k, v in self.metrics.items()
            },
            "mean_gap_percent": self.mean_gap_percent,
            "llm_calls": self.llm_calls,
            "seconds": round(self.seconds, 2),
            "supplier_stats": self.supplier_stats,
        }


def summarise(results: Sequence[BriefResult], supplier_stats: dict[str, Json]) -> Summary:
    metrics: dict[str, float | None] = {}
    for name in WEIGHTS:
        values = [
            0.0 if r.error else r.scores.get(name)
            for r in results
            if r.error or r.scores.get(name) is not None
        ]
        present = [v for v in values if v is not None]
        metrics[name] = sum(present) / len(present) if present else None
    gaps = [r.gap_percent for r in results if r.gap_percent is not None]
    return Summary(
        briefs=len(results),
        errors=sum(1 for r in results if r.error),
        score=100 * sum(r.score for r in results) / len(results) if results else 0.0,
        metrics=metrics,
        mean_gap_percent=round(sum(gaps) / len(gaps), 2) if gaps else None,
        llm_calls=sum(r.llm_calls for r in results),
        seconds=sum(r.seconds for r in results),
        supplier_stats=supplier_stats,
    )
