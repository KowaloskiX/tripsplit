"""The API server's one PKP browser: lazy start, reuse, one restart on failure, close."""

import asyncio
from typing import Any

import pytest

from app.suppliers.intercity import BrowserTransport, SharedBrowserTransport
from app.suppliers.providers import pkp_transport, shared_browser_transport


class FakeBrowser(BrowserTransport):
    """Answers without Camoufox; `failures` calls raise before it starts answering."""

    def __init__(self, log: list[str], failures: int = 0) -> None:
        super().__init__(headless=True)
        self.log = log
        self.failures = failures
        self.in_flight = 0

    async def __aenter__(self) -> "FakeBrowser":
        self.log.append("open")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.log.append("close")

    async def get_json(self, url: str) -> Any:
        self.in_flight += 1
        try:
            assert self.in_flight == 1, "calls must be serialised"
            await asyncio.sleep(0)
            if self.failures:
                self.failures -= 1
                raise RuntimeError("Akamai reset")
            return {"url": url}
        finally:
            self.in_flight -= 1

    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        return {"url": url, "body": body}


async def test_starts_lazily_and_reuses_one_browser() -> None:
    log: list[str] = []
    shared = SharedBrowserTransport(lambda: FakeBrowser(log), max_concurrent=1)
    assert not shared.started and log == []
    answers = await asyncio.gather(*(shared.get_json(f"u{n}") for n in range(5)))
    assert [a["url"] for a in answers] == [f"u{n}" for n in range(5)]
    assert await shared.post_json("p", {"a": 1}) == {"url": "p", "body": {"a": 1}}
    assert log == ["open"]
    await shared.close()
    assert log == ["open", "close"] and not shared.started
    await shared.close()  # idempotent
    assert log == ["open", "close"]


async def test_a_failed_call_restarts_the_browser_once() -> None:
    log: list[str] = []
    browsers = iter([FakeBrowser(log, failures=1), FakeBrowser(log)])
    shared = SharedBrowserTransport(lambda: next(browsers))
    assert await shared.get_json("u") == {"url": "u"}
    assert log == ["open", "close", "open"]


async def test_a_second_failure_propagates() -> None:
    log: list[str] = []
    shared = SharedBrowserTransport(lambda: FakeBrowser(log, failures=1))
    with pytest.raises(RuntimeError, match="Akamai"):
        await shared.get_json("u")


def test_transport_is_selectable() -> None:
    assert pkp_transport("browser") is shared_browser_transport()
    assert not isinstance(pkp_transport("http"), SharedBrowserTransport)
