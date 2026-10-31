"""Browser launch + page-settle logic.

Camoufox is the stealth engine (Playwright-compatible). We keep a thin wrapper so
the rest of the harness never cares which engine is behind it. Set ENGINE=chromium
or ENGINE=firefox to fall back to vanilla Playwright (e.g. on a locked-down box).
"""

import contextlib
import os
import time
from typing import Any

# How often the live preview gets a new frame on engines without a CDP screencast.
LIVE_FRAME_INTERVAL_S = 0.3


def profile_dir_from_env():
    """`AGENT_PROFILE_DIR`, absolute, or None — Camoufox then starts a throwaway profile."""
    raw = os.getenv("AGENT_PROFILE_DIR", "").strip()
    return os.path.abspath(os.path.expanduser(raw)) if raw else None


class Browser:
    def __init__(self, headless: bool | None = None) -> None:
        self.engine = os.getenv("ENGINE", "camoufox").lower()
        self.headless = headless if headless is not None else os.getenv("HEADLESS", "0") == "1"
        self._ctx = None  # camoufox context manager, if used
        self._pw = None  # playwright, if used
        self.browser = None
        self.page: Any = None
        self._cdp: Any = None  # CDP session for the live screencast
        # If set, the live preview: a CDP screencast on Chromium, `live_tick` screenshots on
        # Camoufox/Firefox (Playwright's sync API is single-threaded, so the runner ticks it
        # between actions and while it waits).
        self.live_frame_path: str | None = None
        self._last_live = 0.0
        # Per-keystroke delay; 0 = instant fill (sites without bot management, per profile).
        self.type_delay_ms = 25

    def start(self):
        if self.engine == "camoufox":
            from camoufox.sync_api import Camoufox

            # humanize=True adds human-like cursor movement; os spoofs the fingerprint. A single
            # OS, not a list: the current browserforge data yields no fingerprint for a list.
            options = {
                "headless": self.headless,
                "humanize": True,
                "os": os.getenv("CAMOUFOX_OS", "macos"),
            }
            profile_dir = profile_dir_from_env()
            if profile_dir:
                # A persistent context reuses the cookies/logins saved by `agent-login`. The
                # launch returns a BrowserContext (not a Browser) that already has a page.
                os.makedirs(profile_dir, exist_ok=True)
                options.update(persistent_context=True, user_data_dir=profile_dir)
            self._ctx = Camoufox(**options)
            self.browser = self._ctx.__enter__()
            pages = getattr(self.browser, "pages", None) if profile_dir else None
            self.page = pages[0] if pages else self.browser.new_page()
        else:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            vw = int(os.getenv("VIEWPORT_W", "1536"))
            vh = int(os.getenv("VIEWPORT_H", "864"))
            if self.engine == "firefox":
                self.browser = self._pw.firefox.launch(headless=self.headless)
                self.page = self.browser.new_page(viewport={"width": vw, "height": vh})
            else:
                # Chromium with light stealth hardening so bot walls (DataDome /
                # Cloudflare) treat it like a normal desktop browser. Enables the
                # CDP screencast used for the embedded live-video preview.
                self.browser = self._pw.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = self.browser.new_context(
                    locale="pl-PL",
                    viewport={"width": vw, "height": vh},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                    ),
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                self.page = context.new_page()
        # Wider desktop viewport so heavy PL e-commerce layouts (price rail, etc.)
        # are fully captured in screenshots. 16:9 to match the preview panel.
        with contextlib.suppress(Exception):
            self.page.set_viewport_size(
                {
                    "width": int(os.getenv("VIEWPORT_W", "1536")),
                    "height": int(os.getenv("VIEWPORT_H", "864")),
                }
            )
        self.page.set_default_timeout(20000)

        # auto-accept JS dialogs (e.g. a demo store's "Product added" alert) so an
        # unhandled dialog can't block the loop
        def _accept_dialog(d):
            with contextlib.suppress(Exception):
                d.accept()

        self.page.on("dialog", _accept_dialog)
        self._start_screencast()
        return self.page

    def _start_screencast(self):
        """Chromium only: stream JPEG frames via CDP to live_frame_path for the
        embedded live-video preview. No-op on Camoufox/Firefox (no CDP screencast)."""
        if not self.live_frame_path or self.engine != "chromium":
            return
        import base64 as _b64

        with contextlib.suppress(Exception):
            self._cdp = self.page.context.new_cdp_session(self.page)

            def _on_frame(params):
                with contextlib.suppress(Exception):
                    tmp = self.live_frame_path + ".tmp"
                    with open(tmp, "wb") as fh:
                        fh.write(_b64.b64decode(params["data"]))
                    os.replace(tmp, self.live_frame_path)
                with contextlib.suppress(Exception):
                    self._cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

            self._cdp.on("Page.screencastFrame", _on_frame)
            self._cdp.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 55,
                    "maxWidth": 1536,
                    "maxHeight": 864,
                    "everyNthFrame": 1,
                },
            )

    def live_tick(self, force: bool = False) -> None:
        """Engines without a screencast: refresh `live.jpg` at most every
        LIVE_FRAME_INTERVAL_S, atomically (tmp + rename) so a reader never sees half a JPEG."""
        if not self.live_frame_path or self._cdp is not None or self.page is None:
            return
        now = time.monotonic()
        if not force and now - self._last_live < LIVE_FRAME_INTERVAL_S:
            return
        self._last_live = now
        tmp = self.live_frame_path + ".tmp"
        with contextlib.suppress(Exception):
            self.page.screenshot(path=tmp, type="jpeg", quality=55, full_page=False)
            os.replace(tmp, self.live_frame_path)

    def idle(self, seconds: float) -> None:
        """Wait `seconds` while keeping the live preview fresh (e.g. awaiting approval)."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            self.live_tick()
            step = min(left, LIVE_FRAME_INTERVAL_S)
            try:
                self.page.wait_for_timeout(int(step * 1000))
            except Exception:
                time.sleep(step)

    def goto(self, url):
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self.settle()

    def settle(self, timeout: int | None = None) -> None:
        """Wait for the page to stop moving: network idle + a short paint delay.
        Ad/tracking-heavy stores never reach true network idle, so cap the wait low
        (SETTLE_MS, default 2.5s) instead of blocking the full timeout every step."""
        timeout = timeout if timeout is not None else int(os.getenv("SETTLE_MS", "2500"))
        deadline = time.monotonic() + timeout / 1000
        # In short slices, so the live preview keeps moving while the page loads.
        while True:
            self.live_tick()
            left_ms = int((deadline - time.monotonic()) * 1000)
            if left_ms <= 0:
                break
            try:
                self.page.wait_for_load_state(
                    "networkidle", timeout=min(left_ms, int(LIVE_FRAME_INTERVAL_S * 1000))
                )
                break
            except Exception:
                continue
        with contextlib.suppress(Exception):
            self.page.wait_for_timeout(300)
        self.live_tick(force=True)

    def screenshot(self, path: str) -> None:
        with contextlib.suppress(Exception):
            self.page.screenshot(path=path, full_page=False)
        self.live_tick(force=True)

    def close(self):
        with contextlib.suppress(Exception):
            if self._ctx is not None:
                self._ctx.__exit__(None, None, None)
            elif self.browser is not None:
                self.browser.close()
        with contextlib.suppress(Exception):
            if self._pw is not None:
                self._pw.stop()
