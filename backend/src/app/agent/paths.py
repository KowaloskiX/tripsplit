"""Where the agent writes things on disk. One place, env-configurable.

`runs/<run_id>/` holds per-step screenshots, `live.jpg`, `status.json` and `trace.json` —
the backend serves them to the UI as the live preview. `trajectories/` is the replay cache.
"""

import os

_DEFAULT_VAR = os.path.join(os.getcwd(), "var", "agent")


def var_dir() -> str:
    return os.getenv("AGENT_VAR_DIR", _DEFAULT_VAR)


def runs_dir() -> str:
    return os.path.join(var_dir(), "runs")


def run_dir(run_id: str) -> str:
    return os.path.join(runs_dir(), run_id)


def trajectories_dir() -> str:
    return os.path.join(var_dir(), "trajectories")
