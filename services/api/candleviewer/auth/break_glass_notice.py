"""Break-glass notice on the WS `system` topic (E09-S11 #2119 slice 6, decision O4).

While an offline break-glass Owner reset is unresolved (the critical `system_events` row
`auth`/`break_glass_used` that slice 3's store writes), a client's FIRST `/ws` authentication
receives one role-neutral `system` notice, reason `auth.break_glass_used`, right after
`auth_ok` (`23-ws-protocol.md` §15.9). It names no user and does not touch order entry.

The gateway's hook is synchronous and argument-free, so `notices()` reads a cached flag and never
does I/O. `start()` answers the `BreakGlassEvents` port once before cv-api serves: the CLI runs
only while cv-api is stopped (run lock, R2b), so a new event can only appear across a restart.
A tracked task then refreshes the flag every `REFRESH_INTERVAL_S`, which picks up a resolution
and recovers from a failed start-up read. Every read is bounded by `READ_TIMEOUT_S`; a failed
one keeps the last state read (never a guessed notice), is counted in `read_failures` and logged
by error class only. `auth` imports no storage driver (ADR-0003), hence the port, implemented
read-only by `SqlAlchemyBreakGlassEvents` in `storage/repositories/break_glass_sqlalchemy.py`.

Every successful read also sets `auth_break_glass_unresolved_events` (how many are unresolved,
0 when none), the series `AuthBreakGlassUsed` pages the Owner on (#2496). A failed read leaves it
as it was. The same refresh reads how many CLI runs `audit_log` holds a record of into
`auth_break_glass_attempts`, which `AuthBreakGlassAttempted` pages on: a run that changed nothing
leaves audit rows and no unresolved event. The two are separate statements with separate
failures, so a broken attempts read cannot silence the unresolved-events page or the notice.

Every failed read is also counted in `auth_break_glass_state_read_failures_total`: a failed read
keeps the last value of both gauges (0 in a fresh process), so without the counter a reader that
cannot read leaves both pages silent with nothing to say so. `AuthBreakGlassStateReadFailing`
raises a ticket on it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

import structlog

from candleviewer.auth.metrics import (
    auth_break_glass_attempts,
    auth_break_glass_state_read_failures_total,
    auth_break_glass_unresolved_events,
)
from candleviewer.observability.context import spawn

#: §15.9 `notice` reason of the break-glass notice (decision R3).
BREAK_GLASS_NOTICE_REASON: Final = "auth.break_glass_used"
REFRESH_INTERVAL_S: Final = 60.0
READ_TIMEOUT_S: Final = 5.0
_MESSAGE: Final = "Break-glass recovery was used on this server; the Owner must review it."


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BreakGlassEvents(Protocol):
    async def unresolved_break_glass_count(self) -> int:
        """How many `auth`/`break_glass_used` system events are still unresolved."""
        ...

    async def break_glass_attempt_count(self) -> int:
        """How many CLI runs `audit_log` has a record of (`auth.break_glass_attempt` rows)."""
        ...


class BreakGlassNotice:
    """The cached unresolved state; `events` is `None` on the fake backend (nothing to read)."""

    def __init__(
        self,
        events: BreakGlassEvents | None,
        *,
        interval_s: float = REFRESH_INTERVAL_S,
        timeout_s: float = READ_TIMEOUT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._events = events
        self._interval_s = interval_s
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._unresolved: bool | None = None  # None until a read succeeds
        self._read_failures = 0
        self._task: asyncio.Task[None] | None = None

    @property
    def unresolved(self) -> bool | None:
        """The last state read; `None` while no read has succeeded."""
        return self._unresolved

    @property
    def read_failures(self) -> int:
        return self._read_failures

    async def refresh(self) -> None:
        """Read each count once, bounded; never raises except on cancellation."""
        if self._events is None:
            return
        unresolved = await self._read("unresolved", self._events.unresolved_break_glass_count)
        if unresolved is not None:
            self._unresolved = unresolved > 0
            auth_break_glass_unresolved_events.set(unresolved)
        attempts = await self._read("attempts", self._events.break_glass_attempt_count)
        if attempts is not None:
            auth_break_glass_attempts.set(attempts)

    async def _read(self, series: str, count: Callable[[], Awaitable[int]]) -> int | None:
        """One bounded read: its count, or `None` after counting and logging the failure."""
        try:
            async with asyncio.timeout(self._timeout_s):
                return await count()
        except Exception as exc:  # TimeoutError included; CancelledError propagates
            self._read_failures += 1
            auth_break_glass_state_read_failures_total.inc()
            _log().error(
                "auth.break_glass_state_read_failed",
                series=series,
                error=type(exc).__name__,
                failures=self._read_failures,
            )
            return None

    def notices(self) -> list[dict[str, object]]:
        """The gateway's first-`auth_ok` hook: one notice while unresolved. No I/O."""
        if not self._unresolved:
            return []
        return [
            {
                "kind": "notice",
                "severity": "critical",
                "message": _MESSAGE,
                "reason": BREAK_GLASS_NOTICE_REASON,
            }
        ]

    async def start(self) -> None:
        """Read once before serving, then refresh every `interval_s` (idempotent)."""
        if self._events is None or self._task is not None:
            return
        await self.refresh()
        self._task = spawn(self._run(), name="break-glass-notice-refresh")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises

    async def _run(self) -> None:
        while True:
            await self._sleep(self._interval_s)
            await self.refresh()
