"""The sidecar's one place that starts asyncio tasks (ADR-0041 section 1).

The API starts its tasks through `candleviewer.observability.spawn`, which the sidecar may not
import (the `independence-backup-sidecar` contract), so `.semgrep/cv-bare-create-task.yml`
exempts this module, and only this one in the package, as it exempts the API's
`observability/context.py` (#3319 ruling 2; a test holds every other `cvbackup` module to no task
creation of its own). What `spawn` guarantees, each tested:

- a strong reference: every task is named and held in a set until it ends, so none is collected
  half-run;
- a bounded set: at most `MAX_TASKS` at once (4 connections, each a job, its peer watch, a hash
  and an append, plus the sweep, fit many times over); past it `spawn` refuses with `TaskLimit`
  and closes the coroutine unstarted;
- a done-callback that retrieves a failure nobody awaited, logs it by its class only, never its
  text (no request reaches here with anything but codes), and records it (`failures`);
- cancellation honoured: a cancelled task leaves the set and is neither logged nor recorded, and
  `uninterrupted`'s caller sees its own cancel at once.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Coroutine
from typing import Any, Final, TypeVar

_T = TypeVar("_T")  # not PEP 695 `[T]`, as in the API's `storage` (Semgrep 1.99.0)
MAX_TASKS: Final = 64
_RUNNING: Final[set[asyncio.Task[Any]]] = set()
_FAILURES: Final[deque[tuple[str, str]]] = deque(maxlen=32)


class TaskLimit(RuntimeError):
    """`MAX_TASKS` tasks are running: nothing more starts."""

    def __init__(self) -> None:
        super().__init__("cvbackup: the task bound is reached")


def running() -> frozenset[asyncio.Task[Any]]:
    """The tasks started here that have not ended."""
    return frozenset(_RUNNING)


def failures() -> tuple[tuple[str, str], ...]:
    """The latest failures nobody was to read, oldest first: `(task name, error class)`."""
    return tuple(_FAILURES)


def spawn(  # noqa: UP047 (see _T)
    work: Coroutine[Any, Any, _T], *, name: str, quiet: bool = False
) -> asyncio.Task[_T]:
    """`work` as a task named `name`, kept until it ends. `quiet`: its failure is the caller's
    to read, never logged or recorded here (a peer's reset while its EOF is watched)."""
    if len(_RUNNING) >= MAX_TASKS:
        work.close()  # never started, so never "never awaited"
        raise TaskLimit
    task = asyncio.get_running_loop().create_task(work, name=name)
    _RUNNING.add(task)

    def settled(done: asyncio.Task[_T]) -> None:
        _RUNNING.discard(done)
        if done.cancelled():
            return
        failure = done.exception()  # retrieved, so asyncio never reports it unread
        if failure is not None and not quiet:
            _FAILURES.append((name, type(failure).__name__))
            logging.getLogger("cvbackup").warning(
                "cvbackup.task_failed name=%s error=%s", name, type(failure).__name__
            )

    task.add_done_callback(settled)
    return task


async def uninterrupted(work: Coroutine[Any, Any, _T], *, name: str) -> _T:  # noqa: UP047 (see _T)
    """`work` run to its end even if the caller is cancelled meanwhile (the caller still sees the
    cancel at once). For steps that must land whole: an append, a rename and its entry."""
    return await asyncio.shield(spawn(work, name=name))
