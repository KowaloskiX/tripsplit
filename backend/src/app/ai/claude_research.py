"""`PackageResearcher` that lets Claude Code (`-p` mode) DESCRIBE the packages — nothing more.

The packages themselves always come from the supplier catalogue (`CatalogResearcher`): real,
purchasable offers with prices the trip flow can re-quote. Claude receives those offers as JSON
and only writes a title and a one-line summary per package; it cannot add, drop, reorder or
reprice anything. The prompt carries offers only — no names, no traveller data.

Runs on the developer's Claude subscription — a dev/demo adapter, NOT the default. Any failure
(missing binary, timeout, malformed JSON) keeps the catalogue's own wording.
"""

import json
import logging
from dataclasses import replace

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.ai.claude_cli import result_text, run_claude
from app.ai.research import PackagePlan, PackageResearcher, TripBrief

logger = logging.getLogger(__name__)


class _Description(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=4000)


_DESCRIPTIONS = TypeAdapter(list[_Description])


def offers_json(plans: list[PackagePlan]) -> str:
    """What Claude sees: per package, its items' public facts."""
    return json.dumps(
        [
            {
                "package": index,
                "total_minor": plan.total_minor,
                "items": [
                    {
                        "kind": item.kind.value,
                        "mode": item.mode.value if item.mode else None,
                        "title": item.title,
                        "seller": item.supplier,
                        "price_minor": item.price_minor,
                        "details": item.details,
                    }
                    for item in plan.items
                ],
            }
            for index, plan in enumerate(plans)
        ],
        ensure_ascii=False,
    )


def build_prompt(brief: TripBrief, plans: list[PackagePlan]) -> str:
    return f"""You write short, friendly package descriptions for a group-trip app.

Trip: {brief.title} — from {brief.origin}, {brief.date_from.isoformat()} to
{brief.date_to.isoformat()}, {brief.travellers} travellers. Brief: {brief.brief or "(none)"}

These {len(plans)} packages are FIXED (prices in minor units of {brief.currency} for the whole
group). Do not change, add or drop anything — only describe them, in the same order:
{offers_json(plans)}

Reply with ONLY a JSON array of {len(plans)} objects, no prose, no markdown fences:
[{{"title": "max 120 chars, starts with Budget / Comfort / Splurge", "summary": "one sentence"}}]"""


def parse_descriptions(stdout: bytes, expected: int) -> list[_Description]:
    """The CLI envelope `{"type": "result", "result": "<text>"}` -> validated descriptions.

    Raises `ValueError` (or `ValidationError`, a subclass) on anything unexpected.
    """
    text = result_text(stdout)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("the result contains no JSON array")
    descriptions = _DESCRIPTIONS.validate_json(text[start : end + 1])
    if len(descriptions) != expected:
        raise ValueError(f"expected {expected} descriptions, got {len(descriptions)}")
    return descriptions


class ClaudeCliResearcher:
    def __init__(self, catalogue: PackageResearcher, timeout_s: float) -> None:
        self._catalogue = catalogue
        self._timeout_s = timeout_s

    async def research(self, brief: TripBrief) -> list[PackagePlan]:
        plans = await self._catalogue.research(brief)
        try:
            described = parse_descriptions(await self._run(build_prompt(brief, plans)), len(plans))
        except (OSError, TimeoutError, ValueError, ValidationError):
            logger.exception("Claude CLI could not describe the packages — catalogue wording kept")
            return plans
        return [
            replace(plan, title=text.title, summary=text.summary)
            for plan, text in zip(plans, described, strict=True)
        ]

    async def _run(self, prompt: str) -> bytes:
        return await run_claude(prompt, self._timeout_s)
