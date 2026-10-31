"""The package-research port: a trip brief in, three purchasable packages out.

Plain dataclasses on both sides — no Beanie, no provider SDK — so the service that stores the
result does not care whether a fixture or an LLM with web search produced it.
"""

from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol

from app.core.domain.trips import BookingKind, TransportMode
from app.suppliers.ports import Segment

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
    # Where to; empty = read from the title and brief.
    destination: str = ""
    # The trip's mode preference; None = any (the brief may still say "fly there, train back").
    transport_mode: TransportMode | None = None

    @property
    def nights(self) -> int:
        return max((self.date_to - self.date_from).days, 1)


@dataclass(frozen=True, slots=True)
class PackageItemPlan:
    kind: BookingKind
    title: str
    supplier: str  # who sells it, for people
    supplier_url: str
    # Minor units (grosze) for the WHOLE group.
    price_minor: int
    details: str = ""
    starts_at: datetime | None = None
    mode: TransportMode | None = None
    # The supplier plugin's offer this item buys; empty for an item from outside the registry.
    supplier_id: str = ""
    offer_ref: str = ""
    segments: tuple[Segment, ...] = ()
    refundable: bool = False
    supplier_data: Mapping[str, Any] = field(default_factory=dict)


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


class SearchOutcome(StrEnum):
    OK = "ok"
    EMPTY = "empty"  # the supplier answered, but with nothing
    CACHED = "cached"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class SupplierProgress:
    """One supplier search finished during a research (for a live "suppliers ticked off")."""

    supplier_id: str
    supplier: str  # display name
    kind: BookingKind
    outcome: SearchOutcome
    offers: int
    seconds: float


type ProgressSink = Callable[[SupplierProgress], Awaitable[None]]

# Set by whoever runs a research and wants per-supplier progress (ProposalService -> the feed);
# a context variable, so every `PackageResearcher` wrapper passes it through untouched.
research_progress: ContextVar[ProgressSink | None] = ContextVar("research_progress", default=None)
