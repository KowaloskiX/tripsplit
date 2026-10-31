"""The scenario vocabulary: the suppliers, a trip brief, the people and a list of small,
readable steps.

Scenarios are plain Python (`app/harness/scenarios/<name>.py`, each exporting `SCENARIO`), so a
typo is a type error rather than a silently ignored YAML key. Members are referred to by their
full display name. Bookings are addressed generically — by kind (`transport` / `stay` /
`activity`), by transport mode (`rail` / `flight` / `bus` / `ferry`) or `all` — never by a
supplier's name. Suppliers are plugin ids (`sim_flight`, `sim_rail`, ...) with an optional
scripted `SimBehaviour`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import date
from typing import Literal

from app.core.domain.trips import (
    BookingStatus,
    ContributionStatus,
    EventKind,
    TransportMode,
    TripStatus,
)
from app.suppliers.sim import SimBehaviour

type Target = Literal["transport", "rail", "flight", "bus", "ferry", "stay", "activity"]
type TargetSelector = Target | Literal["all"]
# What the scripted agent does when it is started for a booking of a given target.
type ScriptedOutcome = Literal["done", "handoff", "stuck", "error"]
type ShareTrend = Literal["higher", "lower", "equal"]


@dataclass(frozen=True, slots=True)
class SupplierSpec:
    """A supplier plugin for the scenario: its id and what it does (simulators only). The
    behaviour is copied for every run, so a one-shot never leaks into the next scenario."""

    id: str
    behaviour: SimBehaviour | None = None


# The rail-flavoured trip most scenarios share: rail + a stay site + activities, all bought
# by the agent like the original Prague demo.
RAIL_TRIP: tuple[SupplierSpec, ...] = (
    SupplierSpec("sim_rail"),
    SupplierSpec("sim_stay_site"),
    SupplierSpec("sim_activity"),
)


@dataclass(frozen=True, slots=True)
class Brief:
    title: str
    origin: str
    brief: str
    date_from: date
    date_to: date
    group_size: int
    budget_per_person_minor: int | None = None
    destination: str = ""
    transport_mode: TransportMode | None = None


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
    """`members=None` means everyone who currently owes money (minus `everyone_except`).
    Shares are paid from wallets: `fund_wallets` first tops each payer's wallet up (dummy
    BLIK) by exactly what it misses; `False` pays from whatever the wallet holds."""

    members: Sequence[str] | None = None
    everyone_except: Sequence[str] = ()
    fund_wallets: bool = True


@dataclass(frozen=True, slots=True)
class TopUp:
    """`member` tops their wallet up through the dummy rails (BLIK `000000` is declined)."""

    member: str
    amount_minor: int
    blik_code: str = "123456"


@dataclass(frozen=True, slots=True)
class TopUpAndPay:
    """The "Pay my share" sheet: top up exactly the shortfall by BLIK, then pay the share."""

    members: Sequence[str]
    blik_code: str = "123456"


@dataclass(frozen=True, slots=True)
class StartBookings:
    """Starts every PENDING / FAILED booking of the target and waits for the agents to settle.
    `top_up_on_price_change`: a `price_changed` answer (a live supplier re-priced) is met the
    way a group would — everyone tops up, and the purchase is started once more."""

    target: TargetSelector = "all"
    top_up_on_price_change: bool = False


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """What the scripted agent does on every later start for the target (default: `done`)."""

    target: Target
    outcome: ScriptedOutcome


@dataclass(frozen=True, slots=True)
class Approve:
    target: TargetSelector = "all"
    approved: bool = True


@dataclass(frozen=True, slots=True)
class Disrupt:
    """The demo disruption endpoint: a delay on the first bought transport."""

    delay_minutes: int
    price_change_percent: float


@dataclass(frozen=True, slots=True)
class SupplierPriceChange:
    """The target's suppliers ask `percent` more at their next quote or hold (one-shot)."""

    target: Target
    percent: float


@dataclass(frozen=True, slots=True)
class SupplierDisruption:
    """The target's suppliers report a disruption at the next status check: a cancellation
    (or a delay) with a replacement on another carrier at `replacement_percent`."""

    target: Target
    cancelled: bool = True
    delay_minutes: int = 0
    replacement_percent: float = 0.0


@dataclass(frozen=True, slots=True)
class CheckDisruptions:
    """The organizer asks the suppliers about the bought bookings (`check_disruptions`)."""


@dataclass(frozen=True, slots=True)
class AdvanceClock:
    """Time passes for the trip flow and every supplier (holds and quotes can lapse)."""

    hours: float


@dataclass(frozen=True, slots=True)
class EnterTravellerDetails:
    """These members enter their traveller details (date of birth, nationality, passport)."""

    members: Sequence[str]


@dataclass(frozen=True, slots=True)
class Leave:
    member: str


@dataclass(frozen=True, slots=True)
class CompleteManually:
    target: Target
    ref: str


# ---- expectations -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpectStatus:
    status: TripStatus


@dataclass(frozen=True, slots=True)
class ExpectBookingStatus:
    """Every live (not cancelled) booking of the target is in `status`; `count` = how many live
    bookings of the target there must be (rail for six at a cap of five is two purchases)."""

    target: Target
    status: BookingStatus
    count: int | None = None


@dataclass(frozen=True, slots=True)
class ExpectPurchases:
    """The live bookings of the target carry exactly these party sizes, in order (8 at a cap
    of 9 -> (8,); at a cap of 5 -> (4, 4))."""

    target: Target
    sizes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ExpectHold:
    """Every live booking of the target holds its price right now (`live`), or holds none
    that is still valid (`live=False`)."""

    target: Target
    live: bool = True


@dataclass(frozen=True, slots=True)
class ExpectAgentRuns:
    """How many agent runs the target's bookings needed (0 for an API purchase)."""

    target: Target
    count: int


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
class ExpectBudget:
    """Exactly `within` packages cost at most the brief's per-person budget, and every
    package's `over_budget` flag says so correctly."""

    within: int


@dataclass(frozen=True, slots=True)
class ExpectAgentMessage:
    """The agent said something containing `text` (case-insensitive) in the feed."""

    text: str


@dataclass(frozen=True, slots=True)
class ExpectWallet:
    """`member`'s wallet holds `balance_minor`; `refunded` = a trip refund landed in it."""

    member: str
    balance_minor: int | None = None
    refunded: bool | None = None


@dataclass(frozen=True, slots=True)
class ExpectPot:
    """The trip pot (collected - spent on confirmed bookings - refunded) holds `held_minor`."""

    held_minor: int


@dataclass(frozen=True, slots=True)
class ExpectError:
    """The NEXT step must fail with this domain error code (e.g. `trip_not_ready`)."""

    code: str


type Action = (
    GeneratePackages
    | CastVotes
    | CloseVoting
    | Pay
    | TopUp
    | TopUpAndPay
    | StartBookings
    | AgentOutcome
    | Approve
    | Disrupt
    | SupplierPriceChange
    | SupplierDisruption
    | CheckDisruptions
    | AdvanceClock
    | EnterTravellerDetails
    | Leave
    | CompleteManually
)
type Expectation = (
    ExpectStatus
    | ExpectBookingStatus
    | ExpectPurchases
    | ExpectHold
    | ExpectAgentRuns
    | ExpectShares
    | ExpectEvent
    | ExpectWinner
    | ExpectBudget
    | ExpectAgentMessage
    | ExpectWallet
    | ExpectPot
    | ExpectError
)
type Step = Action | Expectation

EXPECTATIONS = (
    ExpectStatus,
    ExpectBookingStatus,
    ExpectPurchases,
    ExpectHold,
    ExpectAgentRuns,
    ExpectShares,
    ExpectEvent,
    ExpectWinner,
    ExpectBudget,
    ExpectAgentMessage,
    ExpectWallet,
    ExpectPot,
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
    suppliers: tuple[SupplierSpec, ...] = RAIL_TRIP
    # Members who have NOT entered traveller details at the start; everyone else has.
    without_traveller_details: tuple[str, ...] = ()
    # Invariant name -> why its violation is expected in this scenario (reported, not failed).
    known_violations: Mapping[str, str] = field(default_factory=dict)
    # The scenario documents a product bug: failing is expected (pytest xfail, strict=False).
    xfail: str | None = None
    # Talks to the real LiteAPI SANDBOX: runs only with `--live-stays`, pending otherwise
    # (the fast run and pytest never reach the network).
    live_stays_only: bool = False
    # Talks to the real Duffel TEST API: runs only with `--live-flights`, pending otherwise
    # (the fast run and pytest never reach the network).
    live_flights_only: bool = False
    # PRICE_TOLERANCE_PERCENT for the scenario's trip flow (0 = any re-quote re-splits).
    price_tolerance_percent: float = 0.0
    # HOLDS for the scenario's trip flow: off by default like the app; scenarios about holds
    # turn them on explicitly.
    holds: bool = False

    @property
    def members(self) -> tuple[str, ...]:
        return (self.organizer, *self.friends)


def describe(step: Step) -> str:
    """`Pay(everyone_except=['Kuba Mazur'])` — only the fields that differ from the default."""
    parts = []
    for item in fields(step):
        value = getattr(step, item.name)
        if item.name == "blik_code" and value == "123456":
            continue
        if value in ((), {}, None) and item.name != "picks":
            continue
        if item.name in ("approved", "fund_wallets") and value is True:
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
