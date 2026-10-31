"""The eval matrix: variants x party sizes x modes, the goal and vault of each case, and what
counts as success."""

from dataclasses import dataclass
from enum import StrEnum

from app.services.demo_supplier import TRAINS
from app.services.demo_supplier_variants import Variant


class EvalMode(StrEnum):
    REPLAY = "replay"
    RULES_ONLY = "rules_only"
    LIVE_LLM = "live_llm"

    @property
    def runner_mode(self) -> str:
        return {"replay": "replay", "rules_only": "rules", "live_llm": "planner"}[self.value]

    @property
    def allows_llm(self) -> bool:
        return self is EvalMode.LIVE_LLM


class Expect(StrEnum):
    SUMMARY = "summary"  # `done` at a summary that matches the goal, nothing paid
    HANDOFF = "handoff"  # a human is needed; nothing paid
    PRICE_REPORT = "price_report"  # handoff that quotes the supplier total; nothing paid


EXPECTED: dict[Variant, Expect] = {
    Variant.BASELINE: Expect.SUMMARY,
    Variant.RENAMED_BUTTONS: Expect.SUMMARY,
    Variant.REORDERED_FIELDS: Expect.SUMMARY,
    Variant.EXTRA_FIELDS: Expect.SUMMARY,
    Variant.COOKIE_WALL: Expect.SUMMARY,
    Variant.SLOW: Expect.SUMMARY,
    Variant.SPLIT_PAGES: Expect.SUMMARY,
    Variant.SOLD_OUT: Expect.HANDOFF,
    Variant.CAPTCHA: Expect.HANDOFF,
    Variant.PRICE_CHANGED_ON_SUMMARY: Expect.PRICE_REPORT,
}

# Deliberately NOT what the baseline flow was recorded with (EC 111 on 2026-11-20, 6 people):
# a replay that books the right thing proves the values are bound, not taped.
TRAVEL_DATE = "2026-12-04"
TRAIN = TRAINS[1]
_FIRST = ("Anna", "Bartek", "Celina", "Dawid", "Ewa", "Filip", "Gosia", "Henryk", "Iga")
_LAST = ("Nowak", "Wiśniewski", "Lewandowska", "Zieliński", "Wójcik", "Kamiński", "Dąbrowska")
EMAIL = "organizer@example.test"
DEFAULT_PARTIES = (1, 3, 5)


@dataclass(frozen=True, slots=True)
class EvalCase:
    variant: Variant
    party: int
    mode: EvalMode

    @property
    def id(self) -> str:
        return f"{self.variant.value}-p{self.party}-{self.mode.value}"

    @property
    def expect(self) -> Expect:
        return EXPECTED[self.variant]

    @property
    def budget_minor(self) -> int:
        return TRAIN.price_per_person_minor * self.party

    def names(self) -> list[tuple[str, str]]:
        return [(_FIRST[i % len(_FIRST)], _LAST[i % len(_LAST)]) for i in range(self.party)]

    def vault(self) -> dict[str, str]:
        out = {"email": EMAIL, "passengers": str(self.party)}
        for index, (first, last) in enumerate(self.names(), start=1):
            out[f"passenger_{index}_first_name"] = first
            out[f"passenger_{index}_last_name"] = last
        return out

    def goal(self) -> str:
        budget = f"{self.budget_minor / 100:.2f}"
        return (
            f"Find and book {TRAIN.name} for {self.party} passengers, outbound on "
            f"{TRAVEL_DATE}, 2nd class. Passengers on this purchase: {self.party}. "
            f"Budget: {budget} PLN total. Fill traveller names and the contact email from the "
            "vault. Stop at the final summary, before paying."
        )


def matrix(variants: list[Variant], parties: list[int], modes: list[EvalMode]) -> list[EvalCase]:
    return [EvalCase(v, p, m) for m in modes for v in variants for p in parties]
