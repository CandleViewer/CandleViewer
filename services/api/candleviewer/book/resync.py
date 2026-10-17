"""`BookEngine` + resync discipline for one `(env, symbol, depth)` (E08-S05).

Hot path stays plain code (INV-B14-a): `on_event` applies deltas directly.
This engine owns and *enforces* the whole lifecycle synchronously (C-2.21)
and publishes each lifecycle edge as a plain event name to an optional
injected `HealthSink` (INV-B14-b). The B14 `book` chart lives behind that sink
in a non-hot composition module and only *records* the edges; this package
never imports or queries the statechart runtime (C-2.20, CV-LINT-HOTPATH).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable

from candleviewer.book.errors import BookError, BookInvariantError
from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookDelta, BookSnapshot

#: INV-B14-d: deltas buffered while a snapshot is in flight are bounded.
BUFFER_BOUND = 1_000
#: Security note: >5 resyncs in 60 s trips the breaker -> `degraded`.
BREAKER_MAX, BREAKER_WINDOW_US = 5, 60_000_000

Publish = Callable[[object], Awaitable[None]]


#: Receives lifecycle edges (`SUBSCRIBE`, `SNAPSHOT`, `SEQUENCE_GAP`,
#: `SNAPSHOT_TIMEOUT`, `BUFFER_OVERFLOW`). Must not block: fire-and-forget only.
HealthSink = Callable[[str], Awaitable[None]]


class BookEngine:
    def __init__(
        self,
        *,
        symbol: str,
        depth: int,
        publish: Publish,
        resubscribe: Callable[[], Awaitable[None]],
        now_us: Callable[[], int],
    ) -> None:
        self.symbol, self.depth = symbol, depth
        self.phase = BookPhase.INIT
        self.book: BookState | None = None
        self.muted = False  # tier warm-up: build to LIVE without publishing
        self.resync_count = 0
        self.degraded = False
        self.last_u = 0
        self.last_good_ts_us: int | None = None
        self.health_sink: HealthSink | None = None
        self._publish, self._resubscribe, self._now = publish, resubscribe, now_us
        self._buffer: deque[BookDelta] = deque()
        self._staged: BookSnapshot | None = None
        self._template: BookSnapshot | None = None
        self._resync_times: deque[int] = deque()
        self._pending_since: int | None = None
        self._reason = "subscribe"

    # ---- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        await self.request_snapshot()
        await self._edge("SUBSCRIBE")

    async def on_event(self, ev: BookSnapshot | BookDelta) -> None:
        """Hot path. Never touches an interpreter for a delta."""
        if isinstance(ev, BookSnapshot):
            await self._on_snapshot(ev)
            return
        if self.phase is not BookPhase.LIVE or self.book is None:
            if self.phase is BookPhase.SNAPSHOT_PENDING:
                if len(self._buffer) >= BUFFER_BOUND:
                    await self._desync("buffer_overflow")
                else:
                    self._buffer.append(ev)
            return
        if ev.prev_update_id != self.last_u:
            await self._desync("sequence_gap")
            return
        try:
            self.book.apply(ev.bids, ev.asks)
        except BookError as exc:
            kind = exc.kind if isinstance(exc, BookInvariantError) else "payload"
            await self._desync(kind)
            return
        self.last_u = ev.update_id
        self.last_good_ts_us = ev.ts_event
        if not self.muted:
            await self._publish(ev)

    async def _on_snapshot(self, ev: BookSnapshot) -> None:
        if self.phase is BookPhase.LIVE:  # server reset: drop and re-snapshot
            await self._desync("server_reset")
            return
        if self.phase is not BookPhase.SNAPSHOT_PENDING:
            return
        self._staged = ev
        await self.go_live()
        if self.book is not None:  # go_live reached LIVE
            await self._edge("SNAPSHOT")

    async def invalidate(self, reason: str) -> None:
        """External discontinuity (frame loss / reconnect): drop and resync."""
        if self.phase is BookPhase.LIVE:
            await self._desync(reason)

    async def _desync(self, reason: str) -> None:
        was_live = self.phase is BookPhase.LIVE
        self.phase = BookPhase.DESYNCED  # enforce first (C-2.21)
        self.book = None
        self._reason = reason
        await self.go_desynced()
        await self.request_snapshot()
        # The chart knows LIVE -> desynced and (OC-08, #2204) a full pending
        # buffer -> desynced; any other failed (re)snapshot stays in its
        # snapshot_pending, which the engine has just re-entered too.
        if was_live:
            await self._edge("SEQUENCE_GAP")
        elif reason == "buffer_overflow":
            await self._edge("BUFFER_OVERFLOW")
        else:
            await self._edge("SNAPSHOT_TIMEOUT")

    async def _edge(self, event: str) -> None:
        if self.health_sink is not None:
            await self.health_sink(event)

    async def on_snapshot_timeout(self) -> None:
        """Re-request a snapshot that has been pending too long."""
        await self.request_snapshot()
        await self._edge("SNAPSHOT_TIMEOUT")

    def check_timeout(self, timeout_us: int) -> bool:
        """True when a snapshot has been pending longer than `timeout_us`;
        the caller then calls `on_snapshot_timeout`."""
        since = self._pending_since
        return (
            self.phase is BookPhase.SNAPSHOT_PENDING
            and since is not None
            and (self._now() - since >= timeout_us)
        )

    # ---- lifecycle steps -----------------------------------------------------
    async def request_snapshot(self) -> None:
        self.phase = BookPhase.SNAPSHOT_PENDING
        self._buffer.clear()
        self._staged = None
        self._pending_since = self._now()
        await self._resubscribe()

    async def go_live(self) -> None:
        snap = self._staged
        if snap is None:
            return
        try:
            book = BookState.from_levels(self.depth, snap.bids, snap.asks)
        except BookError:
            await self._desync("bad_snapshot")
            return
        last_u = snap.update_id
        for d in self._buffer:  # INV-B14-d: strictly after snapshot seq
            if d.update_id <= last_u:
                continue
            if d.prev_update_id != last_u:
                await self._desync("sequence_gap")
                return
            try:
                book.apply(d.bids, d.asks)
            except BookError:
                await self._desync("bad_replay")
                return
            last_u = d.update_id
        self._buffer.clear()
        self._staged = None
        self._template = snap
        self.book, self.last_u, self.phase = book, last_u, BookPhase.LIVE
        self.last_good_ts_us = self._now()
        if not self.muted:
            await self.publish_current("subscribe" if self.resync_count == 0 else "resync")

    @property
    def snapshot_cross_seq(self) -> int | None:
        """Cross sequence of the snapshot the book was last built from (REST serves it as `seq`)."""
        return None if self._template is None else self._template.cross_seq

    def live_snapshot(self, depth: int | None = None) -> BookSnapshot | None:
        """The current top-`depth` book as a `BookSnapshot`, only while LIVE."""
        if self.phase is not BookPhase.LIVE or self.book is None or self._template is None:
            return None
        n = min(depth or self.depth, self.depth)
        bids, asks = self.book.top(n)
        return self._template.model_copy(
            update={"bids": bids, "asks": asks, "update_id": self.last_u, "depth": n}
        )

    async def publish_current(self, reason: str) -> None:
        """Publish the full current book as a `BookSnapshot` (+ LIVE status)."""
        if self.book is None or self._template is None:
            return
        bids, asks = self.book.snapshot()
        await self._publish(
            self._template.model_copy(
                update={"bids": bids, "asks": asks, "update_id": self.last_u, "reason": reason}
            )
        )
        await self._status("live")

    async def go_desynced(self) -> None:
        self.phase = BookPhase.DESYNCED
        self.book = None
        self.resync_count += 1
        now = self._now()
        self._resync_times.append(now)
        while self._resync_times and now - self._resync_times[0] > BREAKER_WINDOW_US:
            self._resync_times.popleft()
        self.degraded = len(self._resync_times) > BREAKER_MAX
        if not self.muted:
            await self._status(self._reason)

    async def _status(self, reason: str) -> None:
        await self._publish(
            BookStatus(
                symbol=self.symbol,
                depth=self.depth,
                state=self.phase,
                reason=reason,
                ts_us=self._now(),
                last_good_ts_us=self.last_good_ts_us,
                resync_count=self.resync_count,
                degraded=self.degraded,
            )
        )
