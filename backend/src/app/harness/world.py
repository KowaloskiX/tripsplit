"""A world for one scenario: a database, real users, the real services and injected adapters.

The services are constructed exactly like `app.routes.dependencies` builds them; only the
adapters differ — FakePayments, a fixture (or live PKP) researcher, a scripted (or live) agent
and a scripted supplier quote.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId

from app.agent.launcher import AgentLauncher, SubprocessLauncher
from app.ai.fixture_research import FixtureResearcher
from app.ai.research import PackageResearcher
from app.core.background import BackgroundRunner
from app.core.config import Settings
from app.core.domain.result import Ok
from app.db.client import Database
from app.db.identifiers import to_object_id
from app.harness.adapters import RoutingLauncher, ScriptedLauncher, ScriptedQuotes
from app.harness.features import Feature, feature
from app.harness.live_research import LiveIntercityResearcher
from app.harness.scenario import Scenario
from app.payments.fake import FakePayments
from app.services.auth import AuthService
from app.services.bookings import BookingService
from app.services.contributions import ContributionService
from app.services.proposals import ProposalService
from app.services.trips import NewTrip, TripService

PASSWORD = "harness-correct-horse-battery-staple"
EMAIL_DOMAIN = "harness.tripsplit.invalid"
# backend/: the live agent subprocess runs from here, like in `app.routes.dependencies`.
BACKEND_DIR = Path(__file__).resolve().parents[3]
LIVE_TRAJECTORIES = BACKEND_DIR / "var" / "agent" / "trajectories"


@dataclass(frozen=True, slots=True)
class Options:
    out_dir: Path  # this scenario's artifacts: agent runs live under out_dir/agent/runs
    live_search: bool = False
    # Base URL of a backend serving /api/demo-supplier/rail; set => live agent for trains.
    live_agent_base_url: str | None = None
    poll_s: float = 0.02
    max_steps: int = 40


def _email(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}@{EMAIL_DOMAIN}"


@dataclass
class World:
    db: Database
    settings: Settings
    scenario: Scenario
    options: Options
    runner: BackgroundRunner
    trips: TripService
    proposals: ProposalService
    contributions: ContributionService
    bookings: BookingService
    scripted: ScriptedLauncher
    quotes: ScriptedQuotes
    researcher: PackageResearcher
    launcher: AgentLauncher
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
        scripted = ScriptedLauncher(runs_dir)
        launcher: AgentLauncher = scripted
        train_supplier_url: str | None = None
        if options.live_agent_base_url:
            # The demo rail trajectory lets the live agent replay instead of planning each step.
            if LIVE_TRAJECTORIES.is_dir():
                shutil.copytree(LIVE_TRAJECTORIES, agent_var / "trajectories", dirs_exist_ok=True)
            live = SubprocessLauncher(
                backend_dir=BACKEND_DIR, var_dir=agent_var, extra_vault_file=None
            )
            launcher = RoutingLauncher(live=live, scripted=scripted)
            train_supplier_url = f"{options.live_agent_base_url.rstrip('/')}/api/demo-supplier/rail"
        researcher: PackageResearcher = (
            LiveIntercityResearcher(
                scenario.brief.origin_station, scenario.brief.destination_station
            )
            if options.live_search
            else FixtureResearcher()
        )
        runner = BackgroundRunner()
        quotes = ScriptedQuotes()
        payments = FakePayments()
        extra: dict[str, Any] = {}
        if feature(Feature.QUOTES).present:
            extra["quotes"] = quotes
        return cls(
            db=db,
            settings=settings,
            scenario=scenario,
            options=options,
            runner=runner,
            trips=TripService(db),
            proposals=ProposalService(
                db, researcher, runner, train_supplier_url=train_supplier_url
            ),
            contributions=ContributionService(payments),
            bookings=BookingService(
                db,
                launcher,
                runs_dir,
                max_steps=options.max_steps,
                poll_s=options.poll_s,
                payments=payments,
                **extra,
            ),
            scripted=scripted,
            quotes=quotes,
            researcher=researcher,
            launcher=launcher,
        )

    async def setup(self) -> None:
        """Registers every member, creates the trip as the organizer and lets the friends join."""
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
