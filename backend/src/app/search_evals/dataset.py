"""The eval dataset: trip briefs as data.

Every brief is a group trip from a Polish city (Warszawa, Kraków, Gdańsk) to one of seven
European cities, with a party of 2/4/6/8, a budget tier, weekend or midweek dates in
November-December 2026 and a mode wish. Expectations are written down only where they are
obvious ("Praha by rail" must be by rail, a "fly there, train back" trip must do exactly that).
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.ai.research import TripBrief
from app.core.domain.trips import TransportMode


class BudgetTier(StrEnum):
    TIGHT = "tight"
    MEDIUM = "medium"
    NONE = "none"


class ModeWish(StrEnum):
    ANY = "any"
    RAIL = "rail"
    FLIGHT = "flight"
    FLY_THERE_TRAIN_BACK = "fly_there_train_back"


# Per person, for the whole trip (transport + stay + an evening out), in grosze.
BUDGET_PER_PERSON_MINOR: dict[BudgetTier, int | None] = {
    BudgetTier.TIGHT: 80_000,
    BudgetTier.MEDIUM: 160_000,
    BudgetTier.NONE: None,
}

# (outbound mode, return mode) a package may use; None = any mode.
ALLOWED_MODES: dict[ModeWish, tuple[TransportMode | None, TransportMode | None]] = {
    ModeWish.ANY: (None, None),
    ModeWish.RAIL: (TransportMode.RAIL, TransportMode.RAIL),
    ModeWish.FLIGHT: (TransportMode.FLIGHT, TransportMode.FLIGHT),
    ModeWish.FLY_THERE_TRAIN_BACK: (TransportMode.FLIGHT, TransportMode.RAIL),
}

_WEEKEND_NOV = (date(2026, 11, 20), date(2026, 11, 22))  # Fri-Sun
_MIDWEEK_NOV = (date(2026, 11, 24), date(2026, 11, 26))  # Tue-Thu
_WEEKEND_DEC = (date(2026, 12, 4), date(2026, 12, 6))  # Fri-Sun
_MIDWEEK_DEC = (date(2026, 12, 8), date(2026, 12, 10))  # Tue-Thu


@dataclass(frozen=True, slots=True)
class EvalBrief:
    id: str
    origin: str
    destination: str
    dates: tuple[date, date]
    party: int
    budget: BudgetTier
    mode: ModeWish
    # Departures earlier than this local hour are unwanted (outbound and return).
    earliest_departure_hour: int | None = None
    # The oracle is expected to find a complete package (transport both ways + a stay).
    expect_complete: bool = True

    @property
    def date_from(self) -> date:
        return self.dates[0]

    @property
    def date_to(self) -> date:
        return self.dates[1]

    @property
    def budget_per_person_minor(self) -> int | None:
        return BUDGET_PER_PERSON_MINOR[self.budget]

    @property
    def weekend(self) -> bool:
        return self.date_from.weekday() == 4

    def text(self) -> str:
        """The brief as an organiser would write it — the mode wish is in the words too."""
        how = {
            ModeWish.ANY: "",
            ModeWish.RAIL: " We want to go by train.",
            ModeWish.FLIGHT: " We want to fly.",
            ModeWish.FLY_THERE_TRAIN_BACK: " Let's fly there and take the train back.",
        }[self.mode]
        when = "a weekend" if self.weekend else "a few midweek days"
        early = (
            f" Nobody wants to leave before {self.earliest_departure_hour}:00."
            if self.earliest_departure_hour is not None
            else ""
        )
        return f"{self.party} friends, {when} in {self.destination}.{how}{early}"

    def trip_brief(self) -> TripBrief:
        explicit_mode = {
            ModeWish.RAIL: TransportMode.RAIL,
            ModeWish.FLIGHT: TransportMode.FLIGHT,
        }.get(self.mode)
        return TripBrief(
            title=f"{self.destination} with friends",
            origin=self.origin,
            brief=self.text(),
            date_from=self.date_from,
            date_to=self.date_to,
            travellers=self.party,
            budget_per_person_minor=self.budget_per_person_minor,
            destination=self.destination,
            transport_mode=explicit_mode,
            earliest_departure_hour=self.earliest_departure_hour,
        )


def _b(
    id_: str,
    origin: str,
    destination: str,
    dates: tuple[date, date],
    party: int,
    budget: BudgetTier,
    mode: ModeWish,
    earliest: int | None = None,
) -> EvalBrief:
    return EvalBrief(id_, origin, destination, dates, party, budget, mode, earliest)


T, M, N = BudgetTier.TIGHT, BudgetTier.MEDIUM, BudgetTier.NONE
ANY, RAIL, FLY, MIX = ModeWish.ANY, ModeWish.RAIL, ModeWish.FLIGHT, ModeWish.FLY_THERE_TRAIN_BACK

BRIEFS: tuple[EvalBrief, ...] = (
    _b("waw-prg-rail-4-medium-we", "Warszawa", "Praha", _WEEKEND_NOV, 4, M, RAIL),
    _b("waw-prg-any-6-tight-we", "Warszawa", "Praha", _WEEKEND_NOV, 6, T, ANY),
    _b("krk-prg-rail-2-none-mid", "Kraków", "Praha", _MIDWEEK_NOV, 2, N, RAIL),
    _b("gdn-prg-any-4-medium-we", "Gdańsk", "Praha", _WEEKEND_DEC, 4, M, ANY),
    _b("waw-ber-rail-8-medium-we", "Warszawa", "Berlin", _WEEKEND_NOV, 8, M, RAIL),
    _b("krk-ber-any-2-tight-mid", "Kraków", "Berlin", _MIDWEEK_DEC, 2, T, ANY),
    _b("gdn-ber-rail-4-tight-we", "Gdańsk", "Berlin", _WEEKEND_NOV, 4, T, RAIL),
    _b("waw-ber-any-4-medium-we-8h", "Warszawa", "Berlin", _WEEKEND_DEC, 4, M, ANY, 8),
    _b("waw-vie-any-4-medium-we", "Warszawa", "Wien", _WEEKEND_NOV, 4, M, ANY),
    _b("krk-vie-rail-6-medium-mid", "Kraków", "Wien", _MIDWEEK_NOV, 6, M, RAIL),
    _b("waw-vie-flight-2-none-we", "Warszawa", "Wien", _WEEKEND_DEC, 2, N, FLY),
    _b("waw-bud-rail-4-tight-we", "Warszawa", "Budapest", _WEEKEND_NOV, 4, T, RAIL),
    _b("krk-bud-any-8-medium-we", "Kraków", "Budapest", _WEEKEND_DEC, 8, M, ANY),
    _b("gdn-bud-flight-2-medium-mid", "Gdańsk", "Budapest", _MIDWEEK_NOV, 2, M, FLY),
    _b("waw-bcn-flight-4-medium-we", "Warszawa", "Barcelona", _WEEKEND_NOV, 4, M, FLY),
    _b("waw-bcn-any-6-tight-we", "Warszawa", "Barcelona", _WEEKEND_DEC, 6, T, ANY),
    _b("krk-bcn-flight-2-none-mid", "Kraków", "Barcelona", _MIDWEEK_NOV, 2, N, FLY, 7),
    _b("gdn-bcn-any-8-medium-mid", "Gdańsk", "Barcelona", _MIDWEEK_DEC, 8, M, ANY),
    _b("waw-lis-flight-4-medium-we", "Warszawa", "Lisboa", _WEEKEND_NOV, 4, M, FLY),
    _b("krk-lis-any-2-tight-mid", "Kraków", "Lisboa", _MIDWEEK_DEC, 2, T, ANY),
    _b("waw-rom-flight-6-medium-we", "Warszawa", "Roma", _WEEKEND_DEC, 6, M, FLY),
    _b("gdn-rom-any-4-none-we", "Gdańsk", "Roma", _WEEKEND_NOV, 4, N, ANY, 8),
    _b("waw-prg-mix-4-medium-we", "Warszawa", "Praha", _WEEKEND_DEC, 4, M, MIX),
    _b("krk-vie-mix-2-none-mid", "Kraków", "Wien", _MIDWEEK_DEC, 2, N, MIX),
)


def select(ids: list[str] | None) -> list[EvalBrief]:
    """The briefs by id (or a prefix like `waw-prg`), all of them for None/empty."""
    if not ids:
        return list(BRIEFS)
    chosen = [brief for brief in BRIEFS if any(brief.id.startswith(key) for key in ids)]
    if not chosen:
        raise ValueError(f"no brief matches {ids}")
    return chosen
