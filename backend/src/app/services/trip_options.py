"""The options of a research, for picking a trip one step at a time (the chat flow).

Pure functions: which candidates become options (the researcher's own list, else the
packages' items), how they ride through the link check, and how one pick of each becomes a
package. No database, no HTTP.
"""

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass

from app.ai.research import PackageItemPlan, PackagePlan, ResearchCandidates
from app.core.domain.packages import format_money, is_over_budget, per_person
from app.core.domain.suppliers import mode_noun
from app.core.domain.trips import BookingKind
from app.models.trips import ProposalItem, TransportSegment, TripOption
from app.models.trust import stored_images, stored_links, stored_provenance

# Enough to choose from in a chat, few enough to read on a phone.
MAX_TRANSPORT_OPTIONS = 6
MAX_STAY_OPTIONS = 6
MAX_ACTIVITY_OPTIONS = 8


def _key(item: PackageItemPlan) -> tuple[str, str, str]:
    return (item.supplier_id, item.offer_ref, item.title)


def _unique[T](options: Sequence[T], key: Callable[[T], Hashable]) -> list[T]:
    seen: set[Hashable] = set()
    kept: list[T] = []
    for option in options:
        marker = key(option)
        if marker not in seen:
            seen.add(marker)
            kept.append(option)
    return kept


def candidate_options(
    plans: Sequence[PackagePlan], found: ResearchCandidates
) -> ResearchCandidates:
    """The researcher's candidates when it reported any, else every distinct item of the
    packages (a fixture or LLM researcher only returns packages). Capped, order kept; free
    ideas are never options (they are not bought)."""
    if found.empty:
        transports = [
            tuple(item for item in plan.items if item.kind is BookingKind.TRANSPORT)
            for plan in plans
        ]
        stays = [item for plan in plans for item in plan.items if item.kind is BookingKind.STAY]
        activities = [
            item for plan in plans for item in plan.items if item.kind is BookingKind.ACTIVITY
        ]
        found = ResearchCandidates(
            transports=[t for t in transports if t],
            stays=sorted(stays, key=lambda i: (i.price_minor, i.title)),
            activities=sorted(activities, key=lambda i: (i.price_minor, i.title)),
        )
    return ResearchCandidates(
        transports=_unique(found.transports, lambda t: tuple(_key(i) for i in t))[
            :MAX_TRANSPORT_OPTIONS
        ],
        stays=_unique(found.stays, _key)[:MAX_STAY_OPTIONS],
        activities=_unique([a for a in found.activities if a.price_minor > 0], _key)[
            :MAX_ACTIVITY_OPTIONS
        ],
    )


def as_plans(options: ResearchCandidates) -> list[PackagePlan]:
    """Each option as a one-off package, so the link check can verify it with the packages."""
    groups = [*options.transports, *((s,) for s in options.stays)]
    groups += [(a,) for a in options.activities]
    return [PackagePlan(title="", summary="", items=group) for group in groups]


def from_plans(options: ResearchCandidates, plans: Sequence[PackagePlan]) -> ResearchCandidates:
    """The inverse of `as_plans` (the link check keeps order and count)."""
    groups = [plan.items for plan in plans]
    n_transport, n_stays = len(options.transports), len(options.stays)
    return ResearchCandidates(
        transports=list(groups[:n_transport]),
        stays=[group[0] for group in groups[n_transport : n_transport + n_stays]],
        activities=[group[0] for group in groups[n_transport + n_stays :]],
    )


def proposal_item(item: PackageItemPlan) -> ProposalItem:
    return ProposalItem(
        kind=item.kind,
        mode=item.mode,
        title=item.title,
        supplier=item.supplier,
        supplier_url=item.supplier_url,
        price_minor=item.price_minor,
        details=item.details,
        starts_at=item.starts_at,
        supplier_id=item.supplier_id,
        offer_ref=item.offer_ref,
        segments=[
            TransportSegment(
                carrier=segment.carrier,
                number=segment.number,
                origin=segment.origin,
                destination=segment.destination,
                departs_at=segment.departs_at,
                arrives_at=segment.arrives_at,
            )
            for segment in item.segments
        ],
        refundable=item.refundable,
        supplier_data=dict(item.supplier_data),
        links=stored_links(item.links),
        images=stored_images(item.images),
        provenance=stored_provenance(item.provenance),
    )


def stored_options(
    options: ResearchCandidates,
) -> tuple[list[TripOption], list[TripOption], list[TripOption]]:
    """(transport, stays, activities) with ids "t0", "s0", "a0", ..."""
    return (
        [
            TripOption(option_id=f"t{i}", items=[proposal_item(item) for item in transport])
            for i, transport in enumerate(options.transports)
        ],
        [
            TripOption(option_id=f"s{i}", items=[proposal_item(stay)])
            for i, stay in enumerate(options.stays)
        ],
        [
            TripOption(option_id=f"a{i}", items=[proposal_item(activity)])
            for i, activity in enumerate(options.activities)
        ],
    )


def option_label(items: Sequence[ProposalItem]) -> str:
    """ "PKP Intercity train both ways", "Duffel Airways flight + FlixBus bus", or the title
    of a stay / an activity."""
    if not items:
        return ""
    if items[0].kind is not BookingKind.TRANSPORT:
        return items[0].title
    labels = [f"{item.supplier} {mode_noun(item.mode)}" for item in items]
    if len(labels) == 2 and labels[0] == labels[1]:
        return f"{labels[0]} both ways"
    return " + ".join(labels)


@dataclass(frozen=True, slots=True)
class CustomPackage:
    title: str
    summary: str
    items: tuple[ProposalItem, ...]
    total_minor: int
    per_person_minor: int
    over_budget: bool


def custom_package(
    picked: Sequence[TripOption],
    *,
    travellers: int,
    budget_per_person_minor: int | None,
    currency: str,
) -> CustomPackage:
    """One package from the options the organizer picked, in the order picked (transport,
    stay, activities) — priced and budget-flagged like a researched one."""
    items = tuple(item for option in picked for item in option.items)
    total = sum(item.price_minor for item in items)
    share = per_person(total, travellers)
    labels = [option_label(option.items) for option in picked]
    title = f"Your pick: {' + '.join(labels[:2])}"[:120]
    summary = (
        f"Picked step by step: {', '.join(labels)}. {format_money(share, currency)} per person."
    )
    return CustomPackage(
        title=title,
        summary=summary[:4000],
        items=items,
        total_minor=total,
        per_person_minor=share,
        over_budget=is_over_budget(share, budget_per_person_minor),
    )
