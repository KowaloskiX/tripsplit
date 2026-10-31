"""`agent-login`: log into a supplier once, by hand, inside the agent's persistent profile.

    AGENT_PROFILE_DIR=var/agent/profile uv run agent-login --url https://www.intercity.pl

Opens a visible Camoufox window on the supplier with the profile in `AGENT_PROFILE_DIR`. Log
in (PKP Intercity, Booking.com...), accept the cookie banner, then close the window. Later
agent runs with the same `AGENT_PROFILE_DIR` start with those cookies, so they skip the login
wall instead of handing it off. The agent never sees the password — you typed it.
"""

import argparse
import contextlib
import os
import sys

from app.agent.browser import Browser, profile_dir_from_env

_POLL_MS = 500


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv("../.env")
    load_dotenv()
    ap = argparse.ArgumentParser(description="Log into a supplier inside the agent profile.")
    ap.add_argument("--url", required=True, help="the supplier page to open")
    args = ap.parse_args()

    profile = profile_dir_from_env()
    if not profile:
        sys.exit("Set AGENT_PROFILE_DIR (e.g. var/agent/profile) — the profile to log into.")
    # The profile only exists for Camoufox; other engines would silently log into nothing.
    os.environ["ENGINE"] = "camoufox"

    browser = Browser(headless=False)
    try:
        browser.start()
        browser.goto(args.url)
        print(f"[login] profile {profile}\n[login] log in, then close the browser window.")
        while browser.browser.pages:
            try:
                browser.browser.pages[0].wait_for_timeout(_POLL_MS)
            except Exception:
                break  # the window was closed mid-wait
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            browser.close()
    print("[login] saved. Agent runs with this AGENT_PROFILE_DIR reuse the session.")


if __name__ == "__main__":
    main()
