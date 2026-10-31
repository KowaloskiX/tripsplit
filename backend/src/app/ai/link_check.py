"""Are the links on the packages alive, and is there a photo? One GET per page, at research time.

A port of Boscart's `inspectProductPage` (lib/og-image.ts): fetch a supplier page ONCE and read
two things off it — whether it is gone (HTTP 404 / 410 only) and its social-preview image
(`og:image` / `twitter:image`) to give an item without photos one. Conservative on "gone":
403 bot walls, timeouts, 5xx and redirects all count as live, so a blocked-but-real page is
never dropped. Every page is fetched concurrently with a short timeout, and the whole pass
never holds a research up longer than `budget_s` — unfinished checks count as live.

Search pages we build ourselves (Google Flights / Maps, Flightradar24) are not fetched: they
always exist, and they are not what a traveller needs verified.
"""

import asyncio
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlparse

import httpx

from app.ai.research import PackageItemPlan, PackagePlan
from app.core.domain.trust import MAX_IMAGES, OfferLink, is_web_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 1.2
DEFAULT_BUDGET_S = 1.5
MAX_PAGES = 12
MAX_HTML_CHARS = 250_000
GONE_STATUSES = frozenset({404, 410})
SKIPPED_HOSTS = ("google.com", "flightradar24.com", "flightaware.com")
USER_AGENT = "Mozilla/5.0 (compatible; TripSplitBot/1.0; link check)"

_IMAGE_PATTERNS = (
    re.compile(
        r"""<meta[^>]+(?:property|name)=["']og:image(?::secure_url)?["'][^>]+"""
        r"""content=["']([^"']+)["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<meta[^>]+content=["']([^"']+)["'][^>]+"""
        r"""(?:property|name)=["']og:image(?::secure_url)?["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<meta[^>]+name=["']twitter:image(?::src)?["'][^>]+content=["']([^"']+)["']""",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True, slots=True)
class PageCheck:
    gone: bool = False
    image: str = ""


LIVE = PageCheck()


def _absolute_https(candidate: str, base: str) -> str:
    url = urljoin(base, "https:" + candidate if candidate.startswith("//") else candidate)
    return url if url.startswith("https://") else ""


def og_image(html: str, page_url: str) -> str:
    """The page's social-preview image as an absolute https URL, or ""."""
    for pattern in _IMAGE_PATTERNS:
        match = pattern.search(html)
        if match is not None:
            resolved = _absolute_https(match.group(1).strip(), page_url)
            if resolved:
                return resolved
    return ""


def _checked(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return is_web_url(url) and not any(
        host == skipped or host.endswith("." + skipped) for skipped in SKIPPED_HOSTS
    )


async def inspect_page(http: httpx.AsyncClient, url: str, *, want_image: bool) -> PageCheck:
    """One GET: gone (404/410) or live, plus the og:image when asked. Never raises."""
    headers = {"user-agent": USER_AGENT, "accept": "text/html,application/xhtml+xml"}
    if not want_image:
        headers["range"] = "bytes=0-2047"  # only the status line matters
    try:
        response = await http.get(url, headers=headers, follow_redirects=True)
    except (httpx.HTTPError, ValueError):
        return LIVE  # a timeout or a reset is not proof the page is gone
    if response.status_code in GONE_STATUSES:
        return PageCheck(gone=True)
    if not want_image or not response.is_success:
        return LIVE
    return PageCheck(image=og_image(response.text[:MAX_HTML_CHARS], str(response.url)))


class LinkInspector:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        budget_s: float = DEFAULT_BUDGET_S,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self.transport = transport
        self.timeout_s = timeout_s
        self.budget_s = budget_s
        self.max_pages = max_pages

    async def verify(self, plans: list[PackagePlan]) -> list[PackagePlan]:
        """The packages with gone links dropped and missing photos filled from og:image."""
        items = [item for plan in plans for item in plan.items]
        wanted = self._pages(items)
        if not wanted:
            return plans
        checks = await self._check(wanted)
        return [
            replace(plan, items=tuple(self._applied(item, checks) for item in plan.items))
            for plan in plans
        ]

    def _pages(self, items: Iterable[PackageItemPlan]) -> dict[str, bool]:
        """url -> whether its og:image is wanted (some item using it has no photo)."""
        pages: dict[str, bool] = {}
        for item in items:
            for link in item.links:
                if _checked(link.url):
                    pages[link.url] = pages.get(link.url, False) or not item.images
        return dict(list(pages.items())[: self.max_pages])

    async def _check(self, pages: dict[str, bool]) -> dict[str, PageCheck]:
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_s) as http:
            tasks = {
                url: asyncio.create_task(inspect_page(http, url, want_image=want))
                for url, want in pages.items()
            }
            done, pending = await asyncio.wait(tasks.values(), timeout=self.budget_s)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if pending:
            logger.info("link check: %d page(s) too slow, kept as live", len(pending))
        return {url: task.result() for url, task in tasks.items() if task in done}

    @staticmethod
    def _applied(item: PackageItemPlan, checks: dict[str, PageCheck]) -> PackageItemPlan:
        links: tuple[OfferLink, ...] = tuple(
            link for link in item.links if not checks.get(link.url, LIVE).gone
        )
        images = item.images
        if not images:
            found = [checks[link.url].image for link in links if checks.get(link.url, LIVE).image]
            images = tuple(dict.fromkeys(found))[:MAX_IMAGES]
        if links == item.links and images == item.images:
            return item
        return replace(item, links=links, images=images)
