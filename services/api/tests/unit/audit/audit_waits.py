"""Waits for the audit unit tests that never read the wall clock (C-13.7; #3654).

`guarded()` awaits an event unless a watched task (a writer's flusher) ends first; then it raises
at once, with that task's failure as the cause, instead of waiting for an event that cannot come
any more."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from candleviewer.observability.context import spawn


class TaskEnded(AssertionError):
    """A watched task ended before the awaited event; what it raised is the `__cause__`."""


async def guarded[T](awaitable: Coroutine[Any, Any, T], *watch: asyncio.Task[Any] | None) -> T:
    """Await `awaitable`, unless a task in `watch` ends first, even before the call: then raise
    `TaskEnded` from what it raised, if anything. The event wins a tie: `awaitable` runs in a task
    `spawn()` starts, whose first step comes before the race is judged, so a flusher that set its
    alarm and died, before the call or inside the wait, counts as the event."""
    tasks = {task for task in watch if task is not None}
    if not tasks:
        return await awaitable
    waiter = spawn(awaitable, name="guarded")
    try:
        await asyncio.wait({waiter, *tasks}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if not waiter.done():
            waiter.cancel()
    if waiter.done():
        return waiter.result()
    ended = next(task for task in tasks if task.done())
    cause = None if ended.cancelled() else ended.exception()
    raise TaskEnded(f"{ended.get_name()} ended before the awaited event") from cause
