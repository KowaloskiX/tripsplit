"""`CatalogResearcher`: packages composed from what the enabled suppliers actually offer.

It asks every transport supplier of the wanted mode (any mode when the trip has no preference),
every stay supplier and every activity supplier in the registry, then composes three packages
deterministically:

- **Budget** — the cheapest transport and a step up from the cheapest bed (none when the
  cheapest is known to be decent); if that breaks the per-person budget it trims to the
  cheapest bed, and says so when even that does not fit.
- **Comfort** — a third way to go when there is one (no slower than the cheapest, at most 1.5x
  its price), the second-best stay and the cheaper evening out; without the evening when that
  breaks the budget.
- **Splurge** — the dearest of the quickest transports, the best stay and the dearer evening.

Transport has to fit the calendar (`app.ai.itinerary`: there on day one, back on the last day,
no red-eye, the trip's travel preferences) whenever anything does. Two rail singles compete
with the return ticket. "Fly there, train back" in the brief composes one-way offers of two
modes; when the wished modes have nothing, each direction falls back to another mode and every
summary says so. Whether a package
still exceeds the budget is flagged where it is stored (`Proposal.over_budget`). With the PKP
Intercity adapter enabled this is the live research: real trains and fares, same rules.

Every supplier search of a research runs at once (transport, stays, activities). One that fails
or exceeds `supplier_timeout_s` contributes no offers and never fails the research by itself; a
timed-out search keeps running in the background and, with a `SearchCache`, fills the cache for
the next research. Each finished search is reported to the `research_progress` sink, if set.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from app.ai.itinerary import fits_calendar, leg_fits, travel_time
from app.ai.places import destination_of, travel_modes
from app.ai.research import (
    PackageItemPlan,
    PackagePlan,
    SearchOutcome,
    SupplierProgress,
    TripBrief,
    research_progress,
)
from app.core.domain.packages import is_over_budget, per_person
from app.core.domain.suppliers import mode_noun
from app.core.domain.trips import BookingKind, TransportMode
from app.suppliers.ports import Offer, SearchRequest, Segment, SupplierAdapter
from app.suppliers.registry import SupplierRegistry
from app.suppliers.search_cache import SearchCache

logger = logging.getLogger(__name__)

DEFAULT_SUPPLIER_TIMEOUT_S = 15.0
# Searches that outlived their timeout, referenced so they finish instead of being collected
# (the researcher that started one may be gone by then: it is built per request).
_BACKGROUND: set[asyncio.Task[list[Offer]]] = set()

type Transport = tuple[PackageItemPlan, ...]

# The cheapest one-way offers per direction that are paired into "two one-ways" options.
PAIRED_ONE_WAYS = 3
# ...and only when together they cost at least this much less than the return ticket.
ONE_WAYS_MIN_SAVING = 0.05
# Two singles are looked for by rail only: a rail return is two independently priced legs
# anyway (singles just widen the departure windows), while airlines price a return as a unit
# and an airline API counts every search against the look-to-book ratio.
SINGLES_MODE = TransportMode.RAIL
SINGLES_MODES: frozenset[TransportMode | None] = frozenset({None, SINGLES_MODE})
# The comfort package may pay this much more than the cheapest transport for a better one.
COMFORT_PRICE_FACTOR = 1.5
# The splurge takes the dearest option at most this much slower than the fastest.
SPLURGE_SLACK = timedelta(hours=1)
# A stay rated at least this (out of 10) and at most this far from the centre is decent.
DECENT_RATING = 8.0
DECENT_KM_FROM_CENTRE = 3.0


def _item(adapter: SupplierAdapter, offer: Offer) -> PackageItemPlan:
    return PackageItemPlan(
        kind=adapter.capabilities.kind,
        mode=adapter.capabilities.mode,
        title=offer.title,
        supplier=offer.seller,
        supplier_url=offer.purchase_url,
        price_minor=offer.price_minor,
        details=offer.details,
        starts_at=offer.starts_at,
        supplier_id=offer.supplier_id,
        offer_ref=offer.offer_ref,
        segments=offer.segments,
        refundable=offer.refundable,
        supplier_data=dict(offer.supplier_data),
    )


def _by_price(items: Sequence[PackageItemPlan]) -> list[PackageItemPlan]:
    # Ties broken by title, so the composition never depends on the order suppliers answer in.
    return sorted(items, key=lambda item: (item.price_minor, item.title))


def _label(transport: Transport) -> str:
    """ "Ryanair flight", "PKP Intercity train + FlixBus bus", "PKP Intercity train both ways"
    (two one-ways of the same carrier and mode)."""
    labels = [f"{item.supplier} {mode_noun(item.mode)}" for item in transport]
    if len(labels) == 2 and labels[0] == labels[1]:
        return f"{labels[0]} both ways"
    return " + ".join(labels)


def _total(transport: Transport) -> int:
    return sum(item.price_minor for item in transport)


def _segments(transport: Transport) -> list[Segment]:
    return [segment for item in transport for segment in item.segments]


def _fits_calendar(transport: Transport, brief: TripBrief) -> bool:
    return fits_calendar(_segments(transport), brief.date_from, brief.date_to, brief.preferences)


def _pairs(there: Sequence[PackageItemPlan], home: Sequence[PackageItemPlan]) -> list[Transport]:
    """The cheapest few one-ways out x back as options, cheapest first."""
    pairs: list[Transport] = [
        (out, back) for out in there[:PAIRED_ONE_WAYS] for back in home[:PAIRED_ONE_WAYS]
    ]
    return sorted(pairs, key=lambda t: (_total(t), _label(t)))


def _decent(stay: PackageItemPlan) -> bool:
    """A stay the supplier rates well and places near the centre — then the cheapest bed is
    good enough for the budget package, no step up needed. Unknown quality is not decent."""
    rating = stay.supplier_data.get("rating")
    km = stay.supplier_data.get("km_from_centre")
    return (
        isinstance(rating, int | float)
        and rating >= DECENT_RATING
        and isinstance(km, int | float)
        and km <= DECENT_KM_FROM_CENTRE
    )


def _directions(there: TransportMode | None, back: TransportMode | None) -> str:
    """ "train there and back", "flight there, train back"."""
    if there is back:
        return f"{mode_noun(there)} there and back"
    return f"{mode_noun(there)} there, {mode_noun(back)} back"


def _noted(package: PackagePlan, note: str) -> PackagePlan:
    return replace(package, summary=f"{package.summary} {note}") if note else package


def _travel_time(transport: Transport) -> timedelta:
    return travel_time(_segments(transport))


def _splurge_transport(transports: Sequence[Transport], cheapest: Transport) -> Transport:
    """The dearest of the quickest: the best class / most flexible fare among the options
    within `SPLURGE_SLACK` of the fastest — never a dear but slow detour, and not the
    budget's own transport while there is another."""
    pool = [t for t in transports if t != cheapest] or [cheapest]
    fastest = min(_travel_time(t) for t in pool)
    quick = [t for t in pool if _travel_time(t) <= fastest + SPLURGE_SLACK]
    return max(quick, key=lambda t: (_total(t), _label(t)))


def _comfort_transport(
    transports: Sequence[Transport], cheapest: Transport, splurge: Transport
) -> Transport:
    """A third way to go when there is one: no slower than the cheapest, at most
    `COMFORT_PRICE_FACTOR` dearer, the quickest of those; else the cheapest."""
    limit = _total(cheapest) * COMFORT_PRICE_FACTOR
    others = [
        t
        for t in transports
        if t not in (cheapest, splurge)
        and _total(t) <= limit
        and _travel_time(t) <= _travel_time(cheapest)
    ]
    return min(others, key=lambda t: (_travel_time(t), _total(t), _label(t)), default=cheapest)


def _settled(task: asyncio.Task[list[Offer]]) -> None:
    _BACKGROUND.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("a timed-out supplier search failed later: %s", task.exception())


class CatalogResearcher:
    def __init__(
        self,
        suppliers: SupplierRegistry,
        *,
        cache: SearchCache | None = None,
        supplier_timeout_s: float = DEFAULT_SUPPLIER_TIMEOUT_S,
    ) -> None:
        self.suppliers = suppliers
        self.cache = cache
        self.supplier_timeout_s = supplier_timeout_s

    async def research(self, brief: TripBrief) -> list[PackagePlan]:
        text = f"{brief.title} {brief.brief}"
        destination = destination_of(brief.destination, text)
        outbound, back = travel_modes(brief.transport_mode, text)
        transports, stays, activities = await asyncio.gather(
            self._transports(brief, destination, outbound, back),
            self._offers(BookingKind.STAY, brief, destination),
            self._offers(BookingKind.ACTIVITY, brief, destination),
        )
        note = ""
        if not transports and (outbound or back):
            transports, note = await self._fallback(brief, destination, outbound, back)
        if not transports:
            raise ValueError(f"no transport offers from {brief.origin} to {destination}")
        transports = [t for t in transports if _fits_calendar(t, brief)] or transports
        packages = self._compose(
            brief, destination, transports, _by_price(stays), _by_price(activities)
        )
        return [_noted(package, note) for package in packages]

    async def _search(
        self, kind: BookingKind, mode: TransportMode | None, request: SearchRequest
    ) -> list[PackageItemPlan]:
        adapters = self.suppliers.of_kind(kind, mode)
        answers = await asyncio.gather(*(self._ask(adapter, request) for adapter in adapters))
        return [
            _item(adapter, offer)
            for adapter, offers in zip(adapters, answers, strict=True)
            for offer in offers
        ]

    async def _ask(self, adapter: SupplierAdapter, request: SearchRequest) -> list[Offer]:
        """One supplier's offers; [] when it fails or is too slow — never an exception."""
        started = time.monotonic()
        cached = self.cache.get(adapter, request) if self.cache is not None else None
        if cached is not None:
            await self._report(adapter, SearchOutcome.CACHED, cached, started)
            return cached
        task = asyncio.ensure_future(self._fetch(adapter, request))
        try:
            offers = await asyncio.wait_for(asyncio.shield(task), self.supplier_timeout_s)
        except TimeoutError:
            logger.warning(
                "%s search exceeded %.1f s — researching without it",
                adapter.id,
                self.supplier_timeout_s,
            )
            _BACKGROUND.add(task)
            task.add_done_callback(_settled)
            await self._report(adapter, SearchOutcome.TIMEOUT, [], started)
            return []
        except Exception:
            # The boundary to a plugin: its failure means "no offers from it", nothing more.
            logger.exception("%s search failed", adapter.id)
            await self._report(adapter, SearchOutcome.FAILED, [], started)
            return []
        outcome = SearchOutcome.OK if offers else SearchOutcome.EMPTY
        await self._report(adapter, outcome, offers, started)
        return offers

    async def _fetch(self, adapter: SupplierAdapter, request: SearchRequest) -> list[Offer]:
        if self.cache is None:
            return await adapter.search(request)
        return await self.cache.search(adapter, request)

    async def _report(
        self,
        adapter: SupplierAdapter,
        outcome: SearchOutcome,
        offers: Sequence[Offer],
        started: float,
    ) -> None:
        sink = research_progress.get()
        if sink is None:
            return
        progress = SupplierProgress(
            supplier_id=adapter.id,
            supplier=adapter.display_name,
            kind=adapter.capabilities.kind,
            outcome=outcome,
            offers=len(offers),
            seconds=round(time.monotonic() - started, 2),
        )
        try:
            await sink(progress)
        except Exception:
            # Progress is a nicety; a broken sink must not cost the group its packages.
            logger.warning("research progress sink failed", exc_info=True)

    def _request(
        self, brief: TripBrief, origin: str, destination: str, *, one_way: bool = False
    ) -> SearchRequest:
        return SearchRequest(
            origin=origin,
            destination=destination,
            depart_date=brief.date_from,
            return_date=None if one_way else brief.date_to,
            party_size=brief.travellers,
            budget_per_person_minor=brief.budget_per_person_minor,
            currency=brief.currency,
            preferences=brief.preferences,
        )

    async def _offers(
        self, kind: BookingKind, brief: TripBrief, destination: str
    ) -> list[PackageItemPlan]:
        return await self._search(kind, None, self._request(brief, brief.origin, destination))

    async def _transports(
        self,
        brief: TripBrief,
        destination: str,
        outbound: TransportMode | None,
        back: TransportMode | None,
    ) -> list[Transport]:
        """Each option is the transport of one package, cheapest first: a return journey, or a
        one-way out plus a one-way back — when the modes differ, or when two rail singles beat
        the cheapest return that fits the calendar by `ONE_WAYS_MIN_SAVING`. Every search of
        it runs at once."""
        if outbound == back:
            request = replace(self._request(brief, brief.origin, destination), mode=outbound)
            if outbound not in SINGLES_MODES:
                found = await self._search(BookingKind.TRANSPORT, outbound, request)
                return [(item,) for item in _by_price(found)]
            found, there, home = await asyncio.gather(
                self._search(BookingKind.TRANSPORT, outbound, request),
                self._one_way(brief, destination, SINGLES_MODE, home=False),
                self._one_way(brief, destination, SINGLES_MODE, home=True),
            )
            returns: list[Transport] = [(item,) for item in _by_price(found)]
            fitting = [t for t in returns if _fits_calendar(t, brief)] or returns
            bar = min((_total(t) for t in fitting), default=None)
            # Two bookings instead of one are worth it only for a real saving.
            cheaper = [
                pair
                for pair in _pairs(there, home)
                if bar is None or _total(pair) <= bar * (1 - ONE_WAYS_MIN_SAVING)
            ]
            return sorted([*returns, *cheaper], key=lambda t: (_total(t), _label(t)))
        there, home = await asyncio.gather(
            self._one_way(brief, destination, outbound, home=False),
            self._one_way(brief, destination, back, home=True),
        )
        return _pairs(there, home)

    async def _one_way(
        self, brief: TripBrief, destination: str, mode: TransportMode | None, *, home: bool
    ) -> list[PackageItemPlan]:
        """One-way offers there (or home, on the last day) in `mode`, cheapest first — only
        the ones that fit the calendar (`leg_fits`) when there are any."""
        start, end = (destination, brief.origin) if home else (brief.origin, destination)
        day = brief.date_to if home else brief.date_from
        request = replace(
            self._request(brief, start, end, one_way=True), depart_date=day, mode=mode
        )
        found = _by_price(await self._search(BookingKind.TRANSPORT, mode, request))
        fitting = [
            item
            for item in found
            if leg_fits(item.segments, day, brief.preferences, arrive_same_day=not home)
        ]
        return fitting or found

    async def _fallback(
        self,
        brief: TripBrief,
        destination: str,
        outbound: TransportMode | None,
        back: TransportMode | None,
    ) -> tuple[list[Transport], str]:
        """When the wished modes have nothing both ways: each direction in its wished mode if
        it has offers, else in any other mode — and a sentence saying so."""
        legs = await asyncio.gather(
            self._leg_or_other_mode(brief, destination, outbound, home=False),
            self._leg_or_other_mode(brief, destination, back, home=True),
        )
        there, home = legs
        if not there or not home:
            return [], ""
        wished = _directions(outbound, back)
        used = _directions(there[0].mode, home[0].mode)
        note = f"No {wished} on these dates, so this goes {used}."
        return _pairs(there, home), note

    async def _leg_or_other_mode(
        self, brief: TripBrief, destination: str, mode: TransportMode | None, *, home: bool
    ) -> list[PackageItemPlan]:
        found = await self._one_way(brief, destination, mode, home=home) if mode else []
        if found:
            return found
        anything = await self._one_way(brief, destination, None, home=home)
        return [item for item in anything if item.mode is not mode]

    def _fits(self, items: Sequence[PackageItemPlan], brief: TripBrief) -> bool:
        total = sum(item.price_minor for item in items)
        return not is_over_budget(
            per_person(total, brief.travellers), brief.budget_per_person_minor
        )

    def _compose(
        self,
        brief: TripBrief,
        place: str,
        transports: list[Transport],
        stays: list[PackageItemPlan],
        activities: list[PackageItemPlan],
    ) -> list[PackagePlan]:
        cheapest = min(transports, key=_total)
        dearest = _splurge_transport(transports, cheapest)
        budget = self._budget(brief, place, cheapest, stays)
        comfort = self._comfort(
            brief, place, _comfort_transport(transports, cheapest, dearest), stays, activities
        )
        splurge_items = [*dearest]
        if stays:
            splurge_items.append(stays[-1])
        if activities:
            splurge_items.append(activities[-1])
        extras = " + ".join(item.title for item in splurge_items[len(dearest) :])
        splurge = PackagePlan(
            title=f"Splurge: {_label(dearest)} + {extras}"[:120]
            if extras
            else f"Splurge: {_label(dearest)}"[:120],
            summary=f"The best of everything in {place}: {_label(dearest)}"
            + (f", {stays[-1].title}" if stays else "")
            + (f" and {activities[-1].title}." if activities else "."),
            items=tuple(splurge_items),
        )
        return [budget, comfort, splurge]

    def _budget(
        self, brief: TripBrief, place: str, transport: Transport, stays: list[PackageItemPlan]
    ) -> PackagePlan:
        step_up = len(stays) > 2 and not _decent(stays[0])
        candidates = [stays[1], stays[0]] if step_up else stays[:1]
        chosen: list[PackageItemPlan] = []
        for stay in candidates:
            chosen = [*transport, stay]
            if self._fits(chosen, brief):
                break
        if not chosen:
            chosen = [*transport]
        stay_title = chosen[-1].title if len(chosen) > len(transport) else ""
        return PackagePlan(
            title=(f"Budget: {_label(transport)}" + (f" + {stay_title}" if stay_title else ""))[
                :120
            ],
            summary=f"The cheapest way to {place}: {_label(transport)}"
            + (f" and {stay_title}." if stay_title else ".")
            + self._over_budget_note(chosen, brief),
            items=tuple(chosen),
        )

    def _over_budget_note(self, items: Sequence[PackageItemPlan], brief: TripBrief) -> str:
        """When even the cheapest combination breaks the budget, the group hears it plainly —
        with what the trip costs at the least, so it can raise the budget or change dates."""
        if self._fits(items, brief) or brief.budget_per_person_minor is None:
            return ""
        share = per_person(sum(item.price_minor for item in items), brief.travellers)
        return (
            f" Nothing found fits the budget of {brief.budget_per_person_minor // 100} "
            f"{brief.currency} per person: this is the cheapest combination, "
            f"{-(-share // 100)} {brief.currency} per person."
        )

    def _comfort(
        self,
        brief: TripBrief,
        place: str,
        transport: Transport,
        stays: list[PackageItemPlan],
        activities: list[PackageItemPlan],
    ) -> PackagePlan:
        base = [*transport]
        if stays:
            base.append(stays[-2] if len(stays) >= 2 else stays[0])
        with_evening = [*base, activities[0]] if activities else base
        items = with_evening if self._fits(with_evening, brief) else base
        stay = f" + {base[-1].title}" if len(base) > len(transport) else ""
        evening = f" + {activities[0].title}" if len(items) > len(base) else ""
        return PackagePlan(
            title=f"Comfort: {_label(transport)}{stay}{evening}"[:120],
            summary=f"A comfortable {place} weekend: {_label(transport)}{stay}{evening}.".replace(
                " + ", ", "
            ),
            items=tuple(items),
        )
