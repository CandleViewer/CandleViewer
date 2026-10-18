"""Supervised purge of resolved incidents (E42-T05, `21-database-schema.md` Sec.7).

A `resolved` incident is dropped `policy.INCIDENTS_RESOLVED_MONTHS` after its `last_seen_at`;
open and acknowledged rows are kept. Interval loop mirroring `drawings_tasks`: started by the ASGI
lifespan only when `retention_enabled` (`RetentionSchedule.incidents_jobs()` non-empty), tracked
and cancellable (C-2.18). Each run drains batches until one comes back short, at most
`MAX_BATCHES_PER_RUN`; the next run continues the backlog. Only counts are logged, never a title,
a detail or an id, and a failure is logged by class only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog

from candleviewer.observability.context import spawn
from candleviewer.storage.repositories.incidents_sqlalchemy import MAX_PURGE_BATCH
from candleviewer.storage.retention.policy import INCIDENTS_RESOLVED_MONTHS
from candleviewer.storage.retention.schedule import RetentionSchedule

INTERVAL_SECONDS = 24 * 3600
#: Batches per run; bounds one run, the next run continues the backlog.
MAX_BATCHES_PER_RUN = 100


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Purger(Protocol):
    async def purge_resolved(self, older_than_months: int, limit: int) -> int: ...


class IncidentsPurgeTask:
    def __init__(
        self,
        repo: _Purger,
        schedule: RetentionSchedule,
        *,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repo = repo
        self._enabled = bool(schedule.incidents_jobs())
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        # Logged per batch, so a later failure never hides rows already purged.
        try:
            for _ in range(MAX_BATCHES_PER_RUN):
                n = await self._repo.purge_resolved(INCIDENTS_RESOLVED_MONTHS, MAX_PURGE_BATCH)
                logger().info("incidents_purged", deleted=n)
                if n < MAX_PURGE_BATCH:
                    break
        except Exception as exc:  # the loop survives; the class only, never driver text
            logger().error("incidents_purge_failed", error=type(exc).__name__)

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = spawn(self._loop(), name="incidents-purge")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises
