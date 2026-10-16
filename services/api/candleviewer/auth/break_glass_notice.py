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
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

import structlog

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
    async def has_unresolved_break_glass(self) -> bool:
        """Whether any `auth`/`break_glass_used` system event is still unresolved."""
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
        """Read the port once, bounded; never raises except on cancellation."""
        if self._events is None:
            return
        try:
            async with asyncio.timeout(self._timeout_s):
                unresolved = await self._events.has_unresolved_break_glass()
        except Exception as exc:  # TimeoutError included; CancelledError propagates
            self._read_failures += 1
            _log().error(
                "auth.break_glass_state_read_failed",
                error=type(exc).__name__,
                failures=self._read_failures,
            )
            return
        self._unresolved = unresolved

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
