"""Dedicated, bounded executor for the audit page's chain check (design §16, §17).

Recomputing a page's hashes is CPU work, so it runs off the event loop on its own small
thread pool, not on the loop's default executor, which other modules share. Both the
threads (`workers`) and the jobs submitted and not yet finished (`max_pending`) are
bounded. Past `max_pending` a call is refused at once (`ChainHasherBusy`, answered 503)
instead of queueing.

A worker thread cannot be interrupted. When the awaiting task is cancelled, `run` still
waits for its job to finish before the cancellation goes on, so a caller that holds a slot
for the call (the router's per-user concurrency lease) holds it until the CPU work is over.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from candleviewer.audit.errors import AuditError
from candleviewer.observability.context import executor_future

DEFAULT_WORKERS = 2
DEFAULT_MAX_PENDING = 8


class ChainHasherBusy(AuditError):
    """Every hashing slot is taken: the read fails closed (503) and serves nothing."""

    def __init__(self) -> None:
        super().__init__("audit chain check capacity reached")


class ChainHasher:
    def __init__(
        self, *, workers: int = DEFAULT_WORKERS, max_pending: int = DEFAULT_MAX_PENDING
    ) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cv-audit-hash")
        self._max_pending = max_pending
        self._pending = 0

    @property
    def pending(self) -> int:
        """Jobs submitted and not yet finished, running or queued."""
        return self._pending

    async def run[T](self, fn: Callable[[], T]) -> T:
        if self._pending >= self._max_pending:
            raise ChainHasherBusy
        try:
            job = executor_future(self._pool, fn)
        except RuntimeError:  # the pool is shut down
            raise ChainHasherBusy from None
        self._pending += 1
        job.add_done_callback(self._finished)
        cancel: asyncio.CancelledError | None = None
        while not job.done():
            try:
                await asyncio.wait([job])  # never cancels the job
            except asyncio.CancelledError as exc:
                cancel = cancel or exc  # raised once the thread has returned
        if cancel is not None:
            raise cancel
        if job.cancelled():  # a queued job `shutdown` dropped; its caller was not cancelled
            raise ChainHasherBusy
        return job.result()

    def _finished(self, _job: asyncio.Future[Any]) -> None:
        self._pending -= 1

    def shutdown(self) -> None:
        """Refuse new jobs and drop queued ones, whose callers get `ChainHasherBusy`; a
        running job finishes."""
        self._pool.shutdown(wait=False, cancel_futures=True)
