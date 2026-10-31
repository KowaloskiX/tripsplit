"""A trip from one sentence: parse the brief, ask for what is missing, or create the trip with
the caller as organizer and start the package research right away. No HTTP here."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

from app.ai.quick_brief import (
    BriefReader,
    BriefReading,
    QuickAnswers,
    QuickDraft,
    QuickQuestion,
    RulesBriefReader,
    apply_answers,
    parse_quick_brief,
    questions_for,
)
from app.core.domain.errors import TripError
from app.core.domain.result import Err, Ok, Result
from app.db.documents import utc_now
from app.services.proposals import ProposalService
from app.services.trip_views import TripStatusView
from app.services.trips import NewTrip, TripService

NAME_MAX_LENGTH = 60
TITLE_MAX_LENGTH = 120
BRIEF_MAX_LENGTH = 4000

type Today = Callable[[], date]


def _today() -> date:
    return utc_now().date()


@dataclass(frozen=True, slots=True)
class QuickTripView:
    """`trip` is set when the brief was complete (the research is running); otherwise the
    client answers `questions` and sends the brief again with the answers."""

    trip: TripStatusView | None
    draft: QuickDraft
    questions: tuple[QuickQuestion, ...]
    reply: str  # the agent's chat message about the draft


def name_from_email(email: str) -> str:
    """ "anna.kowalska@x.pl" -> "Anna Kowalska": how the organizer appears until renamed."""
    local = email.split("@", 1)[0]
    words = [word for word in local.replace("_", ".").replace("-", ".").split(".") if word]
    name = " ".join(word.capitalize() for word in words if word.isalpha())
    return (name or "Organizer")[:NAME_MAX_LENGTH]


class QuickTripService:
    def __init__(
        self,
        trips: TripService,
        proposals: ProposalService,
        *,
        reader: BriefReader | None = None,
        today: Today = _today,
    ) -> None:
        self.trips = trips
        self.proposals = proposals
        self.reader = reader or RulesBriefReader()
        self.today = today

    async def understand(self, text: str, answers: QuickAnswers) -> BriefReading:
        today = self.today()
        draft = apply_answers(parse_quick_brief(text, today), answers, today)
        if draft.date_from is not None and draft.date_from < today:
            # A trip in the past cannot be booked: ask for the dates again.
            draft = replace(draft, date_from=None, date_to=None)
        return await self.reader.read(draft, today)

    async def create(
        self,
        user_id: str,
        text: str,
        answers: QuickAnswers,
        *,
        display_name: str,
    ) -> Result[QuickTripView, TripError]:
        reading = await self.understand(text, answers)
        draft = reading.draft
        questions = questions_for(draft, self.today())
        if (
            questions
            or draft.destination is None
            or draft.date_from is None
            or draft.date_to is None
            or draft.group_size is None
        ):
            return Ok(
                QuickTripView(trip=None, draft=draft, questions=questions, reply=reading.reply)
            )
        created = await self.trips.create(
            user_id,
            NewTrip(
                title=draft.title[:TITLE_MAX_LENGTH],
                origin=draft.origin,
                brief=draft.text[:BRIEF_MAX_LENGTH],
                date_from=draft.date_from,
                date_to=draft.date_to,
                group_size=draft.group_size,
                budget_per_person_minor=draft.budget_per_person_minor,
                display_name=display_name[:NAME_MAX_LENGTH],
                destination=draft.destination,
                transport_mode=draft.transport_mode,
            ),
        )
        if isinstance(created, Err):
            return created
        started = await self.proposals.generate(created.value.trip_id, user_id)
        trip = started.value if isinstance(started, Ok) else created.value
        return Ok(QuickTripView(trip=trip, draft=draft, questions=(), reply=reading.reply))
