"""Supervised purge of soft-deleted workspaces/layouts plus the users-per-bucket gauge (E15-T01).

Interval loop mirroring `drawings_tasks`/`alert_tasks._Loop`: started by the ASGI lifespan only
when `retention_enabled` (`RetentionSchedule.workspaces_jobs()` non-empty), tracked and
cancellable (C-2.18). Each run drains batches until both statements come back short, capped at
`MAX_BATCHES_PER_RUN`. The purge and the gauge sample fail independently. Only counts are
logged — never names, `pane_config`, `grid_spec` or ids.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

import structlog

from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import BoundedMetric
from candleviewer.storage.repositories.workspaces_sqlalchemy import MAX_PURGE_BATCH
from candleviewer.storage.retention.policy import WORKSPACES_SOFT_DELETE_DAYS
from candleviewer.storage.retention.schedule import RetentionSchedule


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


INTERVAL_SECONDS = 24 * 3600
#: Batches per run; bounds one run, the next run continues the backlog.
MAX_BATCHES_PER_RUN = 100
#: The closed `cv_workspace_users{bucket}` label set (<= MAX_WORKSPACES = 32 live per user).
USER_BUCKETS: Final = ("1", "2-4", "5-8", "9-16", "17-32")
KINDS: Final = ("workspace", "layout")


@dataclass(frozen=True, slots=True)
class WorkspacesMetrics:
    """The E15-T01 series: the purge task records `purged`/`users`, the router the rest."""

    conflicts: BoundedMetric  # cv_workspace_conflicts_total{resource}
    layout_panes: BoundedMetric  # cv_layout_panes (histogram)
    users: BoundedMetric  # cv_workspace_users{bucket}
    purged: BoundedMetric  # cv_workspaces_purged_total{kind}
    request_seconds: BoundedMetric  # cv_workspace_request_seconds{operation}


class _Purger(Protocol):
    async def purge_deleted_counts(self, older_than_days: int, limit: int) -> tuple[int, int]: ...

    async def count_users_by_workspace_bucket(self) -> dict[str, int]: ...


class WorkspacesPurgeTask:
    def __init__(
        self,
        repo: _Purger,
        schedule: RetentionSchedule,
        purged: BoundedMetric,
        users: BoundedMetric,
        *,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repo = repo
        self._enabled = bool(schedule.workspaces_jobs())
        self._purged = purged
        self._users = users
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        await self._purge()
        await self._sample_users()  # also the start-up sample: the loop's first run

    async def _sample_users(self) -> None:
        """Set `cv_workspace_users{bucket}` over the closed set; a failure never stops the loop."""
        try:
            counts = await self._repo.count_users_by_workspace_bucket()
            for bucket in USER_BUCKETS:
                self._users.labels(bucket).set(counts.get(bucket, 0))
        except Exception:
            logger().exception("workspace_users_sample_failed")

    async def _purge(self) -> None:
        # Count and log per batch so a later failure never loses rows already purged.
        try:
            for _ in range(MAX_BATCHES_PER_RUN):
                lay, ws = await self._repo.purge_deleted_counts(
                    WORKSPACES_SOFT_DELETE_DAYS, MAX_PURGE_BATCH
                )
                if lay:
                    self._purged.labels("layout").inc(lay)
                if ws:
                    self._purged.labels("workspace").inc(ws)
                logger().info("workspaces_purged", layouts=lay, workspaces=ws)
                if lay < MAX_PURGE_BATCH and ws < MAX_PURGE_BATCH:
                    break
        except Exception:
            logger().exception("workspaces_purge_failed")

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = spawn(self._loop(), name="workspaces-purge")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
