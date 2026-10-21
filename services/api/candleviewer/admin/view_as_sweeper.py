"""The view-as sweeper (#3085): the server-side ends that no request makes (22 "View-as session").

One tick, at the auth clock's `now`: first the due rows (`list_view_as_due`), where a pending end's
`admin.view_as_ended` is written late (`recorded_late`) once the end's own record can no longer land
(`ViewAsService.end_record_bound` and `WRITE_MARGIN` after its stamp: an earlier late write could
race it), and an unended context ends `expired` from `expires_at` on, else `session_ended` (a
revoked, absolute-expired or orphaned rotated session); then the eligibility pass
(`list_live_view_as`, unrevoked rows), where each live context is evaluated as a request's would be,
so a viewer who lost `users:write` or a target now an Owner, disabled or gone ends within a tick.
Each read and each row's step is bounded, a read to `limit` rows, so a backlog drains over ticks; a
tick never ends the loop: a failure is logged, a row's by its context id and never its session id,
and retried at the next tick. It ticks when started, so a restart sees every pending end, then every
`interval_s`; a stop cancels it, and an end it made has handed its record to the app's tracker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import structlog

from candleviewer.admin.audited import audit_exempt, audited
from candleviewer.admin.view_as import ViewAsService
from candleviewer.auth.metrics import auth_view_as_pending_end_rows
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsSessionStore, ViewAsState
from candleviewer.observability.context import spawn

STEP_TIMEOUT_S: Final = 10.0  # bounds one read or one row's step; past it, the next tick retries
LIST_LIMIT: Final = 100  # the rows one list read returns: a backlog drains over ticks
WRITE_MARGIN: Final = timedelta(seconds=30)  # stamp-to-write gap: the store's statement bound


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _context(row: SessionRecord) -> str | None:
    return None if row.view_as is None else str(row.view_as.context_id)


async def _bounded[T](step: Awaitable[T], **where: str | None) -> T | None:
    """`step` within `STEP_TIMEOUT_S`; a failure, a timeout too, is logged by `where` (a read, or
    a row's context id, never its session id) and is `None`: the next tick tries it again."""
    try:
        async with asyncio.timeout(STEP_TIMEOUT_S):
            return await step
    except Exception as exc:
        _log().error("admin.view_as.sweep_failed", error=type(exc).__name__, **where)
        return None


class ViewAsSweeper:
    def __init__(
        self,
        service: ViewAsService,
        store: ViewAsSessionStore,
        *,
        clock: Callable[[], datetime],  # the auth clock, the service's
        interval_s: float,
        rotated_grace: timedelta,
        limit: int = LIST_LIMIT,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        pending: Callable[[float], None] = auth_view_as_pending_end_rows.set,
    ) -> None:
        self._service, self._store, self._clock, self._sleep = service, store, clock, sleep
        self._interval_s, self._grace, self._limit = interval_s, rotated_grace, limit
        self._pending = pending
        self._quiet = service.end_record_bound + WRITE_MARGIN  # an end's own record lands by then
        #: When this sweeper ended a context: an expired end's `ended_at` is `expires_at`, which
        #: can be long before the end's own record was handed over. Kept for `_quiet`.
        self._ended: dict[UUID, datetime] = {}
        self._task: asyncio.Task[None] | None = None

    @audited("admin.view_as_ended")
    async def tick(self) -> None:
        """One sweep (the module docstring). Raises on cancellation, or if the clock does."""
        now = self._clock()
        self._ended = {cid: at for cid, at in self._ended.items() if now < at + self._quiet}
        listed = self._store.list_view_as_due(now=now, rotated_grace=self._grace, limit=self._limit)
        due = await _bounded(listed, read="due")
        if due is not None:
            self._pending(sum(row.view_as is not None and row.view_as.end_pending for row in due))
        for row in due or ():
            await _bounded(self._due(row, now), context_id=_context(row))
        live = await _bounded(self._store.list_live_view_as(limit=self._limit), read="live")
        for row in live or ():
            await _bounded(self._service.evaluate(row, now=now), context_id=_context(row))

    async def _due(self, row: SessionRecord, now: datetime) -> None:
        state = row.view_as
        if state is None:
            return
        if state.ended_at is not None:
            if now >= self._quiet_from(state):
                await self._service.write_end_record(row, late=True)  # logs its own failure
            return
        expired = now >= state.expires_at
        if not (expired or row.is_revoked or row.is_absolute_expired(now=now)):
            return  # not due after all: a live session's context is the eligibility pass's
        reason = ViewAsEndReason.EXPIRED if expired else ViewAsEndReason.SESSION_ENDED
        if await self._service.end(row, reason=reason, now=now):
            self._ended[state.context_id] = now

    def _quiet_from(self, state: ViewAsState) -> datetime:
        """When the end's own record can no longer land: `_quiet` (the record bound, and the margin
        for the write) after the latest of `ended_at`, `cleared_at` (a leave ends and clears in one
        write) and this sweeper's own end, each stamped before its write. A write slower than the
        margin can still race its record: only `recorded_late` is then wrong (it is keyed)."""
        written = (state.ended_at, state.cleared_at, self._ended.get(state.context_id))
        return max(at for at in written if at is not None) + self._quiet

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:  # outside any step (the clock): one bad tick ends no loop
                _log().error("admin.view_as.tick_failed", error=type(exc).__name__)
            await self._sleep(self._interval_s)

    @audit_exempt("lifecycle")
    def start(self) -> None:
        """Tick now, then every `interval_s`, on a tracked task (idempotent)."""
        if self._task is None:
            self._task = spawn(self._loop(), name="view-as-sweeper")

    @audit_exempt("lifecycle")
    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises
