"""A local HTTP server for the variant sites: no database, no app, one thread per request.

It wraps the same pure `render()` the FastAPI route uses and keeps a log of every summary and
confirmation it rendered — the eval's independent evidence of what the agent really did.
"""

import threading
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Self, cast
from urllib.parse import parse_qsl, urlsplit

from app.services import demo_supplier_variants as variants
from app.services.demo_supplier import Order


@dataclass(frozen=True, slots=True)
class Rendered:
    variant: str
    page: variants.Page
    order: Order
    total_minor: int


@dataclass
class RenderLog:
    entries: list[Rendered] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, entry: Rendered) -> None:
        with self.lock:
            self.entries.append(entry)

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()

    def of(self, page: variants.Page) -> list[Rendered]:
        with self.lock:
            return [e for e in self.entries if e.page is page]


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    log: RenderLog


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        prefix = variants.VARIANT_BASE_PATH + "/"
        if not parts.path.startswith(prefix):
            self._send(404, variants.render_not_found(), None)
            return
        variant, _, page = parts.path[len(prefix) :].partition("/")
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        cookies = {key: morsel.value for key, morsel in jar.items()}
        answer = variants.render(variant, page, params, cookies)
        if answer.delay_s:
            time.sleep(answer.delay_s)
        if (answer.is_summary or answer.is_confirmation) and answer.order is not None:
            spec = variants.SPECS[variants.Variant(variant)]
            cast(_Server, self.server).log.add(
                Rendered(
                    variant,
                    variants.Page(page.strip("/")),
                    answer.order,
                    variants.summary_total_minor(answer.order, spec),
                )
            )
        cookie = (
            f"{variants.CONSENT_COOKIE}=1; Path={variants.VARIANT_BASE_PATH}; SameSite=Lax"
            if answer.set_consent_cookie
            else None
        )
        self._send(answer.status, answer.html, cookie)

    def _send(self, status: int, html: str, cookie: str | None) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class VariantServer:
    """`with VariantServer() as server: server.url("baseline")` — on 127.0.0.1, a free port."""

    def __init__(self) -> None:
        self.log = RenderLog()
        self._httpd = _Server(("127.0.0.1", 0), _Handler)
        self._httpd.log = self.log
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host!s}:{port}"

    def url(self, variant: str) -> str:
        return f"{self.origin}{variants.VARIANT_BASE_PATH}/{variant}"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
