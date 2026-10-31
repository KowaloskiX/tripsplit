"""Schema extraction for verification: the supplier's summary page as a typed record.

Before the agent says `done` (or before a human is asked to approve), we read what the
supplier will actually sell into a `SummaryRecord` — total, currency, passenger names and
count, travel date, service (train number) — and compare THAT with the goal. Rules first:
labelled rows (`<th>/<td>`, `<dt>/<dd>`) collected by `observe`, then regexes over the page
text. A record that cannot be filled in is treated as a mismatch (handoff), never guessed.

The record holds real passenger names while it is compared; `masked()` is what leaves the
process (result.json `summary`).
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.agent.site_profiles import SiteProfile

_ISO = re.compile(r"\b(20\d\d)-([01]\d)-([0-3]\d)\b")
_DMY = re.compile(r"\b([0-3]\d)[./]([01]\d)[./](20\d\d)\b")
_SERVICE = re.compile(r"\b((?:EC|EN|EIC|EIP|IC|TLK|RJ|ICE|RE|R)\s?\d{2,5})\b")
_ROW = {
    "total": re.compile(r"total|razem|suma|do zapłaty|amount", re.I),
    "date": re.compile(r"\bdate\b|\bdata\b|departure|wyjazd|odjazd", re.I),
    "service": re.compile(r"train|pociąg|service|flight|connection|połączenie", re.I),
    "passengers": re.compile(r"passenger|pasażer|travell?er|podróżn", re.I),
}


def _money_minor(raw: str) -> int:
    return round(float(re.sub(r"[\s\u00a0]", "", raw).replace(",", ".")) * 100)


def _date(text: str) -> str | None:
    if (m := _ISO.search(text)) is not None:
        return m.group(0)
    if (m := _DMY.search(text)) is not None:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def _mask_name(name: str) -> str:
    return " ".join(f"{part[:1]}***" for part in name.split()) or "***"


@dataclass(frozen=True, slots=True)
class SummaryRecord:
    total_minor: int | None = None
    currency: str | None = None
    passenger_count: int | None = None
    passengers: tuple[str, ...] = field(default_factory=tuple)
    date: str | None = None
    service: str | None = None
    source: str = "rules"

    def masked(self) -> dict[str, Any]:
        out = asdict(self)
        out["passengers"] = [_mask_name(n) for n in self.passengers]
        return out


def extract_summary(state: dict[str, Any], profile: SiteProfile) -> SummaryRecord:
    """Read a summary page (an `observe` state) into a record; unknown fields stay None."""
    rows: list[dict[str, Any]] = state.get("rows") or []
    text = str(state.get("text") or state.get("text_preview") or "")
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key, pattern in _ROW.items():
            if key not in found and pattern.search(str(row.get("label") or "")):
                found[key] = row
                break

    total_minor = currency = None
    total_src = str(found["total"]["value"]) if "total" in found else text
    pattern = (
        profile.total if "total" not in found else r"(\d[\d\s\u00a0]*[.,]\d{2})\s*(PLN|zł|EUR|CZK)?"
    )
    if (m := re.search(pattern, total_src, re.I)) is not None:
        total_minor = _money_minor(m.group(1))
        currency = (m.group(2) or "").upper().replace("ZŁ", "PLN") or None

    date = _date(str(found["date"]["value"])) if "date" in found else None
    date = date or _date(text)

    service_src = str(found["service"]["value"]) if "service" in found else text
    service = m.group(1) if (m := _SERVICE.search(service_src)) is not None else None

    passengers: tuple[str, ...] = ()
    count: int | None = None
    if "passengers" in found:
        row = found["passengers"]
        passengers = tuple(str(i) for i in row.get("items") or [] if str(i).strip())
        if (m := re.match(r"\s*(\d+)", str(row.get("value") or ""))) is not None:
            count = int(m.group(1))
        elif passengers:
            count = len(passengers)
    return SummaryRecord(total_minor, currency, count, passengers, date, service)
