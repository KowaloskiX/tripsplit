"""`SearchCache`: an in-process TTL cache of supplier search results.

Keyed by (supplier id, `SearchRequest`) — the request is a frozen dataclass, so origin,
destination, dates, party, mode, budget and currency are all part of the key — and an entry
only answers the very adapter instance that produced it (two registries may configure the same
supplier id differently, e.g. another demo URL). A re-generate or
a second trip on the same route within the TTL answers instantly; a cached offer is still
re-quoted before anyone pays, so a few minutes of staleness costs nothing.

Concurrent identical searches share one call (single flight). Empty results are not cached:
an adapter answers [] when its supplier failed, and that must not stick for minutes.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.suppliers.ports import Offer, SearchRequest, SupplierAdapter

type Key = tuple[str, SearchRequest]
type MonotonicClock = Callable[[], float]

DEFAULT_TTL_S = 300.0
MAX_ENTRIES = 256


@dataclass(frozen=True, slots=True)
class _Entry:
    expires_at: float
    adapter: SupplierAdapter
    offers: tuple[Offer, ...]


class SearchCache:
    def __init__(
        self, ttl_s: float = DEFAULT_TTL_S, clock: MonotonicClock = time.monotonic
    ) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._entries: dict[Key, _Entry] = {}
        self._in_flight: dict[tuple[int, SearchRequest], asyncio.Future[list[Offer]]] = {}

    @property
    def enabled(self) -> bool:
        return self.ttl_s > 0

    def get(self, adapter: SupplierAdapter, request: SearchRequest) -> list[Offer] | None:
        key = (adapter.id, request)
        entry = self._entries.get(key)
        if entry is None or entry.adapter is not adapter:
            return None
        if self._clock() >= entry.expires_at:
            del self._entries[key]
            return None
        return list(entry.offers)

    def put(self, adapter: SupplierAdapter, request: SearchRequest, offers: list[Offer]) -> None:
        if not self.enabled or not offers:
            return
        if len(self._entries) >= MAX_ENTRIES:
            self._evict()
        expires_at = self._clock() + self.ttl_s
        self._entries[(adapter.id, request)] = _Entry(expires_at, adapter, tuple(offers))

    def _evict(self) -> None:
        now = self._clock()
        for key in [key for key, entry in self._entries.items() if entry.expires_at <= now]:
            del self._entries[key]
        while len(self._entries) >= MAX_ENTRIES:
            del self._entries[next(iter(self._entries))]

    async def search(self, adapter: SupplierAdapter, request: SearchRequest) -> list[Offer]:
        """The cached offers, or `adapter.search` (shared with an identical one in flight)."""
        if not self.enabled:
            return await adapter.search(request)
        cached = self.get(adapter, request)
        if cached is not None:
            return cached
        key = (id(adapter), request)
        pending = self._in_flight.get(key)
        if pending is not None:
            return list(await asyncio.shield(pending))
        future: asyncio.Future[list[Offer]] = asyncio.get_running_loop().create_future()
        self._in_flight[key] = future
        try:
            offers = await adapter.search(request)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as failure:
            future.set_exception(failure)
            future.exception()  # marks it retrieved when nobody else waits
            raise
        else:
            future.set_result(offers)
            self.put(adapter, request, offers)
            return offers
        finally:
            del self._in_flight[key]

    def clear(self) -> None:
        self._entries.clear()
