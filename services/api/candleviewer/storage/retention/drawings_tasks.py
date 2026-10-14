"""Supervised purge of soft-deleted drawings (E14-T01).

Interval loop mirroring `alert_tasks._Loop`: started by the ASGI lifespan only when
`retention_enabled` (`RetentionSchedule.drawings_jobs()` non-empty), tracked and
cancellable (C-2.18). Each run drains batches until one comes back short. Only counts are
logged — never geometry, labels or ids (E14-T01 Observability).

No tombstone is kept: after the purge a drawing id may be created again, so "ids are never
reused" holds within the retention window only (residual R4 on #357).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import BoundedMetric
from candleviewer.storage.repositories.drawings_sqlalchemy import MAX_PURGE_BATCH
from candleviewer.storage.retention.policy import DRAWINGS_SOFT_DELETE_DAYS
from candleviewer.storage.retention.schedule import RetentionSchedule


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


INTERVAL_SECONDS = 24 * 3600


@dataclass(frozen=True, slots=True)
class DrawingsMetrics:
    """The three E14-T01 series; the purge task records `purged`, the router the others."""

    batch_ops: BoundedMetric
    conflicts: BoundedMetric
    purged: BoundedMetric


class _Purger(Protocol):
    async def purge_deleted(self, older_than_days: int, limit: int) -> int: ...


class DrawingsPurgeTask:
    def __init__(
        self,
        repo: _Purger,
        schedule: RetentionSchedule,
        purged: BoundedMetric,
        *,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repo = repo
        self._enabled = bool(schedule.drawings_jobs())
        self._purged = purged
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        try:
            total = 0
            while True:
                n = await self._repo.purge_deleted(DRAWINGS_SOFT_DELETE_DAYS, MAX_PURGE_BATCH)
                total += n
                if n < MAX_PURGE_BATCH:
                    break
            if total:
                self._purged.child().inc(total)
            logger().info("drawings_purged", deleted=total)
        except Exception:
            logger().exception("drawings_purge_failed")

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = spawn(self._loop(), name="drawings-purge")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
