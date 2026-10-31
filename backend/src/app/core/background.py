"""In-process background tasks that outlive the request that started them.

`asyncio` keeps only a WEAK reference to a task, so a fire-and-forget `create_task` can be
garbage-collected mid-flight. This runner holds the strong references, logs failures that
nobody awaits, and can be drained — by tests, and on shutdown.

Deliberately not a queue: one process, a handful of short jobs (package research). When a job
must survive a restart, it moves to `arq` on Redis.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class BackgroundRunner:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn[T](self, job: Coroutine[Any, Any, T], *, name: str) -> asyncio.Task[T]:
        task = asyncio.create_task(job, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._forget)
        return task

    def _forget(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("background task %s failed", task.get_name(), exc_info=error)

    async def drain(self) -> None:
        """Waits for every running task (including ones spawned while waiting)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def cancel_all(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
