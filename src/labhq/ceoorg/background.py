"""Work a tool starts and does not wait for: a meeting, a continued conversation.

A tool call has to answer in seconds; these take minutes. The task is kept referenced so it is
not collected midway, and its failure is logged, because nobody awaits it.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_running: set[asyncio.Task[Any]] = set()


def spawn(work: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    task = asyncio.create_task(_logged(work, name), name=name)
    _running.add(task)
    task.add_done_callback(_running.discard)
    return task


async def _logged(work: Coroutine[Any, Any, Any], name: str) -> None:
    try:
        await work
    except Exception:
        logger.exception("background work %s failed", name)


async def settled() -> None:
    """Wait for everything spawned so far; tests use this instead of sleeping."""
    while _running:
        await asyncio.gather(*list(_running), return_exceptions=True)
