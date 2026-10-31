"""The recent supplier API calls, per trip — the live "terminal" of a booking.

Every HTTP call the API suppliers make (Duffel, LiteAPI) is recorded here: method, a path with
every identifier replaced by `{id}` and no query string, the HTTP status, how long it took and
when. The trip it was made for comes from `trip_context`, a context variable the trip services
set around their supplier work — the adapters never learn about trips. Nothing else is kept:
no body, no header, no key, no passenger data.

One process-wide ring buffer: the newest `MAX_CALLS` calls, gone on restart (a terminal, not
an audit log).
"""

import functools
import re
import threading
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Concatenate

MAX_CALLS = 2000
DEFAULT_LIMIT = 50

current_trip: ContextVar[str | None] = ContextVar("supplier_call_trip", default=None)

# A path segment that names something: prefixed ids (off_..., ord_...), anything with a digit
# and at least 6 characters, or long opaque tokens.
_ID_SEGMENT = re.compile(
    r"^(?:[a-z]{2,4}_[A-Za-z0-9]+|(?=.*\d)[A-Za-z0-9_\-]{6,}|[A-Za-z0-9_\-]{20,})$"
)


@dataclass(frozen=True, slots=True)
class SupplierCall:
    supplier_id: str
    method: str
    path: str  # identifiers replaced by "{id}", no query string
    status: int | None  # None = no answer (network error, timeout)
    ms: int
    at: datetime
    trip_id: str | None


def redact_path(path: str) -> str:
    """ "/air/orders/ord_00009hthhsUZ8W4LxQgkjo?x=1" -> "/air/orders/{id}"."""
    bare = path.split("?", 1)[0].split("#", 1)[0]
    if "://" in bare:
        bare = "/" + bare.split("://", 1)[1].partition("/")[2]
    return "/".join(
        "{id}" if segment and _ID_SEGMENT.match(segment) else segment for segment in bare.split("/")
    )


class CallLog:
    def __init__(self, max_calls: int = MAX_CALLS) -> None:
        self._calls: deque[SupplierCall] = deque(maxlen=max_calls)
        self._lock = threading.Lock()

    def record(
        self,
        supplier_id: str,
        method: str,
        path: str,
        status: int | None,
        seconds: float,
        *,
        at: datetime | None = None,
    ) -> None:
        call = SupplierCall(
            supplier_id=supplier_id,
            method=method.upper(),
            path=redact_path(path),
            status=status,
            ms=max(round(seconds * 1000), 0),
            at=at or datetime.now(UTC),
            trip_id=current_trip.get(),
        )
        with self._lock:
            self._calls.append(call)

    def for_trip(self, trip_id: str, limit: int = DEFAULT_LIMIT) -> list[SupplierCall]:
        """The trip's newest calls, oldest first (a terminal reads top to bottom)."""
        with self._lock:
            mine = [call for call in self._calls if call.trip_id == trip_id]
        return mine[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._calls.clear()


CALL_LOG = CallLog()


@contextmanager
def trip_context(trip_id: str) -> Iterator[None]:
    """Supplier calls made inside are recorded for `trip_id`."""
    token = current_trip.set(trip_id)
    try:
        yield
    finally:
        current_trip.reset(token)


def recorded_for_trip[S, **P, R](
    method: Callable[Concatenate[S, str, P], Awaitable[R]],
) -> Callable[Concatenate[S, str, P], Awaitable[R]]:
    """Decorates a service method whose first argument is the trip id: the supplier calls it
    makes are recorded for that trip."""

    @functools.wraps(method)
    async def wrapper(self: S, trip_id: str, /, *args: P.args, **kwargs: P.kwargs) -> R:
        with trip_context(trip_id):
            return await method(self, trip_id, *args, **kwargs)

    return wrapper
