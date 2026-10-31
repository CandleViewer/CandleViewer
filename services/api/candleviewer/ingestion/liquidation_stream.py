"""Live liquidation stream: demand, strict parse, bus publication, bounded write-behind (E24-T03).

`allLiquidation.{symbol}` has no REST history, so a print not written is a print lost for good
(21 §4.6). Rules (#667; plain code on the hot path, never a statechart, C-2.20):

- **Demand.** Refcounted, like the other streams: the WS gateway acquires per subscription
  (`ws_wiring.ingestion_streams`), and every symbol the recorder records (`recorded`) is held
  too, re-read once a second. Only listed symbols ever become topics.
- **Prints.** A push is parsed whole (the adapter's parser, injected, C-2.2); a refused one is
  counted and logged, never half-written. Every print's time must also pass the clock- and
  listing-relative window trades use (`event_window`, #1892): one print stamped in the future
  refuses its push, so it can neither hold a live cluster open nor land ahead of now. Each print
  is published on `{env}.md.{symbol}.liquidation` for the WS topic and queued for the store.
- **Backpressure, never loss.** The write queue is bounded in pushes (`WRITE_QUEUE_MAXSIZE`) and
  in prints (`WRITE_QUEUE_MAX_PRINTS`); a full queue makes the frame handler wait, which backs up
  the socket's dispatch lane instead of dropping a print or growing without limit (C-2.18). The
  writer batches whatever is queued. `stop()` drains it for up to `STOP_DRAIN_S` first. A frame
  the lane drops is counted there (`ingest_dispatch_overflow_total{stream="liquidation"}`) and
  logged here: no REST history refills it.
- **Reconnect.** A socket-wide drop is logged with the time since the last push and counted;
  the first push after it logs the gap's length. The connection manager resubscribes; prints the
  exchange replays land on the same dedup key `(ts, symbol, side, price, size, batch_index)`, so
  the store absorbs them.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Final, Protocol

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, TopicPattern
from candleviewer.exchange.base.models import LiquidationEvent
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.metrics import count_event
from candleviewer.ingestion.planner import DEFAULT_GRACE_S, DemandTracker
from candleviewer.ingestion.rejection import RejectionLog
from candleviewer.ingestion.watchdog import FeedHealthEvent, prune_unlisted
from candleviewer.observability.context import spawn

#: Pushes waiting for the store (C-2.18). A push is one symbol's 500 ms, so 4096 is minutes of a
#: cascade across every recorded symbol; past it the frame handler waits (backpressure).
WRITE_QUEUE_MAXSIZE: Final = 4096
#: Prints waiting for the store: the memory bound (a push holds up to 1 000 prints, so the push
#: bound alone would allow ~4 M). Past it the frame handler waits too.
WRITE_QUEUE_MAX_PRINTS: Final = 100_000
#: `stop()` gives the write-behind this long to store what is queued before cancelling it.
STOP_DRAIN_S: Final = 5.0
#: Prints handed to the store in one write, at most.
WRITE_BATCH_MAX: Final = 5000
WRITE_RETRY_S: Final = 1.0
DETAIL: Final = "liquidation"


class LiquidationWriter(Protocol):
    async def write_liquidations(self, events: Sequence[LiquidationEvent]) -> None: ...


class LiquidationObserver(Protocol):
    """The order-flow metrics (`deriv_*`), injected: ingestion may not import orderflow."""

    def prints(self, events: Sequence[LiquidationEvent], now_us: int) -> None: ...

    def reconnect(self) -> None: ...

    def rejected(self) -> None: ...


def _now_us() -> int:
    return time.time_ns() // 1000


class LiquidationStream:
    """Refcounted `allLiquidation.{symbol}` demand + parse + publication + write-behind."""

    def __init__(
        self,
        *,
        bus: Bus,
        env: str,
        set_desired: Callable[[set[str]], None],
        parse_frame: Callable[[str, int], list[LiquidationEvent] | None],
        topic_for: Callable[[str], str],
        is_listed: Callable[[str], bool],
        recorded: Callable[[], frozenset[str]] = frozenset,
        writer: LiquidationWriter | None = None,
        observer: LiquidationObserver | None = None,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        grace_s: float = DEFAULT_GRACE_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        queue_max: int = WRITE_QUEUE_MAXSIZE,
        queue_max_prints: int = WRITE_QUEUE_MAX_PRINTS,
        event_window: Callable[[str, int], None] | None = None,
        stop_drain_s: float = STOP_DRAIN_S,
    ) -> None:
        self._bus, self._env = bus, env
        self._set_desired, self._parse, self._topic_for = set_desired, parse_frame, topic_for
        self._is_listed, self._recorded = is_listed, recorded
        self._writer, self._observer = writer, observer
        self._clock, self._now_us, self._sleep = clock, now_us, sleep
        self._demand = DemandTracker(clock, grace_s)
        self._rejects = RejectionLog("liquidation", clock)
        self._wanted: set[str] = set()
        self._last_push: float | None = None
        self._dropped_at: float | None = None
        self._writes: asyncio.Queue[list[LiquidationEvent]] = asyncio.Queue(maxsize=queue_max)
        #: #1892: clock/listing-relative plausibility (`ingestion.rejection.EventWindow`).
        self._window = event_window
        self._max_prints, self._queued_prints = queue_max_prints, 0
        self._room = asyncio.Condition()
        self._stop_drain_s = stop_drain_s
        self._tasks: list[asyncio.Task[None]] = []
        self._health = bus.subscribe(
            "liquidation-stream-health",
            TopicPattern(env=env, domain="health", detail="feed"),
            QueuePolicy.NEVER_DROP,
            maxsize=1024,
        )

    # ---- demand ---------------------------------------------------------
    def acquire(self, consumer: str, symbol: str) -> None:
        if not self._is_listed(symbol):  # crafted/unknown symbols never reach a topic
            raise ValueError(f"unlisted symbol {symbol!r}")
        self._demand.acquire(consumer, symbol)
        self.sync()

    def release(self, consumer: str, symbol: str) -> None:
        self._demand.release(consumer, symbol)
        self.sync()

    def desired(self) -> set[str]:
        recorded = {s for s in self._recorded() if self._is_listed(s)}
        return self._demand.desired() | recorded

    def sync(self) -> None:
        """Push the desired upstream set (live demand, inside grace, recorded) to the socket."""
        self._wanted = self.desired()
        self._set_desired({self._topic_for(s) for s in self._wanted})

    async def prune_unlisted(self) -> list[str]:
        health = Topic(env=self._env, domain="health", detail="feed")

        async def publish(ev: FeedHealthEvent) -> None:
            await self._bus.publish(health, ev)

        gone = await prune_unlisted(
            self._demand, self._is_listed, self.sync, publish, self._topic_for, now_us=self._now_us
        )
        self.sync()  # a recorded symbol that left the catalogue goes too
        return gone

    def is_listed(self, symbol: str) -> bool:
        return self._is_listed(symbol)

    # ---- frames ---------------------------------------------------------
    async def handle_frame(self, frame: str) -> None:
        try:
            events = self._parse(frame, self._now_us())
            if events and self._window is not None:
                for e in events:
                    self._window(e.symbol, e.ts_event)
        except (ValueError, RecursionError) as exc:  # the whole push is refused, never half
            self._rejects.record(exc)
            if self._observer is not None:
                self._observer.rejected()
            return
        if not events or events[0].symbol not in self._wanted:
            return
        symbol = events[0].symbol
        now = self._clock()
        if self._dropped_at is not None:
            gap = now - self._dropped_at
            self._dropped_at = None
            get_logger(__name__).warning("liquidation_stream_gap", gap_s=round(gap, 3))
        self._last_push = now
        count_event("liquidation", symbol)
        if self._observer is not None:
            self._observer.prints(events, self._now_us())
        topic = Topic(env=self._env, domain="md", symbol=symbol, detail=DETAIL)
        for event in events:
            await self._bus.publish(topic, event)
        if self._writer is not None:
            await self._enqueue(events)  # full: wait, so the socket lane backs up (no drop)

    async def _enqueue(self, events: list[LiquidationEvent]) -> None:
        """Wait for room by prints (one push always fits an empty queue), then by pushes."""
        async with self._room:
            await self._room.wait_for(
                lambda: (
                    self._queued_prints == 0
                    or self._queued_prints + len(events) <= self._max_prints
                )
            )
            self._queued_prints += len(events)
        await self._writes.put(events)

    async def _taken(self, n: int) -> None:
        async with self._room:
            self._queued_prints -= n
            self._room.notify_all()

    def note_gap(self, reason: str, symbol: str | None = None) -> None:
        """A dispatch lane dropped frames (`IngestionService`): no REST history can fill it. The
        lane counts each dropped frame (`ingest_dispatch_overflow_total{stream="liquidation"}`)."""
        get_logger(__name__).warning("liquidation_frames_lost", reason=reason, symbol=symbol)

    # ---- feed health (reconnect) ----------------------------------------
    async def process_health(self, event: FeedHealthEvent) -> None:
        if event.state not in ("resubscribing", "degraded") or self._dropped_at is not None:
            return
        now = self._clock()
        self._dropped_at = now
        since = None if self._last_push is None else round(now - self._last_push, 3)
        get_logger(__name__).warning("liquidation_socket_dropped", since_last_push_s=since)
        if self._observer is not None:
            self._observer.reconnect()

    async def _health_loop(self) -> None:
        while True:
            ev = await self._health.get()
            if isinstance(ev, FeedHealthEvent):
                await self.process_health(ev)

    async def _sync_loop(self) -> None:
        while True:
            await self._sleep(1.0)
            self.sync()

    def take_batch(self) -> list[LiquidationEvent]:
        """Every queued push, up to `WRITE_BATCH_MAX` prints (at least one push)."""
        batch: list[LiquidationEvent] = []
        while not self._writes.empty() and (not batch or len(batch) < WRITE_BATCH_MAX):
            batch.extend(self._writes.get_nowait())
        return batch

    async def write_once(self) -> int:
        """Wait for a push, then write every queued one; a failed write is retried until the
        store takes it (no print is dropped), one attempt per `WRITE_RETRY_S`."""
        first = await self._writes.get()
        batch = first + self.take_batch()
        await self._taken(len(batch))
        while self._writer is not None:
            try:
                await self._writer.write_liquidations(batch)
            except Exception as exc:  # write-behind must never take ingest down
                get_logger(__name__).warning(
                    "liquidation write-behind failed", error=type(exc).__name__, prints=len(batch)
                )
                await self._sleep(WRITE_RETRY_S)
                continue
            break
        return len(batch)

    async def _write_loop(self) -> None:
        while True:
            await self.write_once()

    @property
    def queued(self) -> int:
        return self._writes.qsize()

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        self.sync()
        self._tasks = [
            spawn(self._health_loop(), name="liquidation-health"),
            spawn(self._sync_loop(), name="liquidation-sync"),
            spawn(self._write_loop(), name="liquidation-write-behind"),
        ]

    async def drain(self) -> None:
        """Store every queued push now (the write loop's work, without waiting for a new one)."""
        while not self._writes.empty():
            await self.write_once()

    async def stop(self) -> None:
        """Drain the write-behind for up to `stop_drain_s`, then cancel the loops: what is still
        queued then is lost (logged), as a socket gap is."""
        if self._writer is not None and not self._writes.empty():
            try:
                async with asyncio.timeout(self._stop_drain_s):
                    await self.drain()
            except TimeoutError:
                get_logger(__name__).warning(
                    "liquidation_write_behind_unflushed", pushes=self._writes.qsize()
                )
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._bus.unsubscribe(self._health)


__all__ = [
    "STOP_DRAIN_S",
    "WRITE_QUEUE_MAXSIZE",
    "WRITE_QUEUE_MAX_PRINTS",
    "LiquidationObserver",
    "LiquidationStream",
    "LiquidationWriter",
]
