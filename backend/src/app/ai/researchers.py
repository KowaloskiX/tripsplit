"""Picks the `PackageResearcher` adapter from configuration."""

from functools import lru_cache

from app.ai.catalog_research import CatalogResearcher
from app.ai.claude_research import ClaudeCliResearcher
from app.ai.research import PackageResearcher
from app.core.config import Settings
from app.suppliers.registry import SupplierRegistry
from app.suppliers.search_cache import SearchCache


@lru_cache
def shared_search_cache(ttl_s: float) -> SearchCache:
    """The process's one search cache (the researcher itself is built per request)."""
    return SearchCache(ttl_s=ttl_s)


def build_researcher(settings: Settings, suppliers: SupplierRegistry) -> PackageResearcher:
    catalogue = CatalogResearcher(
        suppliers,
        cache=shared_search_cache(settings.search_cache_ttl_s),
        supplier_timeout_s=settings.search_supplier_timeout_s,
    )
    if settings.researcher == "claude-cli":
        return ClaudeCliResearcher(catalogue, timeout_s=settings.research_timeout_s)
    return catalogue
