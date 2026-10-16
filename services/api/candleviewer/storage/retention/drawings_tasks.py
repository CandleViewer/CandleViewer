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
from collections.abc import Awaitable, Callable, Sequence
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
#: Batches per run; bounds one run, the next run continues the backlog.
MAX_BATCHES_PER_RUN = 100


@dataclass(frozen=True, slots=True)
class DrawingsMetrics:
    """The three E14-T01 series; the purge task records `purged`, the router the others."""

    batch_ops: BoundedMetric
    conflicts: BoundedMetric
    purged: BoundedMetric
    rows: BoundedMetric  # cv_drawings_rows{tool}: live drawings per tool (set by the purge task)


class _Purger(Protocol):
    async def purge_deleted(self, older_than_days: int, limit: int) -> int: ...

    async def count_live_by_tool(self) -> dict[str, int]: ...


class DrawingsPurgeTask:
    def __init__(
        self,
        repo: _Purger,
        schedule: RetentionSchedule,
        purged: BoundedMetric,
        rows: BoundedMetric,
        tools: Sequence[str],
        *,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repo = repo
        self._enabled = bool(schedule.drawings_jobs())
        self._purged = purged
        self._rows = rows
        self._tools = tuple(tools)  # the closed TOOLS set, injected (storage must not import api)
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        await self._purge()
        await self._sample_rows()  # also the start-up sample: the loop's first run

    async def _sample_rows(self) -> None:
        """Set `cv_drawings_rows{tool}` for the closed tool set; a failure never stops the loop."""
        try:
            counts = await self._repo.count_live_by_tool()
            for tool in self._tools:
                self._rows.labels(tool).set(counts.get(tool, 0))
        except Exception:
            logger().exception("drawings_rows_sample_failed")

    async def _purge(self) -> None:
        # Count and log per batch so a later failure never loses rows already purged.
        try:
            for _ in range(MAX_BATCHES_PER_RUN):
                n = await self._repo.purge_deleted(DRAWINGS_SOFT_DELETE_DAYS, MAX_PURGE_BATCH)
                if n:
                    self._purged.child().inc(n)
                logger().info("drawings_purged", deleted=n)
                if n < MAX_PURGE_BATCH:
                    break
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
