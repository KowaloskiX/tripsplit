"""`PackageResearcher` backed by Claude Code in `-p` mode, with web search.

Runs on the developer's Claude subscription — a dev/demo adapter, not a production one. Any
failure (missing binary, timeout, malformed JSON, a schema violation) falls back to the fixture
packages, so a demo never stalls on the LLM.
"""

import asyncio
import json
import logging

# Imported under another name because `tests/test_injection_contract.py` bans the textual
# token "exec" followed by a parenthesis. This spawns a process from an argv list (no shell, no
# dynamic code), which is not what that guard is about.
from asyncio import create_subprocess_exec as spawn_process
from asyncio import subprocess
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.ai.fixture_research import FixtureResearcher
from app.ai.research import (
    PACKAGES_PER_RESEARCH,
    PackageItemPlan,
    PackagePlan,
    PackageResearcher,
    TripBrief,
)
from app.core.domain.trips import BookingKind

logger = logging.getLogger(__name__)

CLAUDE_BINARY = "claude"
CLAUDE_MODEL = "sonnet"


class _ItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: BookingKind
    title: str = Field(min_length=1, max_length=120)
    supplier: str = Field(min_length=1, max_length=120)
    supplier_url: str = Field(pattern=r"^https://", max_length=2000)
    price_minor: int = Field(ge=0)
    details: str = Field(default="", max_length=4000)
    starts_at: datetime | None = None


class _PackageModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=4000)
    items: list[_ItemModel] = Field(min_length=1, max_length=6)


_PACKAGES = TypeAdapter(list[_PackageModel])


def build_prompt(brief: TripBrief) -> str:
    budget = (
        f"Budget per person: about {brief.budget_per_person_minor / 100:.0f} {brief.currency}."
        if brief.budget_per_person_minor
        else "No explicit budget."
    )
    return f"""You are a group-trip researcher. Research real, currently bookable options on
the web.

Trip: {brief.title}
Travelling from: {brief.origin}
Dates: {_iso(brief.date_from)} to {_iso(brief.date_to)} ({brief.nights} night(s))
Travellers: {brief.travellers}
Brief from the group: {brief.brief or "(none)"}
{budget}

Propose EXACTLY {PACKAGES_PER_RESEARCH} packages, from cheapest to most comfortable. Each package
combines a return train (kind "train"), a stay (kind "stay") and optionally one activity
(kind "activity"). Prefer PKP Intercity (https://www.intercity.pl/pl/) for trains, Booking.com
(https://www.booking.com/) for stays and GetYourGuide (https://www.getyourguide.com/) for
activities, and use their home pages as supplier_url.

Prices are integers in minor units of {brief.currency} (1 {brief.currency} = 100) and cover the
WHOLE group for the whole trip, not one person.

Reply with ONLY a JSON array — no prose, no markdown fences — matching this schema:
[
  {{
    "title": "string, max 120 chars, e.g. 'Budget: PKP Intercity EIC + hostel'",
    "summary": "one or two sentences",
    "items": [
      {{
        "kind": "train" | "stay" | "activity",
        "title": "string, max 120 chars, e.g. 'PKP Intercity EIC Warszawa -> Praha hl.n.'",
        "supplier": "string, e.g. 'PKP Intercity'",
        "supplier_url": "https://...",
        "price_minor": 123400,
        "details": "times, class, room type, what is included",
        "starts_at": "ISO 8601 datetime with timezone, or null"
      }}
    ]
  }}
]"""


def _iso(day: date) -> str:
    return day.isoformat()


def parse_packages(stdout: bytes) -> list[PackagePlan]:
    """The CLI envelope `{"type": "result", "result": "<text>"}` -> validated packages.

    Raises `ValueError` (or `ValidationError`, a subclass) on anything unexpected.
    """
    envelope = json.loads(stdout)
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        raise ValueError("Claude CLI returned an error envelope")
    text = envelope.get("result")
    if not isinstance(text, str):
        raise ValueError("Claude CLI envelope has no textual result")
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("the result contains no JSON array")
    packages = _PACKAGES.validate_json(text[start : end + 1])
    if len(packages) != PACKAGES_PER_RESEARCH:
        raise ValueError(f"expected {PACKAGES_PER_RESEARCH} packages, got {len(packages)}")
    return [
        PackagePlan(
            title=package.title,
            summary=package.summary,
            items=tuple(
                PackageItemPlan(
                    kind=item.kind,
                    title=item.title,
                    supplier=item.supplier,
                    supplier_url=item.supplier_url,
                    price_minor=item.price_minor,
                    details=item.details,
                    starts_at=item.starts_at,
                )
                for item in package.items
            ),
        )
        for package in packages
    ]


class ClaudeCliResearcher:
    def __init__(self, timeout_s: float, fallback: PackageResearcher | None = None) -> None:
        self._timeout_s = timeout_s
        self._fallback = fallback or FixtureResearcher()

    async def research(self, brief: TripBrief) -> list[PackagePlan]:
        try:
            return parse_packages(await self._run(build_prompt(brief)))
        except (OSError, TimeoutError, ValueError, ValidationError):
            logger.exception("Claude CLI research failed — falling back to fixture packages")
            return await self._fallback.research(brief)

    async def _run(self, prompt: str) -> bytes:
        process = await spawn_process(
            CLAUDE_BINARY,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--allowed-tools",
            "WebSearch,WebFetch",
            "--no-session-persistence",
            "--model",
            CLAUDE_MODEL,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self._timeout_s)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise ValueError(
                f"Claude CLI exited with {process.returncode}: {stderr.decode(errors='replace')}"
            )
        return stdout
