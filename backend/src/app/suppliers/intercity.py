"""PKP Intercity (e-IC 2.0): stations, connections and price quotes as structured data.

There is no public PKP Intercity API. The e-IC 2.0 web app itself talks JSON to
`api-gateway.intercity.pl/server/public/endpoint/{Pociagi,Sprzedaz}` with no login and no token,
which is what this client uses. Two consequences, both deliberate:

- **Transport is a port.** The gateway sits behind Akamai bot management, so a plain HTTP client
  may be reset or stalled. `BrowserTransport` therefore runs each call as a `fetch()` inside a
  real (Camoufox) page on ebilet.intercity.pl — genuine TLS, cookies and sensor — and stays a JSON
  round trip of ~1 s. `HttpTransport` is the cheap option where the network allows it.
- **Read-only.** We search and quote; buying stays with the booking agent and a human approval.
  This is unofficial use of an internal API: keep the rate low and the purpose a demo.

Verified on 2026-10-31 (Warszawa Centralna -> Praha hl.n.). Field names are Polish because the
API's are; they stop at this module.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol
from urllib.parse import quote

from app.core.domain.bookings import split_party

logger = logging.getLogger(__name__)

GATEWAY = "https://api-gateway.intercity.pl/server/public/endpoint"
STATIONS_ORIGIN = "https://www.intercity.pl"
STATIONS_URL = f"{STATIONS_ORIGIN}/station/get/"
APP_ORIGIN = "https://ebilet.intercity.pl"
APP_VERSION = "1.6.13"
_CLIENT_VERSION = f"{APP_VERSION}_desktop"
_DEVICE_NO = 956

# An online international purchase accepts at most this many passengers; a 6-person request
# answers "No offers fulfil the criteria" (error 254, verified live on intercity.pl). The PKP
# supplier adapter declares it as its `max_party_per_purchase`.
MAX_PASSENGERS_PER_PURCHASE = 5
NO_OFFERS_ERROR = 254

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class Transport(Protocol):
    async def get_json(self, url: str) -> Any: ...

    async def post_json(self, url: str, body: dict[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class Station:
    name: str
    code: int


@dataclass(frozen=True, slots=True)
class TrainLeg:
    category: str  # "EC", "EIC", "IC", "TLK", "EN"
    number: int
    name: str
    departs_at: datetime
    arrives_at: datetime


@dataclass(frozen=True, slots=True)
class Connection:
    legs: tuple[TrainLeg, ...]
    departs_at: datetime
    arrives_at: datetime
    minutes: int

    @property
    def label(self) -> str:
        return " + ".join(f"{leg.category} {leg.number} {leg.name}".strip() for leg in self.legs)


@dataclass(frozen=True, slots=True)
class FareQuote:
    """One fare for one purchase (up to MAX_PASSENGERS_PER_PURCHASE people)."""

    travel_class: int
    total_minor: int  # grosze, for all passengers of this purchase
    passengers: int
    offer_name: str  # "Super Promo International", "eNRT", ...
    refundable: bool
    proposal_code: str  # `kodPropozycji` — the supplier's reference for this exact quote
    valid_until: datetime  # the supplier's own quote expiry


@dataclass(frozen=True, slots=True)
class GroupQuote:
    """The cheapest fare for a whole group, possibly split over several purchases."""

    connection: Connection
    travel_class: int
    offer_name: str
    refundable: bool
    purchases: tuple[FareQuote, ...] = field(default_factory=tuple)

    @property
    def total_minor(self) -> int:
        return sum(purchase.total_minor for purchase in self.purchases)

    @property
    def passengers(self) -> int:
        return sum(purchase.passengers for purchase in self.purchases)

    @property
    def valid_until(self) -> datetime:
        return min(purchase.valid_until for purchase in self.purchases)


def split_group(travellers: int, cap: int = MAX_PASSENGERS_PER_PURCHASE) -> list[int]:
    """As few purchases as possible, as even as possible: 6 -> [3, 3], 11 -> [4, 4, 3]."""
    return split_party(travellers, cap)


def results_url(departure: date, from_code: int, to_code: int, time: str = "06:00") -> str:
    """The deterministic e-IC results page — the booking agent can `goto` it directly."""
    return (
        f"{APP_ORIGIN}/polaczenia-miedzynarodowe?dwyj={departure.isoformat()}"
        f"&swyj={from_code}&sprzy={to_code}&time={quote(time)}"
        "&przy=0&sprzez=&ticket100=1010&ticket50=&polbez=0"
    )


def parse_stations(payload: Any) -> list[Station]:
    return [Station(name=str(item["n"]), code=int(item["h"])) for item in payload or []]


def parse_connections(payload: Any) -> list[Connection]:
    connections = []
    for item in (payload or {}).get("polaczenia", []):
        legs = tuple(
            TrainLeg(
                category=str(train.get("kategoriaPociagu") or ""),
                number=int(train["nrPociagu"]),
                name=str(train.get("nazwaPociagu") or ""),
                departs_at=datetime.strptime(train["dataWyjazdu"], _TIME_FORMAT),
                arrives_at=datetime.strptime(train["dataPrzyjazdu"], _TIME_FORMAT),
            )
            for train in item.get("pociagi", [])
        )
        if not legs:
            continue
        connections.append(
            Connection(
                legs=legs,
                departs_at=datetime.strptime(item["dataWyjazdu"], _TIME_FORMAT),
                arrives_at=datetime.strptime(item["dataPrzyjazdu"], _TIME_FORMAT),
                minutes=int(item.get("czasJazdy") or 0),
            )
        )
    return connections


def parse_fares(payload: Any) -> list[FareQuote]:
    """Fares from a `sprawdzCene` answer; [] when the supplier has no offer (e.g. error 254)."""
    fares = []
    for price in (payload or {}).get("ceny", []):
        if price.get("blad"):
            continue
        fares.append(
            FareQuote(
                travel_class=int(price["klasa"]),
                total_minor=int(price["cena"]),
                passengers=len(price.get("podrozni") or []),
                offer_name=", ".join(
                    sorted({str(o["nazwaOferty"]) for o in price.get("opisyOfert") or []})
                ),
                refundable=bool(price.get("czyPropozycjaZwrotna")),
                proposal_code=str(price.get("kodPropozycji") or ""),
                valid_until=datetime.strptime(price["dataWaznosciPropozycji"], _TIME_FORMAT),
            )
        )
    return fares


# Calls one client has in flight at once: enough to price a search's trains in one round,
# few enough to stay a polite, demo-sized load on an unofficial API.
MAX_CONCURRENT_CALLS = 6


class IntercityClient:
    """Calls may run concurrently (bounded by `max_concurrent`). Station lookups are cached
    for the client's lifetime — station codes do not change between searches."""

    def __init__(self, transport: Transport, max_concurrent: int = MAX_CONCURRENT_CALLS) -> None:
        self.transport = transport
        self._slots = asyncio.Semaphore(max_concurrent)
        self._stations: dict[str, Station | None] = {}

    async def _get(self, url: str) -> Any:
        async with self._slots:
            return await self.transport.get_json(url)

    async def _post(self, url: str, body: dict[str, Any]) -> Any:
        async with self._slots:
            return await self.transport.post_json(url, body)

    async def stations(self, query: str) -> list[Station]:
        return parse_stations(await self._get(f"{STATIONS_URL}?q={quote(query)}"))

    async def station(self, query: str) -> Station | None:
        """The best concrete station for a name. "Warszawa" first answers the aggregate
        "Warszawa (dowolna stacja)", whose code the fare endpoint rejects — skip aggregates."""
        key = query.strip().casefold()
        if key in self._stations:
            return self._stations[key]
        found = await self.stations(query)
        concrete = [station for station in found if "dowolna" not in station.name.lower()]
        candidates = concrete or found
        best = candidates[0] if candidates else None
        if best is not None:  # an unknown name may be a typo fixed in the next search
            self._stations[key] = best
        return best

    async def fares_by_size(
        self, connection: Connection, from_code: int, to_code: int, sizes: Sequence[int]
    ) -> dict[int, list[FareQuote]]:
        """Fares for every distinct purchase size, asked concurrently: 3 + 3 is one call."""
        distinct = sorted(set(sizes))
        answers = await asyncio.gather(
            *(self.fares(connection, from_code, to_code, size) for size in distinct)
        )
        return dict(zip(distinct, answers, strict=True))

    async def connections(self, from_code: int, to_code: int, day: date) -> list[Connection]:
        body = {
            "metoda": "wyszukajPolaczenia",
            "wersja": _CLIENT_VERSION,
            "dataWyjazdu": f"{day.isoformat()} 00:00:00",
            "dataPrzyjazdu": f"{day.isoformat()} 23:59:59",
            "stacjaWyjazdu": from_code,
            "stacjaPrzyjazdu": to_code,
            "czasNaPrzesiadkeMin": 5,
            "czasNaPrzesiadkeMax": 1440,
            "liczbaPrzesiadekMax": 2,
            "stacjePrzez": [],
            "polaczeniaBezposrednie": 0,
            "polaczeniaNajszybsze": 0,
            "liczbaPolaczen": 0,
            "kategoriePociagow": [],
            "kodyPrzewoznikow": [],
            "rodzajeMiejsc": [],
            "typyMiejsc": [],
            "braille": 0,
            "atrybutyHandlowe": [],
            "urzadzenieNr": _DEVICE_NO,
        }
        return parse_connections(await self._post(f"{GATEWAY}/Pociagi", body))

    async def fares(
        self, connection: Connection, from_code: int, to_code: int, passengers: int
    ) -> list[FareQuote]:
        """Fares for ONE purchase. Ask for at most MAX_PASSENGERS_PER_PURCHASE people."""
        if not 1 <= passengers <= MAX_PASSENGERS_PER_PURCHASE:
            raise ValueError(f"one purchase covers 1..{MAX_PASSENGERS_PER_PURCHASE} passengers")
        traveller = {
            "dataUrodzenia": None,
            "podrozZOpiekunem": 0,
            "typOpiekuna": 0,
            "typBiletuOpiekuna": 0,
            "wspolneMiejsce": 0,
        }
        body = {
            "odcinki": [
                {
                    "pociagNr": leg.number,
                    "wyjazdData": leg.departs_at.strftime(_TIME_FORMAT),
                    "stacjaOdKod": from_code,
                    "stacjaDoKod": to_code,
                }
                for leg in connection.legs[:1]
            ],
            "podrozni": [traveller] * passengers,
            "jezyk": "EN",
            "ofertaKod": 1,
            "biletTyp": 4,
            "powrot": False,
            "metoda": "sprawdzCene",
            "wersja": _CLIENT_VERSION,
            "urzadzenieNr": _DEVICE_NO,
        }
        return parse_fares(await self._post(f"{GATEWAY}/Sprzedaz", body))

    async def group_quote(
        self,
        connection: Connection,
        from_code: int,
        to_code: int,
        travellers: int,
        travel_class: int = 2,
        refundable: bool = False,
    ) -> GroupQuote | None:
        """The cheapest matching fare for the whole group, split into allowed purchases.

        None when any purchase of the split has no matching fare (sold out, class missing).
        """
        sizes = split_group(travellers)
        by_size = await self.fares_by_size(connection, from_code, to_code, sizes)
        purchases: list[FareQuote] = []
        for size in sizes:
            matching = [
                fare
                for fare in by_size[size]
                if fare.travel_class == travel_class and fare.refundable == refundable
            ]
            if not matching:
                return None
            purchases.append(min(matching, key=lambda fare: fare.total_minor))
        return GroupQuote(
            connection=connection,
            travel_class=travel_class,
            offer_name=purchases[0].offer_name,
            refundable=refundable,
            purchases=tuple(purchases),
        )


def _api_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "App-Version": APP_VERSION,
    }


class HttpTransport:
    """Plain HTTPS. Cheapest, but Akamai may reset or stall it — prefer BrowserTransport."""

    def __init__(self, timeout_s: float = 15.0) -> None:
        self.timeout_s = timeout_s

    async def get_json(self, url: str) -> Any:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        import httpx

        headers = {**_api_headers(), "Origin": APP_ORIGIN, "Referer": f"{APP_ORIGIN}/"}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()


_FETCH_JS = """async ([url, method, headers, body]) => {
  const response = await fetch(url, {method, headers, body: body === null ? undefined : body});
  return await response.json();
}"""


class BrowserTransport:
    """Each call is a `fetch()` inside a real Camoufox page.

    Station lookup lives on www.intercity.pl and the gateway answers the e-IC app on
    ebilet.intercity.pl, and neither allows the other origin (CORS). So one page per origin is
    opened lazily and reused: after a ~5 s warm-up a call costs one JSON round trip.
    Use as an async context manager.
    """

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._camoufox: Any = None
        self._browser: Any = None
        self._pages: dict[str, Any] = {}
        # Concurrent first calls must not open the same origin's page twice.
        self._page_lock = asyncio.Lock()

    async def __aenter__(self) -> "BrowserTransport":
        from camoufox.async_api import AsyncCamoufox

        # The camoufox package ships without type hints.
        self._camoufox = AsyncCamoufox(headless=self.headless, os="macos")  # type: ignore[no-untyped-call]
        self._browser = await self._camoufox.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._camoufox is not None:
            await self._camoufox.__aexit__(None, None, None)
        self._camoufox = self._browser = None
        self._pages = {}

    async def _page_for(self, url: str) -> Any:
        if self._browser is None:
            raise RuntimeError("BrowserTransport is not open — use `async with`")
        origin = STATIONS_ORIGIN if url.startswith(STATIONS_ORIGIN) else APP_ORIGIN
        if origin in self._pages:
            return self._pages[origin]
        async with self._page_lock:
            if origin not in self._pages:
                page = await self._browser.new_page()
                await page.goto(f"{origin}/", wait_until="domcontentloaded")
                self._pages[origin] = page
        return self._pages[origin]

    async def _fetch(self, url: str, method: str, headers: dict[str, str], body: str | None) -> Any:
        page = await self._page_for(url)
        return await page.evaluate(_FETCH_JS, [url, method, headers, body])

    async def get_json(self, url: str) -> Any:
        return await self._fetch(url, "GET", {"Accept": "application/json"}, None)

    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        return await self._fetch(url, "POST", _api_headers(), json.dumps(body))


class SharedBrowserTransport:
    """One `BrowserTransport` for a whole long-lived process (the API server).

    The browser starts lazily on the first call (a ~5 s warm-up nobody pays at boot) and is
    reused by every later call. Up to `max_concurrent` calls run at once — each is a `fetch()`
    inside the page, and concurrent `page.evaluate`s are safe — so a search can price several
    trains in parallel; 1 serialises them. Opening and discarding the browser is under a lock.
    A failed call closes the browser (unless another call already replaced it) and is retried
    once on a fresh one (a crashed page, an expired Akamai session); a second failure
    propagates to the adapter, which treats it as "could not ask". `close()` belongs in the
    server's shutdown.
    """

    def __init__(
        self,
        factory: Callable[[], BrowserTransport] | None = None,
        *,
        max_concurrent: int = 6,
    ) -> None:
        self._factory = factory or (lambda: BrowserTransport(headless=True))
        self._browser: BrowserTransport | None = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(max_concurrent)

    @property
    def started(self) -> bool:
        return self._browser is not None

    async def _open(self) -> BrowserTransport:
        async with self._lock:
            if self._browser is None:
                browser = self._factory()
                await browser.__aenter__()
                self._browser = browser
            return self._browser

    async def _discard(self, browser: BrowserTransport | None = None) -> None:
        """Closes `browser` if it is still the current one (any current one when None)."""
        async with self._lock:
            if self._browser is None or (browser is not None and self._browser is not browser):
                return
            current, self._browser = self._browser, None
        try:
            await current.__aexit__(None, None, None)
        except Exception:
            logger.warning("closing the PKP browser failed", exc_info=True)

    async def _call(self, operation: Callable[[BrowserTransport], Awaitable[Any]]) -> Any:
        async with self._slots:
            browser = await self._open()
            try:
                return await operation(browser)
            except Exception:
                logger.warning("PKP browser call failed — restarting the browser once")
                await self._discard(browser)
            return await operation(await self._open())

    async def get_json(self, url: str) -> Any:
        return await self._call(lambda browser: browser.get_json(url))

    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        return await self._call(lambda browser: browser.post_json(url, body))

    async def close(self) -> None:
        await self._discard()


def summarize(quotes: Sequence[GroupQuote]) -> list[str]:
    """Human-readable lines for the CLI."""
    lines = []
    for quote_ in quotes:
        split = " + ".join(str(p.passengers) for p in quote_.purchases)
        lines.append(
            f"{quote_.connection.departs_at:%H:%M}->{quote_.connection.arrives_at:%H:%M} "
            f"{quote_.connection.label}: {quote_.total_minor / 100:.2f} PLN for "
            f"{quote_.passengers} ({split}), class {quote_.travel_class}, {quote_.offer_name}, "
            f"valid until {quote_.valid_until:%H:%M:%S}"
        )
    return lines
