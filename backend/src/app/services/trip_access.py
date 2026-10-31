"""The trip access rule, in one place: only members see a trip, and to everyone else it does
not exist.

Trips are not tenant-owned (friends from different organizations share one), so membership is
the whole isolation boundary. A non-member gets `NOT_FOUND`, never "forbidden" — a 403 would
confirm that the identifier is a real trip.
"""

from dataclasses import dataclass

from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.core.domain.trips import MemberRole, TripStatus
from app.db.identifiers import to_object_id
from app.models.trips import Trip, TripMember
from app.repositories.trips import MemberRepository, TripRepository


@dataclass(frozen=True, slots=True)
class TripAccess:
    trip: Trip
    member: TripMember

    @property
    def is_organizer(self) -> bool:
        return self.member.role is MemberRole.ORGANIZER


async def load_access(
    trip_id: str,
    user_id: str,
    *,
    trips: TripRepository,
    members: MemberRepository,
) -> Result[TripAccess, TripError]:
    trip_oid, user_oid = to_object_id(trip_id), to_object_id(user_id)
    if trip_oid is None or user_oid is None:
        return Err(TripError.NOT_FOUND)
    member = await members.get(trip_oid, user_oid)
    if member is None:
        return Err(TripError.NOT_FOUND)
    trip = await trips.get(trip_oid)
    if trip is None:
        return Err(TripError.NOT_FOUND)
    return Ok(TripAccess(trip=trip, member=member))


def require_status(access: TripAccess, *allowed: TripStatus) -> TripError | None:
    return None if access.trip.status in allowed else TripError.INVALID_STATE


def require_organizer(access: TripAccess) -> TripError | None:
    return None if access.is_organizer else TripError.NOT_ORGANIZER
