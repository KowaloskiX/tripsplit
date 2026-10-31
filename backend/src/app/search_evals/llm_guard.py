"""Counts LLM calls made while the research runs — the deterministic search must make none.

Every way this codebase reaches a model is patched for the duration: the OpenAI SDK's chat and
responses endpoints (sync and async) and the subprocess the Claude CLI adapters spawn. A call
is counted and refused (it raises), so a regression shows up as a number in the report rather
than a bill.
"""

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn
from unittest import mock


class LlmCallRefused(RuntimeError):
    pass


@dataclass
class LlmCounter:
    calls: int = 0

    def refuse(self, *args: Any, **kwargs: Any) -> NoReturn:
        self.calls += 1
        raise LlmCallRefused("the search eval refuses LLM calls")

    async def refuse_async(self, *args: Any, **kwargs: Any) -> NoReturn:
        self.refuse()


_SYNC_TARGETS = (
    "openai.resources.chat.completions.Completions.create",
    "openai.resources.responses.Responses.create",
)
_ASYNC_TARGETS = (
    "openai.resources.chat.completions.AsyncCompletions.create",
    "openai.resources.responses.AsyncResponses.create",
    "app.ai.claude_cli.spawn_process",
)


@contextmanager
def no_llm() -> Iterator[LlmCounter]:
    counter = LlmCounter()
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(program: Any, *args: Any, **kwargs: Any) -> Any:
        if "claude" in str(program).casefold():
            counter.refuse()
        return await original_spawn(program, *args, **kwargs)

    with ExitStack() as stack:
        for target in _SYNC_TARGETS:
            stack.enter_context(mock.patch(target, counter.refuse))
        for target in _ASYNC_TARGETS:
            stack.enter_context(mock.patch(target, counter.refuse_async))
        stack.enter_context(mock.patch("asyncio.create_subprocess_exec", spawn))
        yield counter
