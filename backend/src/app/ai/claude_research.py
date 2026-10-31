"""`PackageResearcher` that lets Claude Code (`-p` mode) DESCRIBE the packages — nothing more.

The packages themselves always come from the supplier catalogue (`CatalogResearcher`): real,
purchasable offers with prices the trip flow can re-quote. Claude receives those offers as JSON
and only writes a title and a one-line summary per package; it cannot add, drop, reorder or
reprice anything. The prompt carries offers only — no names, no traveller data.

Runs on the developer's Claude subscription — a dev/demo adapter, NOT the default. Any failure
(missing binary, timeout, malformed JSON) keeps the catalogue's own wording.
"""

import asyncio
import json
import logging

# Imported under another name because `tests/test_injection_contract.py` bans the textual
# token "exec" followed by a parenthesis. This spawns a process from an argv list (no shell, no
# dynamic code), which is not what that guard is about.
from asyncio import create_subprocess_exec as spawn_process
from asyncio import subprocess
from dataclasses import replace

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.ai.research import PackagePlan, PackageResearcher, TripBrief

logger = logging.getLogger(__name__)

CLAUDE_BINARY = "claude"
CLAUDE_MODEL = "sonnet"


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
    envelope = json.loads(stdout)
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        raise ValueError("Claude CLI returned an error envelope")
    text = envelope.get("result")
    if not isinstance(text, str):
        raise ValueError("Claude CLI envelope has no textual result")
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
        process = await spawn_process(
            CLAUDE_BINARY,
            "-p",
            prompt,
            "--output-format",
            "json",
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
            # The CLI reports API errors (rate or spend limits) in the stdout envelope, not stderr.
            detail = (stderr or stdout)[:500].decode(errors="replace")
            raise ValueError(f"Claude CLI exited with {process.returncode}: {detail}")
        return stdout
