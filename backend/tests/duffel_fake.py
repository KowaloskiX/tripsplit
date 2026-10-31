"""A fake Duffel test API for the tests: trimmed recorded answers behind an
`httpx.MockTransport`, every request recorded. Used by `tests/test_duffel*.py`."""

import copy
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "duffel"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def error(code: str, field: str | None, message: str, status: int = 404) -> dict[str, Any]:
    entry: dict[str, Any] = {"code": code, "message": message, "type": "invalid_request_error"}
    if field is not None:
        entry["source"] = {"field": field, "pointer": f"/passengers/0/{field}"}
    return {"errors": [entry], "meta": {"status": status}}


type Handler = Callable[[httpx.Request], httpx.Response | None]


class FakeDuffel:
    """The Duffel test API from fixtures. `override` answers a request first (None = go on)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.offer_request = fixture("offer_request_waw_bcn")
        self.order = fixture("order_hold")
        self.paid = False
        self.override: Handler | None = None

    def shift_to(self, now: datetime) -> None:
        """Moves the recorded timestamps next to `now`: offers live 30 minutes, holds keep
        the price two days and must be paid within three — like the real test API."""
        stamp = "%Y-%m-%dT%H:%M:%SZ"
        for offer in self.offer_request["data"]["offers"]:
            offer["expires_at"] = (now + timedelta(minutes=30)).strftime(stamp)
            terms = offer["payment_requirements"]
            if not terms["requires_instant_payment"]:
                terms["price_guarantee_expires_at"] = (now + timedelta(days=2)).strftime(stamp)
                terms["payment_required_by"] = (now + timedelta(days=3)).strftime(stamp)
        status = self.order["data"]["payment_status"]
        status["price_guarantee_expires_at"] = (now + timedelta(days=2)).strftime(stamp)
        status["payment_required_by"] = (now + timedelta(days=3)).strftime(stamp)

    def bodies(self, method: str, path: str) -> list[Any]:
        return [
            json.loads(r.content)["data"]
            for r in self.requests
            if r.method == method and r.url.path == path
        ]

    def calls(self, method: str, prefix: str) -> int:
        return sum(1 for r in self.requests if r.method == method and r.url.path.startswith(prefix))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.override is not None and (answer := self.override(request)) is not None:
            return answer
        path, method = request.url.path, request.method
        if method == "POST" and path == "/air/offer_requests":
            return httpx.Response(201, json=self.offer_request)
        if method == "GET" and path.startswith("/air/offers/"):
            wanted = path.rsplit("/", 1)[-1]
            for offer in self.offer_request["data"]["offers"]:
                if offer["id"] == wanted:
                    return httpx.Response(200, json={"data": offer})
            return httpx.Response(404, json=error("not_found", None, "Not found"))
        if method == "POST" and path == "/air/orders":
            selected = json.loads(request.content)["data"]["selected_offers"][0]
            for offer in self.offer_request["data"]["offers"]:
                if offer["id"] == selected:  # the order costs what the offer did
                    self.order["data"]["total_amount"] = offer["total_amount"]
                    self.order["data"]["total_currency"] = offer["total_currency"]
            self.order["data"]["offer_id"] = selected
            return httpx.Response(201, json=self.order)
        if method == "GET" and path.startswith("/air/orders/"):
            order = copy.deepcopy(self.order)
            if self.paid:
                order["data"]["payment_status"]["awaiting_payment"] = False
            return httpx.Response(200, json=order)
        if method == "POST" and path == "/air/payments":
            self.paid = True
            return httpx.Response(201, json=fixture("payment"))
        if method == "GET" and path == "/air/airline_initiated_changes":
            return httpx.Response(200, json=fixture("airline_initiated_changes"))
        return httpx.Response(404, json=error("not_found", None, "Not found"))
