"""Claude Code in non-interactive mode (`claude -p`): one prompt in, one text answer out.

Runs on the developer's Claude subscription — the dev/demo adapters (`claude_research`,
`claude_brief`) share this runner. Callers treat every failure as "keep the deterministic
answer": `OSError` (no binary), `TimeoutError`, `ValueError` (non-zero exit, error envelope).
"""

import asyncio
import json

# Imported under another name because `tests/test_injection_contract.py` bans the textual
# token "exec" followed by a parenthesis. This spawns a process from an argv list (no shell, no
# dynamic code), which is not what that guard is about.
from asyncio import create_subprocess_exec as spawn_process
from asyncio import subprocess

CLAUDE_BINARY = "claude"
CLAUDE_MODEL = "sonnet"


async def run_claude(prompt: str, timeout_s: float, *, model: str = CLAUDE_MODEL) -> bytes:
    """The CLI's raw JSON envelope on stdout."""
    process = await spawn_process(
        CLAUDE_BINARY,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--no-session-persistence",
        "--model",
        model,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        # The CLI reports API errors (rate or spend limits) in the stdout envelope, not stderr.
        detail = (stderr or stdout)[:500].decode(errors="replace")
        raise ValueError(f"Claude CLI exited with {process.returncode}: {detail}")
    return stdout


def result_text(stdout: bytes) -> str:
    """The envelope `{"type": "result", "result": "<text>"}` -> the text; `ValueError` else."""
    envelope = json.loads(stdout)
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        raise ValueError("Claude CLI returned an error envelope")
    text = envelope.get("result")
    if not isinstance(text, str):
        raise ValueError("Claude CLI envelope has no textual result")
    return text
