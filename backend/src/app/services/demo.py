"""Demo helpers: a six-person trip driven from one browser. Exposed on dev/test only — the
route layer refuses them elsewhere.

Fake members are real `User` documents that can never sign in: the password hash is of a
random secret nobody keeps, and the account is inactive. They are recognisable by the
reserved `.invalid` email domain (RFC 2606), which can never belong to a real person.
"""

import secrets

from beanie import PydanticObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import EventActor, EventKind, TripStatus
from app.core.security import hash_password
from app.db.client import Database
from app.db.identifiers import identifier_of, to_object_id
from app.models.auth import User
from app.models.trips import TripMember
from app.repositories.auth import UserRepository
from app.repositories.trips import (
    EventRepository,
    MemberRepository,
    ProposalRepository,
    TripRepository,
    VoteRepository,
)
from app.services.contributions import ContributionService
from app.services.trip_access import TripAccess, load_access, require_organizer, require_status
from app.services.trips import JOINABLE_STATUSES

DEMO_EMAIL_DOMAIN = "demo.tripsplit.invalid"
DEMO_NAMES = (
    "Ola",
    "Kuba",
    "Marta",
    "Bartek",
    "Zosia",
    "Piotr",
    "Kasia",
    "Tomek",
    "Ania",
    "Michał",
)


class DemoService:
    def __init__(self, db: Database, contributions: ContributionService) -> None:
        self.db = db
        self.contribution_service = contributions
        self.trips = TripRepository()
        self.members = MemberRepository()
        self.users = UserRepository()
        self.proposals = ProposalRepository()
        self.votes = VoteRepository()
        self.events = EventRepository()

    async def _access(self, trip_id: str, user_id: str) -> Result[TripAccess, TripError]:
        return await load_access(trip_id, user_id, trips=self.trips, members=self.members)

    async def seed_members(self, trip_id: str, user_id: str, count: int) -> Result[int, TripError]:
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        error = require_organizer(access.value) or require_status(access.value, *JOINABLE_STATUSES)
        if error is not None:
            return Err(error)
        trip_oid = identifier_of(access.value.trip)
        taken = {member.display_name for member in await self.members.for_trip(trip_oid)}
        names = [name for name in DEMO_NAMES if name not in taken][:count]
        # Hashed once per batch, before the transaction (the callback must be replayable).
        unusable_hash = await hash_password(secrets.token_urlsafe(32))

        async def write(session: AsyncClientSession) -> None:
            for name in names:
                user = await self.users.add(
                    User(
                        email=f"{name.lower()}-{secrets.token_hex(4)}@{DEMO_EMAIL_DOMAIN}",
                        password_hash=unusable_hash,
                        is_active=False,
                    ),
                    session=session,
                )
                await self.members.add(
                    TripMember(trip_id=trip_oid, user_id=identifier_of(user), display_name=name),
                    session=session,
                )
                await self.events.add(
                    trip_oid,
                    EventKind.MEMBER_JOINED,
                    EventActor.MEMBER,
                    f"{name} joined the trip.",
                    actor_user_id=identifier_of(user),
                    session=session,
                )

        await self.db.in_transaction(write)
        return Ok(len(names))

    async def vote_all(
        self, trip_id: str, user_id: str, proposal_id: str
    ) -> Result[int, TripError]:
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        if (error := require_status(access.value, TripStatus.VOTING)) is not None:
            return Err(error)
        trip_oid = identifier_of(access.value.trip)
        proposal_oid = to_object_id(proposal_id)
        proposal = await self.proposals.get(proposal_oid) if proposal_oid is not None else None
        if proposal is None or proposal.trip_id != trip_oid:
            return Err(TripError.PROPOSAL_NOT_FOUND)

        fake = await self._fake_members(trip_oid)
        for member in fake:
            await self.votes.upsert(trip_oid, member.user_id, identifier_of(proposal))
            await self.events.add(
                trip_oid,
                EventKind.VOTE_CAST,
                EventActor.MEMBER,
                f"{member.display_name} voted for “{proposal.title}”.",
                payload={"proposal_id": proposal_id},
                actor_user_id=member.user_id,
            )
        return Ok(len(fake))

    async def pay_all(self, trip_id: str, user_id: str) -> Result[int, TripError]:
        """Pays every outstanding share except the caller's — so the caller makes the last,
        decisive payment on stage."""
        access = await self._access(trip_id, user_id)
        if not isinstance(access, Ok):
            return access
        if (error := require_status(access.value, TripStatus.PAYING)) is not None:
            return Err(error)
        trip, me = access.value.trip, access.value.member
        paid = 0
        for member in await self.members.for_trip(identifier_of(trip)):
            if member.user_id == me.user_id:
                continue
            result = await self.contribution_service.pay_for(trip, member)
            if isinstance(result, Ok):
                paid += 1
        return Ok(paid)

    async def _fake_members(self, trip_id: PydanticObjectId) -> list[TripMember]:
        fake: list[TripMember] = []
        for member in await self.members.for_trip(trip_id):
            user = await self.users.get_by_id(member.user_id)
            if user is not None and user.email.endswith(f"@{DEMO_EMAIL_DOMAIN}"):
                fake.append(member)
        return fake
