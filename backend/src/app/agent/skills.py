"""Per-domain playbooks the planner consults.

Capture the *stable shape* of a supplier site (consent button, guest path, which gates force a
handoff, where the summary page is) — NOT pixel coordinates or task narration. When the agent is
on a host with a matching skill file, its notes are injected into the planner prompt.

Add a site: drop `skills/<host>.md` (e.g. `skills/intercity.pl.md`). Matching is by host suffix,
so `skills/booking.com.md` also covers `secure.booking.com`.
"""

import os
from urllib.parse import urlparse

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


def host_of(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower().lstrip(".")
    return host[4:] if host.startswith("www.") else host


def notes_for(url: str, max_chars: int = 4000) -> str:
    """Return the site playbook text for this URL's host, or the generic default."""
    host = host_of(url)
    if not host or not os.path.isdir(SKILLS_DIR):
        return ""
    files = [f for f in os.listdir(SKILLS_DIR) if f.endswith(".md") and f != "_default.md"]
    exact = f"{host}.md"
    ordered = ([exact] if exact in files else []) + sorted(
        (f for f in files if host.endswith(f[:-3])), key=len, reverse=True
    )
    for name in ordered:
        path = os.path.join(SKILLS_DIR, name)
        if os.path.isfile(path):
            return _read(path, max_chars)
    default = os.path.join(SKILLS_DIR, "_default.md")
    return _read(default, max_chars) if os.path.isfile(default) else ""


def _read(path: str, max_chars: int) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()[:max_chars]
