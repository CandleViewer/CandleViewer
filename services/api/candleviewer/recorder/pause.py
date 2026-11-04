"""`RecorderPause`: maintenance mode's hold of the recorder (#5629, 24 Sec.13.3).

It is the `RecorderControl` the maintenance controller (`admin.flags.maintenance`) calls with
`keep_recorder = false`. Structural: `recorder` may not import `admin` (CONSTITUTION Sec.3).

* `pause` holds the writer process-wide in one synchronous step (`StreamWriter.hold`), notes the
  hold's start and the sessions live then, and flushes what was queued before it, within
  `flush_timeout_s`. The B11 sessions are untouched: no chart event, no state, no hash.
* `resume` releases the writer in one synchronous step, then writes the held interval as
  `maintenance_pause` gaps (`SessionManager.on_maintenance_pause`), within `gap_timeout_s`.

Both are idempotent and cancel-safe, as the port requires (the controller's effect budget may cut
either, and its next poll calls it again): the synchronous step runs once, a cut flush puts its
batch back, and a held interval stays pending until its gaps are written, which `record_gap`
de-duplicates. Pending intervals are bounded (`MAX_PENDING`); past it the oldest is logged as
critical and dropped.

* `stop` is the runtime's stop step, before the sessions close (C-2.14): the open hold is written
  as gaps up to now, without releasing the writer, and so is every pending interval; one it
  cannot write is logged as critical (`recorder_pause_gap_unpersisted`). A crash writes none: the
  next start's `process_restart` gap, from the session's last event (none was admitted while
  held), covers the hold.

No task is spawned here.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import structlog

from candleviewer.recorder.sessions import LiveSession

#: Held intervals whose gaps are not written yet, at most (one per pause / resume cycle).
MAX_PENDING: Final = 64


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class HoldableWriter(Protocol):
    """What `StreamWriter` gives a hold."""

    def hold(self) -> bool: ...

    def release(self) -> bool: ...

    async def flush_queued(self) -> None: ...


class PauseSessions(Protocol):
    """What `SessionManager` gives a hold."""

    def live_sessions(self) -> tuple[LiveSession, ...]: ...

    async def on_maintenance_pause(
        self, start_us: int, end_us: int, held: Sequence[LiveSession] = ()
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _Held:
    start_us: int
    end_us: int
    sessions: tuple[LiveSession, ...]


class RecorderPause:
    def __init__(
        self,
        writer: HoldableWriter,
        sessions: PauseSessions,
        *,
        now_us: Callable[[], int],
        flush_timeout_s: float,
        gap_timeout_s: float,
    ) -> None:
        """`now_us` is the wall clock in epoch microseconds, the sessions' own."""
        for name, value in (("flush_timeout_s", flush_timeout_s), ("gap_timeout_s", gap_timeout_s)):
            if not 0 < value < float("inf"):
                raise ValueError(f"{name} must be positive and finite")
        self._writer, self._sessions, self._now_us = writer, sessions, now_us
        self._flush_s, self._gap_s = flush_timeout_s, gap_timeout_s
        #: The open hold: its start and the sessions live then; `None` while not held.
        self._open: tuple[int, tuple[LiveSession, ...]] | None = None
        self._pending: deque[_Held] = deque()
        #: One drain at a time: a poll's resume can overlap the shutdown's stop.
        self._drain_lock = asyncio.Lock()

    @property
    def paused(self) -> bool:
        return self._open is not None

    def _queue(self, held: _Held) -> None:
        if len(self._pending) >= MAX_PENDING:
            lost = self._pending.popleft()
            logger().critical(
                "recorder_pause_gap_unpersisted", start_us=lost.start_us, end_us=lost.end_us
            )
        self._pending.append(held)

    async def _drain(self) -> None:
        async with asyncio.timeout(self._gap_s), self._drain_lock:
            while self._pending:
                held = self._pending[0]
                await self._sessions.on_maintenance_pause(held.start_us, held.end_us, held.sessions)
                self._pending.popleft()

    async def pause(self, reason: str) -> None:
        if self._open is None:  # no await from here to the hold: one step
            self._open = (self._now_us(), self._sessions.live_sessions())
            self._writer.hold()
            logger().warning("recorder_paused", reason=reason)
        async with asyncio.timeout(self._flush_s):
            await self._writer.flush_queued()

    async def resume(self, reason: str) -> None:
        if self._open is not None:  # no await from here to the release: one step
            (start_us, held), self._open = self._open, None
            self._writer.release()
            self._queue(_Held(start_us, self._now_us(), held))
            logger().info("recorder_resumed", reason=reason)
        await self._drain()

    async def stop(self) -> None:
        """Shutdown: the open hold (to now, the writer kept held) and every pending interval are
        written as gaps; any left unwritten is logged as critical, then the failure goes on."""
        if self._open is not None:  # no await from here to the queue: one step
            (start_us, held), self._open = self._open, None
            self._queue(_Held(start_us, self._now_us(), held))
            logger().warning("recorder_pause_stopped_held")
        try:
            await self._drain()
        except BaseException:
            for lost in self._pending:
                logger().critical(
                    "recorder_pause_gap_unpersisted", start_us=lost.start_us, end_us=lost.end_us
                )
            self._pending.clear()
            raise
