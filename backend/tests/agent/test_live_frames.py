"""The live preview on engines without a CDP screencast (QA finding 3) — no real browser."""

from pathlib import Path
from typing import Any

from app.agent.browser import Browser


class _FakePage:
    def __init__(self) -> None:
        self.shots: list[dict[str, Any]] = []
        self.waited_ms = 0

    def screenshot(self, *, path: str, **options: Any) -> None:
        self.shots.append(options)
        Path(path).write_bytes(b"\xff\xd8 frame %d" % len(self.shots))

    def wait_for_timeout(self, ms: int) -> None:
        self.waited_ms += ms

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        raise TimeoutError(state)  # a page that never reaches network idle


def _browser(tmp_path: Path) -> tuple[Browser, _FakePage]:
    browser = Browser(headless=True)
    page = _FakePage()
    browser.engine = "camoufox"
    browser.page = page
    browser.live_frame_path = str(tmp_path / "live.jpg")
    return browser, page


def test_frames_are_jpegs_written_atomically_and_rate_limited(tmp_path: Path) -> None:
    browser, page = _browser(tmp_path)
    browser.live_tick()
    browser.live_tick()  # within 300 ms: skipped
    assert len(page.shots) == 1
    assert page.shots[0]["type"] == "jpeg"
    assert (tmp_path / "live.jpg").read_bytes().startswith(b"\xff\xd8")
    assert not (tmp_path / "live.jpg.tmp").exists()
    browser.live_tick(force=True)
    assert len(page.shots) == 2


def test_waiting_and_settling_keep_the_preview_moving(tmp_path: Path) -> None:
    browser, page = _browser(tmp_path)
    browser.idle(0.7)
    assert len(page.shots) >= 2, "a frame every ~300 ms while waiting for approval"
    before = len(page.shots)
    browser.settle(timeout=700)
    assert len(page.shots) - before >= 2, "frames while the page loads, and one when settled"


def test_a_screencast_engine_is_left_alone(tmp_path: Path) -> None:
    browser, page = _browser(tmp_path)
    browser._cdp = object()  # Chromium streams frames itself
    browser.live_tick(force=True)
    assert page.shots == []
