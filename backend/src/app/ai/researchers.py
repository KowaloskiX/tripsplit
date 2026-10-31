"""Picks the `PackageResearcher` adapter from configuration."""

from app.ai.claude_research import ClaudeCliResearcher
from app.ai.fixture_research import FixtureResearcher
from app.ai.research import PackageResearcher
from app.core.config import Settings


def build_researcher(settings: Settings) -> PackageResearcher:
    if settings.researcher == "claude-cli":
        return ClaudeCliResearcher(timeout_s=settings.research_timeout_s)
    return FixtureResearcher()
