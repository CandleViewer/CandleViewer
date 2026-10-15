"""Correlation context (E04-T02, US-OBS-003).

The seven correlation fields live in structlog's own contextvars store so the
`merge_contextvars` processor (E04-T01) stamps them on every log line with no
extra wiring. `spawn()` and `run_in_thread()` are the two sanctioned ways to
hop off the current task: both carry the context across, which bare
`asyncio.create_task` (copies, but is banned by Semgrep for app code so the
intent is explicit) and `run_in_executor` / `to_thread` (copies only
via `to_thread`; raw executors do not) cannot guarantee. `thread_future()` is
the narrow exception for a thread whose caller must outlive its own
cancellation (see its docstring).
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
from collections.abc import Callable, Coroutine, Iterator
from concurrent.futures import Executor
from contextlib import contextmanager
from typing import Any, Final

import structlog

CORRELATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "request_id",
        "conn_id",
        "user_id",
        "account_id",
        "symbol",
        "order_link_id",
        "trade_group_id",
    }
)


@contextmanager
def bind_context(**fields: Any) -> Iterator[None]:
    """Bind correlation fields for the duration of the `with` block.

    Unknown field names are rejected (closed set). `None` values are skipped.
    Previous values are restored on exit, so nested binds compose.
    """
    unknown = set(fields) - CORRELATION_FIELDS
    if unknown:
        raise ValueError(f"unknown correlation field(s): {sorted(unknown)}")
    values = {k: str(v) for k, v in fields.items() if v is not None}
    token = structlog.contextvars.bind_contextvars(**values)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**token)


def get_context() -> dict[str, Any]:
    """Current correlation fields (for tests / outbound-request tagging)."""
    ctx = structlog.contextvars.get_contextvars()
    return {k: v for k, v in ctx.items() if k in CORRELATION_FIELDS}


def current_request_id() -> str | None:
    value = get_context().get("request_id")
    return str(value) if value is not None else None


def spawn[T](coro: Coroutine[Any, Any, T], *, name: str) -> asyncio.Task[T]:
    """`create_task` that explicitly runs under a copy of the current context."""
    ctx = contextvars.copy_context()
    return asyncio.get_running_loop().create_task(coro, name=name, context=ctx)


async def run_in_thread[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Thread offload that carries the correlation context (unlike a raw executor)."""
    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: ctx.run(func, *args, **kwargs))


def thread_future[T](func: Callable[..., T], /, *args: Any) -> asyncio.Future[T]:
    """Start `func(*args)` in the default executor under a copy of the current
    context and return the executor's plain `asyncio.Future`: not a coroutine and
    not a Task.

    Only for a caller that holds a lock which must outlive its own cancellation
    until the thread has returned (the audit WAL, #2250): it awaits the future
    through `asyncio.shield` until the future is done. It is a Future rather than a
    Task because event-loop teardown (`asyncio.run`) cancels every Task, and a
    Task wrapper (`spawn(run_in_thread(...))`, `asyncio.to_thread`) would cancel
    the executor future while the thread still runs; the holder would then drop
    the lock early. Nothing cancels this future except whoever holds it. Use
    `run_in_thread` everywhere else."""
    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(ctx.run, func, *args))


def executor_future[T](
    executor: Executor, func: Callable[..., T], /, *args: Any
) -> asyncio.Future[T]:
    """Start `func(*args)` on a caller-owned `executor` under a copy of the current
    context and return the executor's plain `asyncio.Future`.

    For a module that must run CPU work on its own bounded pool instead of the loop's
    shared default executor (the audit chain check, design §16/§17). Like
    `thread_future`, the plain Future can be awaited without cancelling the job, and
    the correlation context is carried into the worker thread."""
    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(executor, functools.partial(ctx.run, func, *args))
