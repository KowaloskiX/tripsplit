"""What the trip services return: plain read models with string identifiers.

A service never returns a Beanie document (it carries internal fields and `ObjectId`s) nor an
API schema (HTTP must not leak down). These dataclasses sit in between; the routes validate
them into response schemas with `from_attributes`.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from beanie import PydanticObjectId

from app.core.domain.bookings import refund_minor
from app.core.domain.suppliers import TravellerField
from app.core.domain.trips import (
    BookingKind,
    ContributionStatus,
    EventActor,
    EventKind,
    MemberRole,
    TransportMode,
    TripStatus,
)
from app.core.domain.trust import OfferLink, Provenance
from app.db.identifiers import identifier_of, to_text
from app.models.trips import Contribution, Proposal, Trip, TripEvent, TripMember
from app.models.trust import TrustLink, TrustProvenance
from app.services.wallet import PotView


@dataclass(frozen=True, slots=True)
class TripView:
    id: str
    title: str
    origin: str
    brief: str
    date_from: date
    date_to: date
    group_size: int
    budget_per_person_minor: int | None
    currency: str
    destination: str
    transport_mode: TransportMode | None
    earliest_departure_hour: int | None
    max_transfers: int | None
    status: TripStatus
    organizer_id: str
    chosen_proposal_id: str | None
    total_minor: int
    pay_by: datetime | None = None


@dataclass(frozen=True, slots=True)
class TripSummaryView:
    trip: TripView
    my_role: MemberRole


@dataclass(frozen=True, slots=True)
class MemberView:
    user_id: str
    display_name: str
    role: MemberRole
    # Traveller details the trip's suppliers need that this member has not entered — field
    # names only, never values. Empty = complete.
    traveller_details_missing: tuple[TravellerField, ...] = ()

    @property
    def traveller_details_complete(self) -> bool:
        return not self.traveller_details_missing


@dataclass(frozen=True, slots=True)
class SegmentView:
    carrier: str
    number: str
    origin: str
    destination: str
    departs_at: datetime
    arrives_at: datetime


@dataclass(frozen=True, slots=True)
class ProposalItemView:
    kind: BookingKind
    mode: TransportMode | None
    title: str
    supplier: str
    supplier_url: str
    price_minor: int
    details: str
    starts_at: datetime | None
    segments: tuple[SegmentView, ...]
    links: tuple[OfferLink, ...] = ()
    images: tuple[str, ...] = ()
    provenance: Provenance | None = None


@dataclass(frozen=True, slots=True)
class ProposalView:
    id: str
    title: str
    summary: str
    items: tuple[ProposalItemView, ...]
    total_minor: int
    per_person_minor: int
    over_budget: bool
    votes: int
    voted_by_me: bool
    chosen: bool


@dataclass(frozen=True, slots=True)
class ContributionView:
    user_id: str
    display_name: str
    amount_minor: int
    paid_minor: int
    outstanding_minor: int
    # Paid beyond the current share (REFUND_DUE): what the member gets back.
    refund_minor: int
    status: ContributionStatus


@dataclass(frozen=True, slots=True)
class RoomView:
    """Everything the trip room renders, in one response."""

    trip: TripView
    invite_code: str
    my_user_id: str
    my_role: MemberRole
    members: tuple[MemberView, ...]
    proposals: tuple[ProposalView, ...]
    my_vote_proposal_id: str | None
    contributions: tuple[ContributionView, ...]
    my_contribution: ContributionView | None
    paid_count: int
    # The trip wallet: collected from members' wallets, spent on bookings, refunded, held.
    pot: PotView


@dataclass(frozen=True, slots=True)
class EventView:
    id: str
    kind: EventKind
    actor: EventActor
    message: str
    payload: dict[str, Any]
    actor_user_id: str | None
    actor_name: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TripStatusView:
    trip_id: str
    status: TripStatus


def _optional_text(identifier: PydanticObjectId | None) -> str | None:
    return to_text(identifier) if identifier is not None else None


def trip_view(trip: Trip) -> TripView:
    return TripView(
        id=to_text(identifier_of(trip)),
        title=trip.title,
        origin=trip.origin,
        brief=trip.brief,
        date_from=trip.date_from,
        date_to=trip.date_to,
        group_size=trip.group_size,
        budget_per_person_minor=trip.budget_per_person_minor,
        currency=trip.currency,
        destination=trip.destination,
        transport_mode=trip.transport_mode,
        earliest_departure_hour=trip.earliest_departure_hour,
        max_transfers=trip.max_transfers,
        status=trip.status,
        organizer_id=to_text(trip.organizer_id),
        chosen_proposal_id=_optional_text(trip.chosen_proposal_id),
        total_minor=trip.total_minor,
        pay_by=trip.pay_by,
    )


def member_view(member: TripMember, missing: frozenset[TravellerField] = frozenset()) -> MemberView:
    return MemberView(
        user_id=to_text(member.user_id),
        display_name=member.display_name,
        role=member.role,
        traveller_details_missing=tuple(sorted(missing)),
    )


def proposal_view(
    proposal: Proposal, *, votes: int, voted_by_me: bool, chosen: bool
) -> ProposalView:
    return ProposalView(
        id=to_text(identifier_of(proposal)),
        title=proposal.title,
        summary=proposal.summary,
        items=tuple(
            ProposalItemView(
                kind=item.kind,
                mode=item.mode,
                title=item.title,
                supplier=item.supplier,
                supplier_url=item.supplier_url,
                price_minor=item.price_minor,
                details=item.details,
                starts_at=item.starts_at,
                segments=tuple(
                    SegmentView(
                        carrier=segment.carrier,
                        number=segment.number,
                        origin=segment.origin,
                        destination=segment.destination,
                        departs_at=segment.departs_at,
                        arrives_at=segment.arrives_at,
                    )
                    for segment in item.segments
                ),
                links=links_view(item.links),
                images=tuple(item.images),
                provenance=provenance_view(item.provenance),
            )
            for item in proposal.items
        ),
        total_minor=proposal.total_minor,
        per_person_minor=proposal.per_person_minor,
        over_budget=proposal.over_budget,
        votes=votes,
        voted_by_me=voted_by_me,
        chosen=chosen,
    )


def links_view(links: list[TrustLink]) -> tuple[OfferLink, ...]:
    return tuple(OfferLink(label=link.label, url=link.url, kind=link.kind) for link in links)


def provenance_view(provenance: TrustProvenance | None) -> Provenance | None:
    if provenance is None:
        return None
    return Provenance(
        source=provenance.source, supplier=provenance.supplier, checked_at=provenance.checked_at
    )


def contribution_view(contribution: Contribution, display_name: str) -> ContributionView:
    return ContributionView(
        user_id=to_text(contribution.user_id),
        display_name=display_name,
        amount_minor=contribution.amount_minor,
        paid_minor=contribution.paid_minor,
        outstanding_minor=max(contribution.amount_minor - contribution.paid_minor, 0),
        refund_minor=refund_minor(contribution.amount_minor, contribution.paid_minor),
        status=contribution.status,
    )


def event_view(event: TripEvent, names: dict[PydanticObjectId, str]) -> EventView:
    return EventView(
        id=to_text(identifier_of(event)),
        kind=event.kind,
        actor=event.actor,
        message=event.message,
        payload=event.payload,
        actor_user_id=_optional_text(event.actor_user_id),
        actor_name=names.get(event.actor_user_id) if event.actor_user_id is not None else None,
        created_at=event.created_at,
    )
