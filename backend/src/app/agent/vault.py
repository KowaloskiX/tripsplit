"""Values the agent may type into supplier forms, addressed by key.

The planner is shown the key NAMES only and emits `{{vault.<key>}}` placeholders; `act.py`
substitutes the values at action time, so traveller data and credentials never reach the LLM.

A vault is built from a flat dict (the caller — a service — assembles it from the trip's
organizer profile) or, for the CLI, from the `AGENT_VAULT_JSON` environment variable.
"""

import json
import os
from typing import Any
from urllib.parse import quote, quote_plus


class Vault:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._flat: dict[str, Any] = {}
        source = data if data is not None else _from_env()
        for key, value in source.items():
            if value not in (None, ""):
                self._flat[key] = value

    def get(self, key: str, default: str = "") -> Any:
        return self._flat.get(key, default)

    def planner_keys(self) -> list[str]:
        """Key NAMES (never values) to advertise to the planner."""
        return sorted(self._flat.keys())

    def lookup(self) -> dict[str, str]:
        """value -> key, to turn a literal the planner typed back into its placeholder."""
        return {str(v): k for k, v in self._flat.items() if len(str(v)) >= 2}

    def mask(self, text: str) -> str:
        """`text` with every vault value replaced by `•••` (traces, logs, reports)."""
        if not text:
            return text
        out = text
        for value in sorted((str(v) for v in self._flat.values()), key=len, reverse=True):
            if len(value) < 2 or (value.isdigit() and len(value) < 5):
                continue  # a party size like "3" is not a secret, and masking it garbles text
            out = out.replace(value, "•••")
            out = out.replace(quote_plus(value), "•••").replace(quote(value), "•••")
        return out


def _from_env() -> dict[str, Any]:
    raw = os.getenv("AGENT_VAULT_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
