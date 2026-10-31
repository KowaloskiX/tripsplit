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
"""

from collections.abc import Sequence
from dataclasses import replace

from app.ai.places import destination_of, travel_modes
from app.ai.research import PackageItemPlan, PackagePlan, TripBrief
from app.core.domain.packages import is_over_budget, per_person
from app.core.domain.suppliers import mode_noun
from app.core.domain.trips import BookingKind, TransportMode
from app.suppliers.ports import Offer, SearchRequest, SupplierAdapter
from app.suppliers.registry import SupplierRegistry

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


class CatalogResearcher:
    def __init__(self, suppliers: SupplierRegistry) -> None:
        self.suppliers = suppliers

    async def research(self, brief: TripBrief) -> list[PackagePlan]:
        text = f"{brief.title} {brief.brief}"
        destination = destination_of(brief.destination, text)
        outbound, back = travel_modes(brief.transport_mode, text)
        transports = await self._transports(brief, destination, outbound, back)
        if not transports:
            raise ValueError(f"no transport offers from {brief.origin} to {destination}")
        stays = _by_price(await self._offers(BookingKind.STAY, brief, destination))
        activities = _by_price(await self._offers(BookingKind.ACTIVITY, brief, destination))
        return self._compose(brief, destination, transports, stays, activities)

    async def _search(
        self, kind: BookingKind, mode: TransportMode | None, request: SearchRequest
    ) -> list[PackageItemPlan]:
        found: list[PackageItemPlan] = []
        for adapter in self.suppliers.of_kind(kind, mode):
            found.extend(_item(adapter, offer) for offer in await adapter.search(request))
        return found

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
        one-way out plus a one-way back when the modes differ."""
        if outbound == back:
            request = replace(self._request(brief, brief.origin, destination), mode=outbound)
            found = await self._search(BookingKind.TRANSPORT, outbound, request)
            return [(item,) for item in _by_price(found)]
        there = _by_price(
            await self._search(
                BookingKind.TRANSPORT,
                outbound,
                replace(
                    self._request(brief, brief.origin, destination, one_way=True), mode=outbound
                ),
            )
        )
        home_request = replace(
            self._request(brief, destination, brief.origin, one_way=True),
            depart_date=brief.date_to,
            mode=back,
        )
        home = _by_price(await self._search(BookingKind.TRANSPORT, back, home_request))
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
