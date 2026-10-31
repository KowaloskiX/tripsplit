"""The world a scenario runs in: real services on a throwaway database, the scenario's supplier
plugins, one clock for all of them and a scripted agent.

`--live-search` swaps the simulated rail carrier for the real PKP Intercity adapter (search and
re-quote through a headless browser); `--live-agent` swaps it for the demo rail site and lets
the real agent subprocess buy there. Every other supplier stays simulated.
"""

import contextlib
import copy
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from beanie import PydanticObjectId

from app.agent.launcher import AgentLauncher, SubprocessLauncher
from app.ai.catalog_research import CatalogResearcher
from app.core.background import BackgroundRunner
from app.core.config import Settings
from app.core.domain.result import Ok
from app.db.client import Database
from app.db.identifiers import to_object_id
from app.harness.adapters import HarnessClock, RoutingLauncher, ScriptablePrices, ScriptedLauncher
from app.harness.scenario import Scenario, SupplierSpec
from app.payments.fake import FakePayments
from app.services.auth import AuthService
from app.services.bookings import BookingService
from app.services.contributions import ContributionService
from app.services.proposals import ProposalService
from app.services.supplier_prices import SupplierPrices
from app.services.travellers import TravellerDetailsUpdate, TravellerService
from app.services.trips import NewTrip, TripService
from app.suppliers.demo_rail import DemoRailSupplier
from app.suppliers.intercity import BrowserTransport
from app.suppliers.pkp import LiveSearchLog, PkpIntercitySupplier
from app.suppliers.ports import SupplierAdapter
from app.suppliers.registry import SupplierRegistry
from app.suppliers.sim import SIM_CAPABILITIES, SimBehaviour, sim_supplier

PASSWORD = "harness-correct-horse-battery-staple"
EMAIL_DOMAIN = "harness.tripsplit.invalid"
# backend/: the live agent subprocess runs from here, like in `app.routes.dependencies`.
BACKEND_DIR = Path(__file__).resolve().parents[3]
LIVE_TRAJECTORIES = BACKEND_DIR / "var" / "agent" / "trajectories"
SIM_RAIL = "sim_rail"


@dataclass(frozen=True, slots=True)
class Options:
    out_dir: Path  # this scenario's artifacts: agent runs live under out_dir/agent/runs
    live_search: bool = False
    # Base URL of a backend serving /api/demo-supplier/rail; set => live agent for rail.
    live_agent_base_url: str | None = None
    poll_s: float = 0.02
    max_steps: int = 40


def _email(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}@{EMAIL_DOMAIN}"


def fake_details(index: int) -> TravellerDetailsUpdate:
    """Deterministic, obviously fake traveller details (never printed anywhere)."""
    return TravellerDetailsUpdate(
        date_of_birth=date(1990 + index % 10, 1 + index % 12, 1 + index % 28),
        nationality="PL",
        document_number=f"EH{4_200_000 + index * 7_919:07d}",
        document_expiry=date(2031, 6, 30),
    )


@dataclass
class World:
    db: Database
    settings: Settings
    scenario: Scenario
    options: Options
    runner: BackgroundRunner
    clock: HarnessClock
    suppliers: SupplierRegistry
    # Scriptable behaviour per supplier id (simulators, and real ones wrapped for scripting).
    behaviours: dict[str, SimBehaviour]
    trips: TripService
    proposals: ProposalService
    contributions: ContributionService
    bookings: BookingService
    travellers: TravellerService
    scripted: ScriptedLauncher
    researcher: CatalogResearcher
    launcher: AgentLauncher
    live_search_log: LiveSearchLog | None = None
    resources: contextlib.AsyncExitStack = field(default_factory=contextlib.AsyncExitStack)
    browser: BrowserTransport | None = None
    users: dict[str, str] = field(default_factory=dict)  # display name -> user id
    trip_id: str = ""

    @property
    def organizer_id(self) -> str:
        return self.users[self.scenario.organizer]

    @property
    def trip_oid(self) -> PydanticObjectId:
        oid = to_object_id(self.trip_id)
        if oid is None:
            raise LookupError("the trip has not been created")
        return oid

    @classmethod
    def build(
        cls, db: Database, settings: Settings, scenario: Scenario, options: Options
    ) -> "World":
        agent_var = options.out_dir / "agent"
        runs_dir = agent_var / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        clock = HarnessClock()
        behaviours: dict[str, SimBehaviour] = {}
        adapters: list[SupplierAdapter] = []
        browser: BrowserTransport | None = None
        pkp: PkpIntercitySupplier | None = None
        for spec in scenario.suppliers:
            behaviour = copy.deepcopy(spec.behaviour) if spec.behaviour else SimBehaviour()
            if spec.id == SIM_RAIL and options.live_agent_base_url:
                adapters.append(DemoRailSupplier(options.live_agent_base_url))
            elif spec.id == SIM_RAIL and options.live_search:
                browser = BrowserTransport(headless=True)
                pkp = PkpIntercitySupplier(browser)
                behaviours[pkp.id] = behaviour
                adapters.append(ScriptablePrices(pkp, behaviour))
            else:
                adapters.append(cls._simulator(spec, behaviour, clock))
                behaviours[spec.id] = behaviour
        suppliers = SupplierRegistry(adapters)

        scripted = ScriptedLauncher(runs_dir, suppliers=suppliers, behaviours=behaviours)
        launcher: AgentLauncher = scripted
        if options.live_agent_base_url:
            # The demo rail trajectory lets the live agent replay instead of planning each step.
            if LIVE_TRAJECTORIES.is_dir():
                shutil.copytree(LIVE_TRAJECTORIES, agent_var / "trajectories", dirs_exist_ok=True)
            live = SubprocessLauncher(
                backend_dir=BACKEND_DIR, var_dir=agent_var, extra_vault_file=None
            )
            launcher = RoutingLauncher(live=live, scripted=scripted)
        runner = BackgroundRunner()
        payments = FakePayments()
        researcher = CatalogResearcher(suppliers)
        return cls(
            db=db,
            settings=settings,
            scenario=scenario,
            options=options,
            runner=runner,
            clock=clock,
            suppliers=suppliers,
            behaviours=behaviours,
            trips=TripService(db, suppliers=suppliers),
            proposals=ProposalService(
                db,
                researcher,
                runner,
                suppliers=suppliers,
                prices=SupplierPrices(db, suppliers, clock=clock.now),
            ),
            contributions=ContributionService(payments),
            bookings=BookingService(
                db,
                launcher,
                runs_dir,
                max_steps=options.max_steps,
                poll_s=options.poll_s,
                payments=payments,
                suppliers=suppliers,
                clock=clock.now,
            ),
            travellers=TravellerService(),
            scripted=scripted,
            researcher=researcher,
            launcher=launcher,
            live_search_log=pkp.log if pkp is not None else None,
            browser=browser,
        )

    @staticmethod
    def _simulator(
        spec: SupplierSpec, behaviour: SimBehaviour, clock: HarnessClock
    ) -> SupplierAdapter:
        if spec.id not in SIM_CAPABILITIES:
            raise ValueError(f"unknown simulated supplier {spec.id!r}")
        return sim_supplier(spec.id, clock.now, behaviour)

    def advance(self, hours: float) -> None:
        self.clock.advance(timedelta(hours=hours))

    async def setup(self) -> None:
        """Opens the live browser if needed, registers every member, creates the trip as the
        organizer, lets the friends join and has everyone enter their traveller details
        (except `without_traveller_details`)."""
        if self.browser is not None:
            await self.resources.enter_async_context(self.browser)
        auth = AuthService(self.db, self.settings)
        for name in self.scenario.members:
            issued = await auth.register(_email(name), PASSWORD, f"{name}'s friends")
            if not isinstance(issued, Ok):
                raise RuntimeError(f"could not register {name}: {issued.error}")
            self.users[name] = issued.value.user.id
        brief = self.scenario.brief
        created = await self.trips.create(
            self.organizer_id,
            NewTrip(
                title=brief.title,
                origin=brief.origin,
                brief=brief.brief,
                date_from=brief.date_from,
                date_to=brief.date_to,
                group_size=brief.group_size,
                budget_per_person_minor=brief.budget_per_person_minor,
                display_name=self.scenario.organizer,
                destination=brief.destination,
                transport_mode=brief.transport_mode,
            ),
        )
        if not isinstance(created, Ok):
            raise RuntimeError(f"could not create the trip: {created.error}")
        self.trip_id = created.value.trip_id
        trip = await self.trips.trips.get(self.trip_oid)
        if trip is None:
            raise LookupError("the trip vanished right after creation")
        for name in self.scenario.friends:
            joined = await self.trips.join(trip.invite_code, self.users[name], name)
            if not isinstance(joined, Ok):
                raise RuntimeError(f"{name} could not join: {joined.error}")
        await self.enter_details(
            [n for n in self.scenario.members if n not in self.scenario.without_traveller_details]
        )

    async def enter_details(self, names: list[str]) -> None:
        for name in names:
            index = self.scenario.members.index(name)
            await self.travellers.update_mine(self.users[name], fake_details(index))

    async def close(self) -> None:
        await self.resources.aclose()
