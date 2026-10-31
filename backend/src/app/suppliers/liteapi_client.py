"""A small typed HTTP client for LiteAPI (Nuitee Connect) hotels — https://docs.liteapi.travel.

Two hosts: `api.liteapi.travel` for content and rates, `book.liteapi.travel` for prebook, book,
retrieve and cancel. Every call has one of three outcomes, kept apart on purpose:

- `Ok(data)` — LiteAPI answered with data (`data` member; an empty list for "no availability",
  which LiteAPI reports as a 200 with error code 2001).
- `Err(LiteApiFailure)` — LiteAPI answered and said no (a 4xx or an `error` body): an expired
  offer, an unknown prebook. Only the numeric code and LiteAPI's short description are kept.
- `SupplierUnavailableError` — LiteAPI could not be asked: network, timeout, 5xx or a rate
  limit that outlasted the retries.

Retries with backoff happen only where they are safe: on 429 always (the request was not
processed); on 5xx and network errors only for calls that spend nothing (content, rates,
prebook, retrieve). A booking is never retried — it may have gone through.

The key guard lives here too: a key that is not a SANDBOX key (`sand_...`) is refused unless
live mode was explicitly allowed (`LITEAPI_ALLOW_LIVE=true`), so nothing in this repo books a
real hotel room by accident.
"""

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import SecretStr

from app.core.domain.result import Err, Ok, Result
from app.suppliers.ports import SupplierUnavailableError

logger = logging.getLogger(__name__)

API_URL = "https://api.liteapi.travel/v3.0"
BOOK_URL = "https://book.liteapi.travel/v3.0"
SANDBOX_KEY_PREFIX = "sand_"
DEFAULT_TIMEOUT_S = 30.0
# A multi-hotel rates search waits for many suppliers; a booking confirms with the hotel.
RATES_TIMEOUT_S = 45.0
BOOK_TIMEOUT_S = 90.0
NO_AVAILABILITY = 2001
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_DESCRIPTION = 160

type Json = dict[str, Any]


def check_key(key: str, *, allow_live: bool) -> Result[str, str]:
    """Ok(key) for a usable key; Err(why) otherwise. The reason never contains the key."""
    if not key:
        return Err("the LiteAPI key is empty")
    if key.startswith(SANDBOX_KEY_PREFIX) or allow_live:
        return Ok(key)
    return Err(
        "the LiteAPI key is not a sandbox key (sand_...): it books real rooms with real money; "
        "set LITEAPI_ALLOW_LIVE=true only if that is really meant"
    )


@dataclass(frozen=True, slots=True)
class LiteApiFailure:
    """LiteAPI said no: the HTTP status, its error code and its short description."""

    status: int
    code: int = 0
    description: str = ""

    def describe(self) -> str:
        """Safe for logs and the feed (LiteAPI's descriptions name fields, not values)."""
        text = f"HTTP {self.status}"
        if self.code:
            text += f" — code {self.code}"
        if self.description:
            text += f": {self.description}"
        return text


@dataclass(frozen=True, slots=True)
class Call:
    """One request, for the harness report: no bodies, no ids of people."""

    method: str
    path: str
    status: int
    seconds: float

    def describe(self) -> str:
        return f"{self.method} {self.path} -> {self.status} in {self.seconds:.1f}s"


def failure_of(status: int, payload: Any) -> LiteApiFailure:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return LiteApiFailure(status)
    code = error.get("code")
    description = error.get("description") or error.get("message") or ""
    return LiteApiFailure(
        status=status,
        code=code if isinstance(code, int) else 0,
        description=str(description)[:_MAX_DESCRIPTION],
    )


def outcome_of(status: int, payload: Any) -> Result[Any, LiteApiFailure]:
    """A parsed answer -> Ok(data) / Err(failure). "No availability" is an empty answer."""
    if 200 <= status < 300 and isinstance(payload, dict) and "data" in payload:
        return Ok(payload["data"])
    failure = failure_of(status, payload)
    if failure.code == NO_AVAILABILITY:
        return Ok([])
    return Err(failure)


@dataclass
class LiteApiClient:
    api_key: SecretStr
    allow_live: bool = False
    transport: httpx.AsyncBaseTransport | None = None
    max_retries: int = 2
    backoff_s: float = 0.5
    calls: list[Call] = field(default_factory=list)

    def __post_init__(self) -> None:
        checked = check_key(self.api_key.get_secret_value(), allow_live=self.allow_live)
        if isinstance(checked, Err):
            raise ValueError(checked.error)

    # ---- the endpoints ------------------------------------------------------------------

    async def hotels(
        self, country_code: str, city_name: str, limit: int
    ) -> Result[Any, LiteApiFailure]:
        params = {"countryCode": country_code, "cityName": city_name, "limit": str(limit)}
        return await self._call("GET", API_URL, "/data/hotels", params=params, retry=True)

    async def hotels_near(
        self, latitude: float, longitude: float, radius_m: int, limit: int
    ) -> Result[Any, LiteApiFailure]:
        """Hotels within `radius_m` of a point — for a city LiteAPI names differently."""
        params = {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "radius": str(radius_m),
            "limit": str(limit),
        }
        return await self._call("GET", API_URL, "/data/hotels", params=params, retry=True)

    async def rates(self, body: Json) -> Result[Any, LiteApiFailure]:
        return await self._call(
            "POST", API_URL, "/hotels/rates", body=body, retry=True, timeout_s=RATES_TIMEOUT_S
        )

    async def prebook(self, offer_id: str) -> Result[Any, LiteApiFailure]:
        body = {"offerId": offer_id, "usePaymentSdk": False}
        return await self._call("POST", BOOK_URL, "/rates/prebook", body=body, retry=True)

    async def book(self, body: Json) -> Result[Any, LiteApiFailure]:
        return await self._call(
            "POST", BOOK_URL, "/rates/book", body=body, retry=False, timeout_s=BOOK_TIMEOUT_S
        )

    async def booking(self, booking_id: str) -> Result[Any, LiteApiFailure]:
        return await self._call("GET", BOOK_URL, f"/bookings/{booking_id}", retry=True)

    async def cancel(self, booking_id: str) -> Result[Any, LiteApiFailure]:
        return await self._call("PUT", BOOK_URL, f"/bookings/{booking_id}", retry=False)

    # ---- the plumbing -------------------------------------------------------------------

    async def _call(
        self,
        method: str,
        base: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Json | None = None,
        retry: bool,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> Result[Any, LiteApiFailure]:
        headers = {
            "X-API-Key": self.api_key.get_secret_value(),
            "accept": "application/json",
        }
        attempt = 0
        async with httpx.AsyncClient(transport=self.transport, timeout=timeout_s) as http:
            while True:
                started = time.monotonic()
                try:
                    response = await http.request(
                        method, base + path, params=params, json=body, headers=headers
                    )
                except httpx.HTTPError as exc:
                    if retry and attempt < self.max_retries:
                        attempt += 1
                        await asyncio.sleep(self.backoff_s * attempt)
                        continue
                    raise SupplierUnavailableError(
                        f"LiteAPI {method} {_route(path)}: {type(exc).__name__}"
                    ) from exc
                self.calls.append(
                    Call(method, _route(path), response.status_code, time.monotonic() - started)
                )
                status = response.status_code
                retriable = status == 429 or (retry and status in _RETRY_STATUSES)
                if retriable and attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff_s * attempt)
                    continue
                if status in _RETRY_STATUSES:
                    where = f"{method} {_route(path)}"
                    raise SupplierUnavailableError(f"LiteAPI {where}: HTTP {status}")
                try:
                    payload: Any = response.json()
                except ValueError:
                    payload = None
                outcome = outcome_of(status, payload)
                if isinstance(outcome, Err):
                    logger.info("LiteAPI %s %s: %s", method, _route(path), outcome.error.describe())
                return outcome


def _route(path: str) -> str:
    """`/bookings/OOXZCMgku` -> `/bookings/{id}`: logs and reports carry no booking ids."""
    return "/bookings/{id}" if path.startswith("/bookings/") else path
