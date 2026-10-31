"""The scenario vocabulary: a trip brief, the people and a list of small, readable steps.

Scenarios are plain Python (`app/harness/scenarios/<name>.py`, each exporting `SCENARIO`), so a
typo is a type error rather than a silently ignored YAML key. Members are referred to by their
full display name; bookings by kind (`train` / `stay` / `activity`, or `all`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import date
from typing import Literal

from app.core.domain.trips import BookingStatus, ContributionStatus, EventKind, TripStatus

type KindName = Literal["train", "stay", "activity"]
type KindSelector = Literal["train", "stay", "activity", "all"]
# What the scripted agent does when it is started for a booking of a given kind.
type ScriptedOutcome = Literal["done", "handoff", "stuck", "error"]
type ShareTrend = Literal["higher", "lower", "equal"]


@dataclass(frozen=True, slots=True)
class Brief:
    title: str
    origin: str
    brief: str
    date_from: date
    date_to: date
    group_size: int
    budget_per_person_minor: int | None = None
    # Station names for the live PKP Intercity search (`--live-search`) only.
    origin_station: str = "Warszawa Centralna"
    destination_station: str = "Praha"


# ---- actions ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeneratePackages:
    """The organizer asks for packages; the research runs and is drained."""


@dataclass(frozen=True, slots=True)
class CastVotes:
    """One package index for everyone, or `{member: index}` (members left out do not vote)."""

    picks: int | Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CloseVoting:
    pass


@dataclass(frozen=True, slots=True)
class Pay:
    """`members=None` means everyone who currently owes money (minus `everyone_except`)."""

    members: Sequence[str] | None = None
    everyone_except: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class StartBookings:
    """Starts every PENDING / FAILED booking of the kind and waits for the agents to settle."""

    kind: KindSelector = "all"


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """What the scripted agent does on its NEXT start for each kind (default: `done`)."""

    train: ScriptedOutcome | None = None
    stay: ScriptedOutcome | None = None
    activity: ScriptedOutcome | None = None


@dataclass(frozen=True, slots=True)
class Approve:
    kind: KindSelector = "all"
    approved: bool = True


@dataclass(frozen=True, slots=True)
class Disrupt:
    delay_minutes: int
    price_change_percent: float


@dataclass(frozen=True, slots=True)
class SupplierPriceChange:
    """The supplier's live price moves by `percent` before the next start (one-shot)."""

    kind: KindName
    percent: float


@dataclass(frozen=True, slots=True)
class Leave:
    member: str


@dataclass(frozen=True, slots=True)
class CompleteManually:
    kind: KindName
    ref: str


# ---- expectations -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpectStatus:
    status: TripStatus


@dataclass(frozen=True, slots=True)
class ExpectBookingStatus:
    """Every live (not cancelled) booking of the kind is in `status`."""

    kind: KindName
    status: BookingStatus


@dataclass(frozen=True, slots=True)
class ExpectShares:
    """`status` for everyone, `per_member` overrides, `members` = how many shares count
    (non-zero), `vs_initial` = each share compared with the split at voting close."""

    status: ContributionStatus | None = None
    per_member: Mapping[str, ContributionStatus] = field(default_factory=dict)
    members: int | None = None
    vs_initial: ShareTrend | None = None


@dataclass(frozen=True, slots=True)
class ExpectEvent:
    """A plain string is allowed for event kinds that have not landed yet."""

    kind: EventKind | str


@dataclass(frozen=True, slots=True)
class ExpectWinner:
    """The package at `index` won and the trip total is its price."""

    index: int


@dataclass(frozen=True, slots=True)
class ExpectWithinBudget:
    """Every package costs at most the brief's per-person budget."""


@dataclass(frozen=True, slots=True)
class ExpectError:
    """The NEXT step must fail with this domain error code (e.g. `trip_not_ready`)."""

    code: str


type Action = (
    GeneratePackages
    | CastVotes
    | CloseVoting
    | Pay
    | StartBookings
    | AgentOutcome
    | Approve
    | Disrupt
    | SupplierPriceChange
    | Leave
    | CompleteManually
)
type Expectation = (
    ExpectStatus
    | ExpectBookingStatus
    | ExpectShares
    | ExpectEvent
    | ExpectWinner
    | ExpectWithinBudget
    | ExpectError
)
type Step = Action | Expectation

EXPECTATIONS = (
    ExpectStatus,
    ExpectBookingStatus,
    ExpectShares,
    ExpectEvent,
    ExpectWinner,
    ExpectWithinBudget,
    ExpectError,
)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    title: str
    brief: Brief
    organizer: str
    friends: tuple[str, ...]
    steps: tuple[Step, ...]
    description: str = ""
    # Invariant name -> why its violation is expected in this scenario (reported, not failed).
    known_violations: Mapping[str, str] = field(default_factory=dict)
    # The scenario documents a product bug: failing is expected (pytest xfail, strict=False).
    xfail: str | None = None

    @property
    def members(self) -> tuple[str, ...]:
        return (self.organizer, *self.friends)


def describe(step: Step) -> str:
    """`Pay(everyone_except=['Kuba Mazur'])` — only the fields that differ from the default."""
    parts = []
    for item in fields(step):
        value = getattr(step, item.name)
        if value in ((), {}, None) and item.name != "picks":
            continue
        if item.name == "approved" and value is True:
            continue
        shown = value.value if isinstance(value, TripStatus | BookingStatus) else value
        if isinstance(shown, EventKind | ContributionStatus):
            shown = shown.value
        if isinstance(shown, tuple | list):
            shown = list(shown)
        if isinstance(shown, Mapping):
            shown = {key: getattr(val, "value", val) for key, val in shown.items()}
        parts.append(f"{item.name}={shown!r}")
    return f"{type(step).__name__}({', '.join(parts)})"
