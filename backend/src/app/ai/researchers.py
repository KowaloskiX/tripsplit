"""Picks the `PackageResearcher` adapter from configuration."""

from app.ai.catalog_research import CatalogResearcher
from app.ai.claude_research import ClaudeCliResearcher
from app.ai.research import PackageResearcher
from app.core.config import Settings
from app.suppliers.registry import SupplierRegistry


def build_researcher(settings: Settings, suppliers: SupplierRegistry) -> PackageResearcher:
    catalogue = CatalogResearcher(suppliers)
    if settings.researcher == "claude-cli":
        return ClaudeCliResearcher(catalogue, timeout_s=settings.research_timeout_s)
    return catalogue
