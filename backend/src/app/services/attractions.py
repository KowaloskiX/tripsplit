"""Attraction voting: what the group wants to see at the destination. No HTTP here.

After the package vote closes (while the group pays — it never blocks Rule #1), every member
can open a ranked list of attraction candidates and toggle votes on them. The candidates come
from EVERY enabled activity supplier (a ticket shop, an open-data catalogue of sights), read
through the supplier port only; their `supplier_data` keys differ per supplier, so they are
read defensively (`app.core.domain.attractions`). The list is snapshotted at the first request,
so it does not reshuffle while people vote.
"""

import asyncio
import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from beanie import PydanticObjectId

from app.ai.places import destination_of
from app.core.domain.attractions import (
    coordinate,
    first_of,
    http_url,
    kind_of,
    parse_hours,
    text_of,
    visit_minutes,
    whole,
)
from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import (
    BookingKind,
    EventActor,
    EventKind,
    SupplierChannel,
    TripStatus,
)
from app.db.client import Database
from app.db.identifiers import identifier_of, to_text
from app.models.itinerary import AttractionCandidate, TripAttractions
from app.models.trips import Trip, TripMember
from app.repositories.itinerary import AttractionRepository
from app.repositories.trips import (
    EventRepository,
    MemberRepository,
    ProposalRepository,
    TripRepository,
)
from app.services.trip_access import TripAccess, load_access
from app.suppliers.ports import Offer, SearchRequest, SupplierAdapter
from app.suppliers.registry import SupplierRegistry

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 12
SEARCH_TIMEOUT_S = 15.0
# The package is chosen: from here on the group may plan what to do there.
AFTER_THE_VOTE = frozenset(
    {
        TripStatus.PAYING,
        TripStatus.BOOKING,
        TripStatus.BOOKED,
        TripStatus.DISRUPTED,
        TripStatus.REBOOKING,
        TripStatus.DONE,
    }
)
VOTING_OPEN = AFTER_THE_VOTE - {TripStatus.DONE}


@dataclass(frozen=True, slots=True)
class Voter:
    user_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class AttractionView:
    attraction_id: str
    title: str
    kind: str
    image_url: str
    website: str
    lat: float | None
    lon: float | None
    opens: str | None
    closes: str | None
    duration_minutes: int
    price_per_person_minor: int | None
    currency: str
    bookable: bool
    provenance: str
    rank: int
    voters: list[Voter]
    voted_by_me: bool

    @property
    def votes(self) -> int:
        return len(self.voters)


@dataclass(frozen=True, slots=True)
class AttractionsView:
    trip_id: str
    destination: str
    members: int
    # A plan takes what at least this many members want first (half the group, rounded up).
    majority: int
    attractions: list[AttractionView]


def attraction_id_of(supplier_id: str, offer_ref: str) -> str:
    """Short, URL-safe and stable for one offer."""
    return "a" + hashlib.sha256(f"{supplier_id}|{offer_ref}".encode()).hexdigest()[:12]


def candidate_of(
    adapter: SupplierAdapter, offer: Offer, party: int, index: int
) -> AttractionCandidate:
    """One supplier offer as a candidate, every `supplier_data` key read defensively."""
    data = offer.supplier_data
    kind = kind_of(first_of(data, "kind", "category", "type"), offer.title)
    hours = parse_hours(first_of(data, "opening_hours", "hours", "open_hours"))
    per_person = whole(first_of(data, "price_per_person_minor"))
    if per_person is None and offer.price_minor > 0 and party > 0:
        per_person = -(-offer.price_minor // party)
    priced = per_person is not None and per_person > 0
    rank = whole(first_of(data, "rank"))
    if rank is None and (score := whole(first_of(data, "score"))) is not None:
        rank = -score
    purchasable = adapter.capabilities.channel is not SupplierChannel.MANUAL
    return AttractionCandidate(
        attraction_id=attraction_id_of(adapter.id, offer.offer_ref),
        title=offer.title[:200],
        kind=kind,
        image_url=http_url(text_of(data, "image_url", "image", "thumbnail")),
        website=http_url(text_of(data, "website", "url", "wikipedia_url"))
        or (http_url(offer.purchase_url) if not purchasable else ""),
        lat=coordinate(first_of(data, "lat", "latitude"), 90),
        lon=coordinate(first_of(data, "lon", "lng", "longitude"), 180),
        opens=f"{hours.opens:%H:%M}" if hours else None,
        closes=f"{hours.closes:%H:%M}" if hours else None,
        duration_minutes=visit_minutes(first_of(data, "duration_minutes", "duration"), kind),
        price_per_person_minor=per_person if priced else None,
        currency=offer.currency,
        bookable=purchasable and priced and data.get("bookable") is not False,
        provenance=text_of(data, "provenance", "source", limit=200) or adapter.display_name,
        rank=rank if rank is not None else index,
        supplier_id=adapter.id,
        supplier_name=offer.seller[:200],
        offer_ref=offer.offer_ref,
        purchase_url=offer.purchase_url,
        supplier_data=dict(data),
    )


def rank_candidates(
    found: Sequence[tuple[int, AttractionCandidate]], limit: int = MAX_CANDIDATES
) -> list[AttractionCandidate]:
    """Best first across suppliers: the supplier's own rank, then supplier order; one
    candidate per title (two suppliers knowing the same museum)."""
    seen: set[str] = set()
    ranked: list[AttractionCandidate] = []
    for _, candidate in sorted(found, key=lambda pair: (pair[1].rank, pair[0])):
        key = candidate.title.casefold()
        if key in seen:
            continue
        seen.add(key)
        ranked.append(candidate)
    return ranked[:limit]


class AttractionService:
    def __init__(
        self,
        db: Database,
        *,
        suppliers: SupplierRegistry | None = None,
        search_timeout_s: float = SEARCH_TIMEOUT_S,
    ) -> None:
        self.db = db
        self.suppliers = suppliers if suppliers is not None else SupplierRegistry()
        self.search_timeout_s = search_timeout_s
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.proposals = ProposalRepository()
        self.events = EventRepository()
        self.attractions = AttractionRepository()

    async def _access(self, trip_id: str, user_id: str) -> Result[TripAccess, TripError]:
        return await load_access(trip_id, user_id, trips=self.trips, members=self.members)

    # ---- reads ----------------------------------------------------------------------------

    async def overview(self, trip_id: str, user_id: str) -> Result[AttractionsView, TripError]:
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip = access.value.trip
        if trip.status not in AFTER_THE_VOTE:
            return Err(TripError.INVALID_STATE)
        stored = await self.snapshot(trip)
        members = await self.members.for_trip(identifier_of(trip))
        return Ok(view_of(trip, stored, members, access.value.member.user_id))

    async def snapshot(self, trip: Trip) -> TripAttractions:
        """The trip's candidates; searched and stored at the first request."""
        trip_oid = identifier_of(trip)
        stored = await self.attractions.get(trip_oid)
        if stored is not None:
            return stored
        destination = destination_of(trip.destination, f"{trip.title} {trip.brief}")
        members = await self.members.for_trip(trip_oid)
        candidates = await self._search(trip, destination, max(len(members), 1))
        return await self.attractions.snapshot(trip_oid, destination, candidates)

    async def _search(self, trip: Trip, destination: str, party: int) -> list[AttractionCandidate]:
        request = SearchRequest(
            origin=trip.origin,
            destination=destination,
            depart_date=trip.date_from,
            return_date=trip.date_to,
            party_size=party,
            currency=trip.currency,
        )
        adapters = self.suppliers.of_kind(BookingKind.ACTIVITY)
        answers = await asyncio.gather(*(self._ask(adapter, request) for adapter in adapters))
        in_package = await self._package_offer_refs(trip)
        found = [
            (order, candidate_of(adapter, offer, party, index))
            for order, (adapter, offers) in enumerate(zip(adapters, answers, strict=True))
            for index, offer in enumerate(offers)
            if offer.offer_ref not in in_package
        ]
        return rank_candidates(found)

    async def _ask(self, adapter: SupplierAdapter, request: SearchRequest) -> list[Offer]:
        """One supplier's attractions; [] when it fails or is too slow — never an exception."""
        try:
            return await asyncio.wait_for(adapter.search(request), self.search_timeout_s)
        except Exception:
            logger.warning("%s: attraction search failed", adapter.id, exc_info=True)
            return []

    async def _package_offer_refs(self, trip: Trip) -> set[str]:
        """Offers the chosen package already buys are not candidates again."""
        if trip.chosen_proposal_id is None:
            return set()
        chosen = await self.proposals.get(trip.chosen_proposal_id)
        return {item.offer_ref for item in chosen.items if item.offer_ref} if chosen else set()

    # ---- votes ----------------------------------------------------------------------------

    async def vote(
        self, trip_id: str, attraction_id: str, user_id: str
    ) -> Result[AttractionsView, TripError]:
        """Toggles the member's vote on one attraction. A new vote is said in the feed."""
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        trip, member = access.value.trip, access.value.member
        if trip.status not in VOTING_OPEN:
            return Err(TripError.INVALID_STATE)
        trip_oid = identifier_of(trip)
        stored = await self.snapshot(trip)
        candidate = next((c for c in stored.candidates if c.attraction_id == attraction_id), None)
        if candidate is None:
            return Err(TripError.ATTRACTION_NOT_FOUND)
        voted = await self.attractions.toggle_vote(trip_oid, attraction_id, member.user_id)
        if voted is None:
            return Err(TripError.ATTRACTION_NOT_FOUND)
        fresh = await self.attractions.get(trip_oid) or stored
        members = await self.members.for_trip(trip_oid)
        view = view_of(trip, fresh, members, member.user_id)
        if voted:
            votes = next(a.votes for a in view.attractions if a.attraction_id == attraction_id)
            await self.events.add(
                trip_oid,
                EventKind.ATTRACTION_VOTED,
                EventActor.MEMBER,
                f"{member.display_name.split()[0]} wants {candidate.title}.",
                payload={"attraction_id": attraction_id, "votes": votes},
                actor_user_id=member.user_id,
            )
        return Ok(view)


def view_of(
    trip: Trip,
    stored: TripAttractions,
    members: list[TripMember],
    viewer: PydanticObjectId,
) -> AttractionsView:
    """Votes of CURRENT members only: somebody who left no longer counts."""
    names = {member.user_id: member.display_name for member in members}
    return AttractionsView(
        trip_id=to_text(identifier_of(trip)),
        destination=stored.destination,
        members=len(members),
        majority=-(-len(members) // 2),
        attractions=[
            AttractionView(
                attraction_id=c.attraction_id,
                title=c.title,
                kind=c.kind.value,
                image_url=c.image_url,
                website=c.website,
                lat=c.lat,
                lon=c.lon,
                opens=c.opens,
                closes=c.closes,
                duration_minutes=c.duration_minutes,
                price_per_person_minor=c.price_per_person_minor,
                currency=c.currency,
                bookable=c.bookable,
                provenance=c.provenance,
                rank=c.rank,
                voters=[Voter(to_text(user), names[user]) for user in c.voter_ids if user in names],
                voted_by_me=viewer in c.voter_ids,
            )
            for c in stored.candidates
        ],
    )
