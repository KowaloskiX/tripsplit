"""A small typed HTTP client for the Duffel Flights API (https://duffel.com/docs/api/v2).

Three outcomes per call, kept apart on purpose:

- `Ok(data)` — a 2xx; `data` is the response's `data` member.
- `Err(DuffelFailure)` — Duffel answered and said no (4xx): an expired offer, a validation
  error. Only error codes and field names are kept — never Duffel's message, which may echo a
  passenger's value back.
- `SupplierUnavailableError` — Duffel could not be asked: network, timeout, 5xx or a rate
  limit that outlasted the retries.

Retries with backoff happen only where they are safe: on 429 (the request was not processed)
always, on 5xx and network errors only for idempotent calls (GETs and searches) — retrying a
payment that may have gone through could pay twice.

The key guard is here too: a key that is not a TEST key is refused unless live mode was
explicitly allowed (`DUFFEL_ALLOW_LIVE=true`), so nothing in this repo buys a real ticket by
accident.
"""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from app.core.domain.result import Err, Ok, Result
from app.suppliers.ports import SupplierUnavailableError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.duffel.com"
API_VERSION = "v2"
TEST_KEY_PREFIX = "duffel_test_"
LIVE_KEY_PREFIX = "duffel_live_"
DEFAULT_TIMEOUT_S = 30.0
# An offer request waits up to `supplier_timeout` for the airlines, plus our margin.
SEARCH_TIMEOUT_S = 45.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

type Json = dict[str, Any]


def check_key(key: str, *, allow_live: bool) -> Result[str, str]:
    """Ok(key) for a usable key; Err(why) otherwise. The reason never contains the key."""
    if key.startswith(TEST_KEY_PREFIX):
        return Ok(key)
    if key.startswith(LIVE_KEY_PREFIX):
        if allow_live:
            return Ok(key)
        return Err(
            "the Duffel key is a LIVE key (real tickets, real money); set DUFFEL_ALLOW_LIVE=true "
            "only if that is really meant"
        )
    return Err("the Duffel key is not a Duffel access token (duffel_test_...)")


@dataclass(frozen=True, slots=True)
class DuffelFailure:
    """A 4xx from Duffel: the status, its error codes and the fields they point at."""

    status: int
    codes: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()

    def has(self, *codes: str) -> bool:
        return any(code in self.codes for code in codes)

    def describe(self) -> str:
        """Safe for logs and the feed: codes and field names only."""
        parts = [f"HTTP {self.status}"]
        if self.codes:
            parts.append(", ".join(self.codes))
        if self.fields:
            parts.append("fields: " + ", ".join(sorted(set(self.fields))))
        return " — ".join(parts)


def failure_of(status: int, body: object) -> DuffelFailure:
    codes: list[str] = []
    fields: list[str] = []
    errors = body.get("errors") if isinstance(body, dict) else None
    for error in errors if isinstance(errors, list) else []:
        if not isinstance(error, dict):
            continue
        if isinstance(error.get("code"), str):
            codes.append(error["code"])
        source = error.get("source")
        if isinstance(source, dict) and isinstance(source.get("field"), str):
            fields.append(source["field"])
    return DuffelFailure(status=status, codes=tuple(codes), fields=tuple(fields))


class DuffelClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        allow_live: bool = False,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 2,
        backoff_s: float = 0.5,
    ) -> None:
        checked = check_key(api_key.get_secret_value(), allow_live=allow_live)
        if isinstance(checked, Err):
            raise ValueError(checked.error)
        self._key = api_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._max_retries = max_retries
        self._backoff_s = backoff_s

    @property
    def live_mode(self) -> bool:
        return self._key.get_secret_value().startswith(LIVE_KEY_PREFIX)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key.get_secret_value()}",
            "Duffel-Version": API_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def get(
        self, path: str, *, params: Mapping[str, str] | None = None
    ) -> Result[Any, DuffelFailure]:
        return await self._call("GET", path, params=params, idempotent=True)

    async def post(
        self,
        path: str,
        data: Json,
        *,
        params: Mapping[str, str] | None = None,
        idempotent: bool = False,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> Result[Any, DuffelFailure]:
        return await self._call(
            "POST",
            path,
            body={"data": data},
            params=params,
            idempotent=idempotent,
            timeout_s=timeout_s,
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: Json | None = None,
        params: Mapping[str, str] | None = None,
        idempotent: bool,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> Result[Any, DuffelFailure]:
        attempt = 0
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=timeout_s,
            transport=self._transport,
        ) as client:
            while True:
                attempt += 1
                try:
                    response = await client.request(method, path, json=body, params=params)
                except httpx.HTTPError as error:
                    if idempotent and attempt <= self._max_retries:
                        await self._pause(attempt)
                        continue
                    # The exception text is a URL and an errno — no key, no passenger data.
                    raise SupplierUnavailableError(
                        f"Duffel {method} {path}: {type(error).__name__}"
                    ) from error
                status = response.status_code
                retriable = status == 429 or (idempotent and status in _RETRY_STATUSES)
                if retriable and attempt <= self._max_retries:
                    await self._pause(attempt, response.headers.get("retry-after"))
                    continue
                if status >= 500 or status == 429:
                    raise SupplierUnavailableError(f"Duffel {method} {path}: HTTP {status}")
                payload = _json(response)
                if status >= 400:
                    failure = failure_of(status, payload)
                    logger.info("Duffel %s %s refused: %s", method, path, failure.describe())
                    return Err(failure)
                return Ok(payload.get("data") if isinstance(payload, dict) else None)

    async def _pause(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self._backoff_s * 2 ** (attempt - 1)
        if retry_after is not None and retry_after.replace(".", "", 1).isdigit():
            delay = min(float(retry_after), 10.0)
        await asyncio.sleep(delay)


def _json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None
