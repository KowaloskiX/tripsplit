"""The package-research port: a trip brief in, three purchasable packages out.

Plain dataclasses on both sides — no Beanie, no provider SDK — so the service that stores the
result does not care whether a fixture or an LLM with web search produced it.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from app.core.domain.trips import BookingKind

PACKAGES_PER_RESEARCH = 3


@dataclass(frozen=True, slots=True)
class TripBrief:
    title: str
    origin: str
    brief: str
    date_from: date
    date_to: date
    # How many people the prices must cover (the larger of the planned size and the members).
    travellers: int
    budget_per_person_minor: int | None = None
    currency: str = "PLN"

    @property
    def nights(self) -> int:
        return max((self.date_to - self.date_from).days, 1)


@dataclass(frozen=True, slots=True)
class PackageItemPlan:
    kind: BookingKind
    title: str
    supplier: str
    supplier_url: str
    # Minor units (grosze) for the WHOLE group.
    price_minor: int
    details: str = ""
    starts_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PackagePlan:
    title: str
    summary: str
    items: tuple[PackageItemPlan, ...] = field(default_factory=tuple)

    @property
    def total_minor(self) -> int:
        return sum(item.price_minor for item in self.items)


class PackageResearcher(Protocol):
    async def research(self, brief: TripBrief) -> list[PackagePlan]: ...
