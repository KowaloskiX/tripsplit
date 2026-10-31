"""`CatalogResearcher`: packages composed from what the enabled suppliers actually offer.

It asks every transport supplier of the wanted mode (any mode when the trip has no preference),
every stay supplier and every activity supplier in the registry, then composes three packages
deterministically:

- **Budget** — the cheapest transport and a step up from the cheapest bed; if that breaks the
  per-person budget it trims to the cheapest bed.
- **Comfort** — the cheapest transport, the second-best stay and the cheaper evening out;
  without the evening when that breaks the budget.
- **Splurge** — the dearest transport, the best stay and the dearer evening. It stays a splurge.

"Fly there, train back" in the brief composes one-way offers of two modes. Whether a package
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
from app.suppliers.ports import Offer, SearchRequest, SupplierAdapter
from app.suppliers.registry import SupplierRegistry
from app.suppliers.search_cache import SearchCache

logger = logging.getLogger(__name__)

DEFAULT_SUPPLIER_TIMEOUT_S = 15.0
# Searches that outlived their timeout, referenced so they finish instead of being collected
# (the researcher that started one may be gone by then: it is built per request).
_BACKGROUND: set[asyncio.Task[list[Offer]]] = set()

type Transport = tuple[PackageItemPlan, ...]


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
    """ "Ryanair flight", "PKP Intercity train + FlixBus bus"."""
    return " + ".join(f"{item.supplier} {mode_noun(item.mode)}" for item in transport)


def _total(transport: Transport) -> int:
    return sum(item.price_minor for item in transport)


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
        if not transports:
            raise ValueError(f"no transport offers from {brief.origin} to {destination}")
        return self._compose(
            brief, destination, transports, _by_price(stays), _by_price(activities)
        )

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
        one-way out plus a one-way back when the modes differ (both directions searched at
        once)."""
        if outbound == back:
            request = replace(self._request(brief, brief.origin, destination), mode=outbound)
            found = await self._search(BookingKind.TRANSPORT, outbound, request)
            return [(item,) for item in _by_price(found)]
        there_request = replace(
            self._request(brief, brief.origin, destination, one_way=True), mode=outbound
        )
        home_request = replace(
            self._request(brief, destination, brief.origin, one_way=True),
            depart_date=brief.date_to,
            mode=back,
        )
        there_found, home_found = await asyncio.gather(
            self._search(BookingKind.TRANSPORT, outbound, there_request),
            self._search(BookingKind.TRANSPORT, back, home_request),
        )
        there, home = _by_price(there_found), _by_price(home_found)
        if not there or not home:
            return []
        return [(there[0], home[0]), (there[-1], home[-1])]

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
        dearest = max(transports, key=_total)
        budget = self._budget(brief, place, cheapest, stays)
        comfort = self._comfort(brief, place, cheapest, stays, activities)
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
        candidates = [stays[1], stays[0]] if len(stays) > 2 else stays[:1]
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
            + (f" and {stay_title}." if stay_title else "."),
            items=tuple(chosen),
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
