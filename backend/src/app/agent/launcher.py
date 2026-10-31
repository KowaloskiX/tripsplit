"""Starting an agent run from the backend: a port (`AgentLauncher`) plus the subprocess adapter.

The agent drives a sync Playwright browser, so it runs in its own process (`app.agent.runner`)
rather than inside the API's event loop. The backend only starts it and then watches the run
directory (`status.json`, `result.json`); the process waits for `approval.json` at the summary.

The vault (traveller names, email) goes to the child in a private temp file — mode 0600 and
OUTSIDE the run directory, because the run directory is what the UI is served from. The file is
deleted as soon as the process exits.
"""

import asyncio
import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

LOG_FILE = "agent.log"
# The child's pid, so a restarted backend can tell an orphaned-but-alive run from a lost one.
PID_FILE = "agent.pid"


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    run_id: str
    url: str
    goal: str
    vault: Mapping[str, str]
    max_steps: int = 40
    headful: bool = False


class RunHandle(Protocol):
    async def wait(self) -> int:
        """Resolve with the exit code once the run is over (and cleaned up)."""
        ...


class AgentLauncher(Protocol):
    async def start(self, spec: LaunchSpec) -> RunHandle: ...


def load_vault_file(path: Path | None) -> dict[str, str]:
    """Flat `key -> value` JSON (e.g. real passenger names for a demo); {} when absent."""
    if path is None or not path.is_file():
        return {}
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items() if value not in (None, "")}


def write_private_json(payload: Mapping[str, str]) -> Path:
    """A 0600 temp file in the system temp dir — never under the served run directory."""
    descriptor, name = tempfile.mkstemp(prefix="tripsplit-vault-", suffix=".json")
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False)
    return Path(name)


class _ProcessHandle:
    def __init__(self, process: asyncio.subprocess.Process, vault: Path, log: IO[bytes]) -> None:
        self._process = process
        self._vault = vault
        self._log = log

    async def wait(self) -> int:
        try:
            return await self._process.wait()
        finally:
            await asyncio.to_thread(_cleanup, self._vault, self._log)


def _cleanup(vault: Path, log: IO[bytes]) -> None:
    vault.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        log.close()


def live_pid(run_dir: Path) -> int | None:
    """The run's agent pid if that process is still alive, else None."""
    try:
        pid = int((run_dir / PID_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:  # alive, owned by someone else
        return pid
    return pid


class PidHandle:
    """Waits on a process this backend did not start (it survived a backend restart).

    There is no exit code for a non-child, so it resolves with -1; `result.json` carries the
    outcome anyway.
    """

    def __init__(self, run_dir: Path, poll_s: float = 1.0) -> None:
        self._run_dir = run_dir
        self._poll_s = poll_s

    async def wait(self) -> int:
        while True:
            if await asyncio.to_thread(live_pid, self._run_dir) is None:
                return -1
            await asyncio.sleep(self._poll_s)


class SubprocessLauncher:
    """`python -m app.agent.runner ... --await-approval` with the backend dir as cwd."""

    def __init__(self, *, backend_dir: Path, var_dir: Path, extra_vault_file: Path | None) -> None:
        self._backend_dir = backend_dir
        self._var_dir = var_dir
        self._extra_vault_file = extra_vault_file

    async def start(self, spec: LaunchSpec) -> RunHandle:
        vault, log = await asyncio.to_thread(self._prepare, spec)
        args = [
            sys.executable,
            "-m",
            "app.agent.runner",
            "--url",
            spec.url,
            "--goal",
            spec.goal,
            "--run-id",
            spec.run_id,
            "--max-steps",
            str(spec.max_steps),
            "--vault",
            str(vault),
            "--json",
            "--await-approval",
        ]
        if spec.headful:
            args.append("--headful")
        # The child must write where the backend reads, whatever its own .env says.
        env = {**os.environ, "AGENT_VAR_DIR": str(self._var_dir)}
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=self._backend_dir,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
        except BaseException:
            await asyncio.to_thread(_cleanup, vault, log)
            raise
        pid_file = self._var_dir / "runs" / spec.run_id / PID_FILE
        await asyncio.to_thread(pid_file.write_text, str(process.pid), "utf-8")
        return _ProcessHandle(process, vault, log)

    def _prepare(self, spec: LaunchSpec) -> tuple[Path, IO[bytes]]:
        run_dir = self._var_dir / "runs" / spec.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        vault = write_private_json({**spec.vault, **load_vault_file(self._extra_vault_file)})
        # Planner logs carry vault KEY placeholders only, never values (see app.agent.vault).
        log = (run_dir / LOG_FILE).open("ab")
        return vault, log
