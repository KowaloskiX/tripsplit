"""The goal as data: what the rule layer and flows bind values to.

The services hand the agent a natural-language goal (see `core/domain/packages.booking_goal`
and `BookingService._goal_for`). The deterministic layers need its few hard facts — party
size, travel date, the wanted connection, the budget — so we parse them once, here, instead
of letting each rule grep the prose.

None of these values is secret: they come from the goal, never from the vault. Vault values
(names, email) stay `{{vault.*}}` placeholders until `act.py` types them.
"""

import re
from dataclasses import dataclass
from typing import Any

_ISO_DATE = re.compile(r"\b(20\d\d-[01]\d-[0-3]\d)\b")
_PARTY = (
    re.compile(r"passengers on this purchase:\s*(\d+)", re.I),
    re.compile(r"\bfor\s+(\d+)\s+(?:passengers|people|travell?ers|guests|persons)\b", re.I),
    re.compile(r"\b(\d+)\s+(?:passengers|tickets|people|travell?ers)\b", re.I),
)
# "EC 113 Vltava", "EN 407 Chopin", "IC 5300", "TLK 1234 Name" — a train category + number.
_TRAIN = re.compile(r"\b((?:EC|EN|EIC|EIP|IC|TLK|RJ|ICE|RE|R)\s?\d{2,5}(?:\s+[A-Z][\w-]+)?)")
# The services state the amount the group paid for THIS purchase; it wins over a "budget".
_EXPECTED = re.compile(
    r"expected total[^\d]{0,5}(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(PLN|EUR|CZK|zł|USD)?", re.I
)
_RETURN_DATE = re.compile(r"return date[^\d]{0,5}(20\d\d-[01]\d-[0-3]\d)", re.I)
_BUDGET = re.compile(r"budget[^\d]{0,20}(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(PLN|EUR|CZK|zł|USD)?", re.I)
_DEPARTS = re.compile(r"\bdep(?:arts?|arture)?\.?\s*(?:at\s*)?([0-2]?\d:[0-5]\d)", re.I)
_TOLERANCE = re.compile(r"tolerance[^\d]{0,10}(\d+(?:[.,]\d+)?)\s*%", re.I)
_DEFAULT_TOLERANCE_PERCENT = 2.0


@dataclass(frozen=True, slots=True)
class GoalSpec:
    passengers: int
    date: str | None = None
    train: str | None = None
    budget: float | None = None
    currency: str | None = None
    tolerance_percent: float = _DEFAULT_TOLERANCE_PERCENT
    rebooking: bool = False
    departs: str | None = None
    # A return journey: the summary must show this date too (both legs on one order).
    return_date: str | None = None

    def variables(self) -> dict[str, str]:
        """`{{goal.<key>}}` bindings a flow may reference."""
        out = {"passengers": str(self.passengers)}
        if self.date:
            out["date"] = self.date
        if self.return_date:
            out["return_date"] = self.return_date
        if self.train:
            out["train"] = self.train
        return out


def vault_party(vault_keys: list[str]) -> int:
    """How many passengers the vault carries (`passenger_N_first_name`)."""
    indices = [
        int(m.group(1))
        for key in vault_keys
        if (m := re.fullmatch(r"passenger_(\d+)_first_name", key)) is not None
    ]
    return max(indices, default=0)


def _number(raw: str) -> float:
    return float(raw.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def parse_goal(goal: str, vault: Any = None) -> GoalSpec:
    """Hard facts of a goal. The vault, when given, wins on the party size."""
    keys: list[str] = list(vault.planner_keys()) if vault is not None else []
    party = vault_party(keys)
    if not party and vault is not None and str(vault.get("passengers") or "").isdigit():
        party = int(vault.get("passengers"))
    if not party:
        for pattern in _PARTY:
            if (m := pattern.search(goal)) is not None:
                party = int(m.group(1))
                break
    date = m.group(1) if (m := _ISO_DATE.search(goal)) is not None else None
    train = m.group(1).strip() if (m := _TRAIN.search(goal)) is not None else None
    budget = currency = None
    if (m := _EXPECTED.search(goal) or _BUDGET.search(goal)) is not None:
        budget = _number(m.group(1))
        currency = (m.group(2) or "").upper().replace("ZŁ", "PLN") or None
    tolerance = (
        _number(m.group(1))
        if (m := _TOLERANCE.search(goal)) is not None
        else _DEFAULT_TOLERANCE_PERCENT
    )
    return GoalSpec(
        passengers=max(party, 1),
        date=date,
        train=train,
        budget=budget,
        currency=currency,
        tolerance_percent=tolerance,
        rebooking="rebooking" in goal.lower(),
        departs=m.group(1) if (m := _DEPARTS.search(goal)) is not None else None,
        return_date=m.group(1) if (m := _RETURN_DATE.search(goal)) is not None else None,
    )
