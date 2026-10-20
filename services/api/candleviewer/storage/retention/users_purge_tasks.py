"""Supervised anonymisation of users deleted with `?purge=true` (E42-T10 S13, #965 O6).

Interval loop mirroring `incidents_tasks`, tracked and cancellable (C-2.18), off the request path.
Unlike the retention tasks it does not follow `retention_enabled`: the purge is a privacy promise,
not optional retention, so the lifespan starts it whenever the store is wired (orchestrator ruling,
2026-10-20), and the task is also the door `DELETE /users/{userId}?purge=true` schedules through,
which refuses while the loop is not running (`PurgeUnavailableError`, UL4-D1).

Each run walks the due users once, oldest date first, in bounded batches (`MAX_ANONYMISE_BATCH`,
at most `MAX_BATCHES_PER_RUN` of them), each read starting after the last user of the one before.
Each user is anonymised in a transaction of its own with `users.anonymise` written ahead (the
store's), which also revokes the user's credentials; a session it revoked then ends on B16 as a
disable's does (`SessionEnder`: sockets closed, `REVOKE` recorded), each bounded and isolated. A
user that fails is rolled back by the store, counted by its error class and passed over, so one
row that keeps failing never holds back the users after it; the next run retries it. A failure
every later user would share ends the run: the audit writer refusing or late, or the store
unreachable. One line per batch with its counts and outcome, never an id, a name or driver text.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import structlog

from candleviewer.observability.context import spawn
from candleviewer.storage.repositories.user_purge import (
    Anonymised,
    DuePurge,
    PurgeAuditUnavailableError,
    PurgeSchedule,
    PurgeUnavailableError,
)
from candleviewer.storage.repositories.user_purge_sqlalchemy import MAX_ANONYMISE_BATCH

INTERVAL_SECONDS = 24 * 3600
#: Batches per run; bounds one run, the next run continues the backlog.
MAX_BATCHES_PER_RUN = 20
#: Bounds each session's end (its socket close and its B16 record), as the disable's steps are.
SESSION_END_TIMEOUT_S = 2.0


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Store(Protocol):  # `SqlAlchemyUserPurgeStore`
    async def schedule(
        self,
        user_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> PurgeSchedule: ...

    async def due(self, limit: int, *, after: DuePurge | None = None) -> Sequence[DuePurge]: ...

    async def anonymise(self, user_id: uuid.UUID) -> Anonymised | None: ...


class SessionEnder(Protocol):  # `user_cascade_wiring.PurgedSessions`
    async def end(self, session_id: uuid.UUID, now: datetime) -> None: ...


def _shared(exc: Exception) -> bool:
    """A failure every later user would share, so the run ends: the audit writer refused the
    record or outlived its bound, or the store is unreachable (a refused or lost connection, a
    timeout). A row's own failure (a constraint, a lock wait) is passed over."""
    lost = getattr(exc, "connection_invalidated", False) is True
    return isinstance(exc, PurgeAuditUnavailableError | OSError) or lost


@dataclass
class _Batch:  # one batch's counts, logged once
    anonymised: int = 0
    skipped: int = 0
    errors: Counter[str] = field(default_factory=Counter)
    sessions_ended: int = 0
    session_errors: Counter[str] = field(default_factory=Counter)
    stopped: bool = False

    def log(self) -> None:
        failed, unended = sum(self.errors.values()), sum(self.session_errors.values())
        outcome = "stopped" if self.stopped else "partial" if failed or unended else "ok"
        (logger().info if outcome == "ok" else logger().error)(
            "users_anonymised",
            anonymised=self.anonymised,
            skipped=self.skipped,
            failed=failed,
            errors=dict(sorted(self.errors.items())),
            sessions_ended=self.sessions_ended,
            sessions_not_ended=unended,
            session_errors=dict(sorted(self.session_errors.items())),
            outcome=outcome,
        )


class UsersPurgeTask:
    def __init__(
        self,
        store: _Store,
        *,
        sessions: SessionEnder,
        interval_s: float = INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        session_end_timeout_s: float = SESSION_END_TIMEOUT_S,
    ) -> None:
        self._store, self._sessions = store, sessions
        self._interval_s = interval_s
        self._sleep = sleep
        self._session_end_timeout_s = session_end_timeout_s
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """True while the loop runs: from `start()` until `stop()` (or a crash of the loop)."""
        return self._task is not None and not self._task.done()

    async def schedule(
        self,
        user_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> PurgeSchedule:
        """S14's door: the store's `schedule`, refused with `PurgeUnavailableError` (nothing
        changed) while this reaper is not running, so no purge is accepted that nothing would run
        (UL4-D1). Raises what the store raises."""
        if not self.running:
            raise PurgeUnavailableError
        return await self._store.schedule(
            user_id, actor_user_id=actor_user_id, request_id=request_id, session_id=session_id
        )

    async def run_once(self) -> None:
        after: DuePurge | None = None
        for _ in range(MAX_BATCHES_PER_RUN):
            try:
                due = await self._store.due(MAX_ANONYMISE_BATCH, after=after)
            except Exception as exc:  # the loop survives; the class only, never driver text
                logger().error("users_purge_failed", error=type(exc).__name__)
                return
            if not await self._batch(due) or len(due) < MAX_ANONYMISE_BATCH:
                return
            after = due[-1]  # the next read starts after it, past whoever failed or was skipped

    async def _batch(self, due: Sequence[DuePurge]) -> bool:
        """Anonymise `due` one user at a time; False once a shared failure ended the run. Logged
        once, so a failure never hides the users already anonymised."""
        batch = _Batch()
        for item in due:
            try:
                done = await self._store.anonymise(item.user_id)
            except Exception as exc:  # rolled back by the store; the next run retries the user
                batch.errors[type(exc).__name__] += 1
                if _shared(exc):
                    batch.stopped = True
                    break
                continue
            if done is None:  # the locked re-check found nothing to do (re-enabled, cancelled)
                batch.skipped += 1
                continue
            batch.anonymised += 1
            await self._end_sessions(done, batch)
        batch.log()
        return not batch.stopped

    async def _end_sessions(self, done: Anonymised, batch: _Batch) -> None:
        """B16 for each session the committed anonymisation revoked, as a disable's (R7): bounded
        and isolated, so one that fails is counted and the rest still end; the row stays revoked."""
        for session_id in done.revoked_session_ids:
            try:
                async with asyncio.timeout(self._session_end_timeout_s):
                    await self._sessions.end(session_id, done.at)
            except Exception as exc:  # a timeout too: the class only
                batch.session_errors[type(exc).__name__] += 1
            else:
                batch.sessions_ended += 1

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._loop(), name="users-purge")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises
