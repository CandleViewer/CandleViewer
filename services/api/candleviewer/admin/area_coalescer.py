"""Window coalescing of the admin-area read audit record (#5331, E42-T01 write policy).

`admin_area` writes `admin.area_entered` ahead of every `/admin/*` request. A page that polls
(a 2 s overview, a job poll) would flood the append-only, hash-chained log (C-2.9, C-12.8). This
component lets the guard skip the DUPLICATE record of a repeated safe read, and nothing else:

* Only an allowed `GET`/`HEAD` with a session is ever coalesced. A mutation, a denial and a
  request without a session are written ahead one per request, as before.
* Key: (actor, subject, session, method, route template, ip, last step-up). The first read of a
  key writes its row as before and opens a fixed window of `window_s` seconds anchored at that
  write. Later reads of the key inside the window write nothing and are counted. A new IP, a new
  step-up, entering or leaving view-as, or HEAD instead of GET is another key: a fresh row.
* A row is never updated (C-5.7). The count of a closed window rides the NEXT opening row of its
  key as `after_state.prior_window = {reads, first_at, last_at}` (`reads` includes the opening
  read). With no next row, `flush_due` writes one summary row (`reason=coalesced_summary`,
  `after_state = {route, reads, window_started_at, last_read_at, window_s}`) once the window is
  `SUMMARY_GRACE_S` over. A window of one read needs no summary. The summary's actor is the
  session's own actor (not a system actor), and it has no request id.
* A denial writes its own row and CLOSES the key's window, so the next allowed read writes a full
  row, in order after the denial; the closed window's count still rides that row.
* Fail closed: a coalesced read is served without its own row only while `ready()` (the
  `app._audit_ready` predicate) holds; otherwise the window closes and the read takes the full
  write path (503 if the writer is down), exactly as without coalescing.
* Concurrency: reads that race an opening write each write their own row (errs toward more rows);
  when their windows meet, the counts are merged, never overwritten or dropped.
  A failed opening write opens no window and gives the closed window's count back.
* `window_s = 0` is the escape hatch: nothing is coalesced and no marker is added.

State is bounded (C-2.18): `tracked_keys` windows in an LRU map holding ints, timestamps and the
actor's ids; no path parameters, query strings or tokens. At the cap the oldest window is evicted,
its summary written first; if that write fails nothing is evicted and the request is recorded
without opening a window (never fewer rows). The map is in process (single process, ADR-0004): a
restart starts empty, so the next read writes a fresh row. A graceful stop runs `drain()` (bounded)
to write pending summaries; a crash loses only the COUNT of the open windows, whose first row is
durable (threat model AD-R01 residual).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog

from candleviewer.admin.audited import audit_exempt, audited
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.context import spawn

AREA_ENTERED: Final = "admin.area_entered"
SUMMARY_REASON: Final = "coalesced_summary"
OBJECT_KIND: Final = "admin_route"
SAFE_METHODS: Final = frozenset({"GET", "HEAD"})
TRACKED_KEYS: Final = 4096
SUMMARY_GRACE_S: Final = 30.0
DRAIN_TIMEOUT_S: Final = 5.0
FLUSH_TICK_S: Final = 30.0

type Key = tuple[Any, ...]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Emit(Protocol):
    # A read-only callable property, so writers with named keyword-only parameters satisfy it.
    @property
    def emit(self) -> Callable[..., Awaitable[None]]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _Window:
    actor_label: str
    actor_user_id: uuid.UUID
    actor_ip: str | None
    session_id: uuid.UUID | None
    route: str
    opened: float  # monotonic
    first_at: datetime
    last_at: datetime
    reads: int = 1
    closed: bool = False

    @audit_exempt("read")
    def prior(self) -> dict[str, Any]:
        return {
            "reads": self.reads,
            "first_at": self.first_at.isoformat(),
            "last_at": self.last_at.isoformat(),
        }


class AreaEntryCoalescer:
    def __init__(
        self,
        window_s: int,
        emitter: _Emit,
        *,
        ready: Callable[[], bool],
        tracked_keys: int = TRACKED_KEYS,
        monotonic: Callable[[], float],
        wall: Callable[[], datetime] = _utc_now,
        grace_s: float = SUMMARY_GRACE_S,
    ) -> None:
        self.window_s = window_s
        self._emitter, self._ready = emitter, ready
        self._cap, self._mono, self._wall, self._grace_s = tracked_keys, monotonic, wall, grace_s
        self._windows: OrderedDict[Key, _Window] = OrderedDict()
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    @audit_exempt("read")
    def enabled(self) -> bool:
        return self.window_s > 0

    def __len__(self) -> int:
        return len(self._windows)

    @audit_exempt("read")
    def eligible(self, method: str, session_id: uuid.UUID | None) -> bool:
        return self.enabled and method.upper() in SAFE_METHODS and session_id is not None

    # -- the guard's side -------------------------------------------------------------------

    @audit_exempt("caller_audits")
    def coalesce(self, key: Key) -> bool:
        """True when this read is counted into the key's open window and needs no row. A closed,
        expired or not-ready window is left for the full write path."""
        win = self._windows.get(key)
        if win is None or win.closed:
            return False
        if self._mono() - win.opened >= self.window_s:
            return False
        if not self._ready():  # fail closed: this read must write (and fail) like any other
            win.closed = True
            return False
        win.reads += 1
        win.last_at = self._wall()
        self._windows.move_to_end(key)
        return True

    @audit_exempt("caller_audits")
    def close(self, key: Key) -> None:
        """A denial: the key's next allowed read writes a full row."""
        win = self._windows.get(key)
        if win is not None:
            win.closed = True

    @audit_exempt("caller_audits")
    def take_prior(self, key: Key) -> _Window | None:
        """Take the key's window ahead of a full write; its count (if any read was coalesced)
        rides that row. Give it back with `restore` if the write fails."""
        return self._windows.pop(key, None)

    @audit_exempt("caller_audits")
    def restore(self, key: Key, win: _Window | None) -> None:
        """Give back a taken window whose count was not carried. If the key was reopened
        meanwhile, its reads are folded into the live window (never dropped)."""
        if win is None:
            return
        live = self._windows.get(key)
        if live is None:
            win.closed = True
            self._windows[key] = win
        else:
            self._merge(live, win)

    def _put_back_oldest(self, key: Key, win: _Window) -> None:
        """Return a popped window whose summary was not written, at the oldest end; if the key
        was reopened meanwhile its reads are folded into the live window."""
        live = self._windows.get(key)
        if live is None:
            self._windows[key] = win
            self._windows.move_to_end(key, last=False)
        else:
            self._merge(live, win)

    @staticmethod
    def _merge(live: _Window, other: _Window) -> None:
        """Fold `other`'s reads into `live`. Both counts include one opening read, whose row was
        written, so only `other`'s coalesced reads are added: reads stay conserved."""
        live.reads += max(other.reads - 1, 0)
        live.first_at = min(live.first_at, other.first_at)
        live.last_at = max(live.last_at, other.last_at)

    @staticmethod
    @audit_exempt("read")
    def prior_state(win: _Window | None) -> dict[str, Any] | None:
        return win.prior() if win is not None and win.reads > 1 else None

    @audited("admin.area_entered")
    async def open(self, key: Key, win: _Window) -> bool:
        """Open the window of a row the writer accepted. False (no window) when the map is full
        and its oldest window's summary could not be written: the caller records every request."""
        while key not in self._windows and len(self._windows) >= self._cap:
            old_key, old = self._windows.popitem(last=False)  # out first, then written
            try:
                written = await self._summarise(old)
            except BaseException:
                self._put_back_oldest(old_key, old)
                raise
            if not written:
                self._put_back_oldest(old_key, old)
                return False
        live = self._windows.get(key)
        if live is None:
            self._windows[key] = win
        else:  # a racing first read opened it first: merge, never overwrite its count
            self._merge(live, win)
        self._windows.move_to_end(key)
        return True

    @audit_exempt("wiring")
    def new_window(
        self, *, actor_label: str, actor_user_id: uuid.UUID, ip: str | None,
        session_id: uuid.UUID | None, route: str,
    ) -> _Window:  # fmt: skip
        now = self._wall()
        return _Window(actor_label, actor_user_id, ip, session_id, route, self._mono(), now, now)

    # -- summaries ----------------------------------------------------------------------------

    async def _summarise(self, win: _Window) -> bool:
        """Write the closed window's summary row; True when written or none is owed."""
        if win.reads <= 1:
            return True
        win_reads, last = win.reads, win.last_at
        try:
            await self._emitter.emit(
                AREA_ENTERED,
                actor_label=win.actor_label,
                actor_user_id=win.actor_user_id,
                actor_ip=win.actor_ip,
                session_id=win.session_id,
                object_kind=OBJECT_KIND,
                object_id=win.route,
                outcome=AuditOutcome.SUCCESS,
                severity=Severity.INFO,
                reason=SUMMARY_REASON,
                after_state={
                    "route": win.route,
                    "reads": win_reads,
                    "window_started_at": win.first_at.isoformat(),
                    "last_read_at": last.isoformat(),
                    "window_s": self.window_s,
                },
                request_id=None,
            )
        except Exception as exc:  # the count stays for the next tick
            _log().warning("admin.area_coalesce.summary_failed", error=type(exc).__name__)
            return False
        return True

    @audited("admin.area_entered")
    async def flush_due(self) -> int:
        """Summaries for windows `grace_s` past their end; one-read windows are just forgotten.
        Returns the number of summaries written."""
        now, written = self._mono(), 0
        for key, win in list(self._windows.items()):
            if now - win.opened < self.window_s + self._grace_s:
                continue
            if self._windows.get(key) is not win:
                continue  # taken by a full write meanwhile
            del self._windows[key]
            if win.reads > 1:
                try:
                    ok = await self._summarise(win)
                except BaseException:  # a stop cancelling mid-write: the count is not lost
                    self.restore(key, win)
                    raise
                if ok:
                    written += 1
                else:
                    self.restore(key, win)
        return written

    @audited("admin.area_entered")
    async def drain(self, timeout_s: float = DRAIN_TIMEOUT_S) -> int:
        """At shutdown: every pending summary, whatever the window, within `timeout_s`. A write
        in flight is waited for, never cancelled mid-append. Returns the windows still owing one."""
        wins = [(k, w) for k, w in self._windows.items() if w.reads > 1]
        for key, _ in wins:
            self._windows.pop(key, None)
        pending: dict[Key, _Window] = dict(wins)
        task = spawn(self._drain(pending), name="admin-area-coalesce-drain")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        done, _ = await asyncio.wait({task}, timeout=timeout_s)
        if not done:
            _log().warning("admin.area_coalesce.drain_incomplete", windows=len(pending))
            return len(pending)
        return len(pending)

    async def _drain(self, pending: dict[Key, _Window]) -> None:
        for key in list(pending):
            if await self._summarise(pending[key]):
                del pending[key]


class AreaCoalescerFlushTask:
    """The supervised flush cadence (C-2.18), started and stopped by the ASGI lifespan: a
    `flush_due` tick every `interval_s`; `stop()` cancels the loop, then drains."""

    def __init__(
        self,
        coalescer: AreaEntryCoalescer,
        *,
        interval_s: float = FLUSH_TICK_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._coalescer, self._interval_s, self._sleep = coalescer, interval_s, sleep
        self._task: asyncio.Task[None] | None = None

    @property
    @audit_exempt("lifecycle")
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @audit_exempt("lifecycle")
    def start(self) -> None:
        if self._task is None and self._coalescer.enabled:
            self._task = spawn(self._loop(), name="admin-area-coalesce-flush")

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._interval_s)
            await self.run_once()

    @audited("admin.area_entered")
    async def run_once(self) -> None:
        try:
            await self._coalescer.flush_due()
        except Exception as exc:  # the loop survives; the counts stay for the next tick
            _log().warning("admin.area_coalesce.flush_failed", error=type(exc).__name__)

    @audited("admin.area_entered")
    async def stop(self) -> int:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.wait({task})
        return await self._coalescer.drain()
