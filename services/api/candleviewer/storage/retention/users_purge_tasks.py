"""Supervised anonymisation of users deleted with `?purge=true` (E42-T10 S13, #965 O6).

Interval loop mirroring `incidents_tasks`: started by the ASGI lifespan only when
`retention_enabled` (`RetentionSchedule.users_purge_jobs()` non-empty), tracked and cancellable
(C-2.18), off the request path. Each run reads the due users in bounded batches
(`MAX_ANONYMISE_BATCH`, at most `MAX_BATCHES_PER_RUN` of them) and anonymises them one at a time,
each in a transaction of its own with `users.anonymise` written ahead (the store's). It logs one
line per batch with its counts and outcome, never an id or a name, and a failure by its class only.
A run ends after a short batch, a batch that anonymised no one (its users were all skipped by the
locked re-check), or the first failure, which the store rolled back; the next run goes on.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

import structlog

from candleviewer.observability.context import spawn
from candleviewer.storage.repositories.user_purge_sqlalchemy import MAX_ANONYMISE_BATCH
from candleviewer.storage.retention.schedule import RetentionSchedule

INTERVAL_SECONDS = 24 * 3600
#: Batches per run; bounds one run, the next run continues the backlog.
MAX_BATCHES_PER_RUN = 20


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Anonymiser(Protocol):  # `SqlAlchemyUserPurgeStore`
    async def due(self, limit: int) -> Sequence[uuid.UUID]: ...

    async def anonymise(self, user_id: uuid.UUID) -> bool: ...


class UsersPurgeTask:
    def __init__(
        self,
        store: _Anonymiser,
        schedule: RetentionSchedule,
        *,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store = store
        self._enabled = bool(schedule.users_purge_jobs())
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        for _ in range(MAX_BATCHES_PER_RUN):
            try:
                due = await self._store.due(MAX_ANONYMISE_BATCH)
            except Exception as exc:  # the loop survives; the class only, never driver text
                logger().error("users_purge_failed", error=type(exc).__name__)
                return
            if not await self._batch(due) or len(due) < MAX_ANONYMISE_BATCH:
                return

    async def _batch(self, due: Sequence[uuid.UUID]) -> bool:
        """Anonymise `due` one user at a time; True if the batch anonymised one or more and none
        failed. Logged once, so a failure never hides the users already anonymised."""
        anonymised = skipped = 0
        for user_id in due:
            try:
                if await self._store.anonymise(user_id):
                    anonymised += 1
                else:
                    skipped += 1
            except Exception as exc:  # rolled back by the store; the next run retries the user
                logger().error(
                    "users_anonymised",
                    anonymised=anonymised,
                    skipped=skipped,
                    outcome="failed",
                    error=type(exc).__name__,
                )
                return False
        logger().info("users_anonymised", anonymised=anonymised, skipped=skipped, outcome="ok")
        return anonymised > 0

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = spawn(self._loop(), name="users-purge")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises
