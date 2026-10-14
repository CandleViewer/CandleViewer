"""`ReplaySource`: one replay's recorded events behind a bounded read-ahead (E26-T02).

Pull-based and speed-agnostic (pacing is the replay clock's, E26-T03): `async for item in source`
yields the recorded events and `ReplayGap` markers of `replay.merge`, in its documented order,
then stops. Use it as `async with source:` so the producer task is always stopped.

**Read-ahead** (C-2.18; `20-architecture.md` Sec.4.2). A tracked producer task drives the merge
and puts its batches on a bounded queue. A full queue blocks the producer, so a slow consumer
stops the storage reads instead of growing memory, and no event is ever dropped (the replay
clock slows instead, `24-internal-schemas.md` Sec.13.7). The queue is bounded in events and in
bytes, whichever binds first: batches are cut at `batch_events` events or at
`readahead_bytes / slots` estimated bytes, so `slots` queued batches stay within both bounds
(plus at most one event per batch).

**Memory ceiling.** The merge's cursors share what `memory_ceiling_bytes` leaves after the
queue. A session too wide or a stream too dense for it fails with `ReplayMemoryCeilingExceeded`.
Every byte bound here is an estimate, not a measured resident size: an event counts 512 B
(E26-K01 measured ~0.4 KB) plus 128 B per snapshot level (`merge.approx_bytes`).

**Failures** reach the consumer in order: every event merged before a storage failure is
delivered, then the typed error is raised.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
from typing import Final, Self

from candleviewer.observability import spawn
from candleviewer.observability.metrics import Gauge
from candleviewer.replay.errors import ReplayWindowTooLarge
from candleviewer.replay.merge import (
    DEFAULT_IO_TIMEOUT_S,
    DEFAULT_MAX_ROWS_PER_READ,
    DEFAULT_MAX_WINDOW_US,
    DEFAULT_WINDOW_US,
    US_PER_SECOND,
    RecordedMerge,
)
from candleviewer.replay.models import ReplayItem, ReplayRequest, ReplayTiers
from candleviewer.storage.repositories.recorded import RecordedEvent

replay_readahead_depth = Gauge(
    "replay_readahead_depth", "Events buffered ahead of replay consumers, all sessions."
)


@dataclass(frozen=True, slots=True)
class ReadAheadConfig:
    """Read-ahead and memory bounds of one replay (ADR-0035 proposed; 20-architecture Sec.4.2).

    `window_us` is the initial per-stream read window (ADR-0035: 30 s of replay time).
    `readahead_events` defaults to ~30 s of the busiest dense 200-depth minute E26-K01 measured
    (121 k rows). `memory_ceiling_bytes` caps the estimated size (512 B per event,
    `merge.approx_bytes`) of the queue plus every stream's current window.
    `max_span_us` mirrors E26-T01's 24 h window cap as defence in depth."""

    window_us: int = DEFAULT_WINDOW_US
    max_window_us: int = DEFAULT_MAX_WINDOW_US
    readahead_events: int = 131_072
    readahead_bytes: int = 64 * 1024 * 1024
    memory_ceiling_bytes: int = 256 * 1024 * 1024
    batch_events: int = 1_024
    io_timeout_s: float = DEFAULT_IO_TIMEOUT_S
    max_span_us: int = 24 * 3_600 * US_PER_SECOND
    max_rows_per_read: int = DEFAULT_MAX_ROWS_PER_READ

    def __post_init__(self) -> None:
        positive = (
            self.window_us,
            self.readahead_events,
            self.readahead_bytes,
            self.batch_events,
            self.io_timeout_s,
            self.max_span_us,
            self.max_rows_per_read,
        )
        if min(positive) <= 0:
            raise ValueError("read-ahead bounds, windows and timeouts must be positive")
        if self.max_window_us < self.window_us:
            raise ValueError("max_window_us must be >= window_us")
        if self.batch_events > self.readahead_events:
            raise ValueError("batch_events must be <= readahead_events")
        if self.memory_ceiling_bytes <= self.readahead_bytes:
            raise ValueError("memory_ceiling_bytes must exceed readahead_bytes")


@dataclass(frozen=True, slots=True)
class _Failed:
    error: Exception


@dataclass(frozen=True, slots=True)
class _End:
    pass


_END: Final = _End()


class ReplaySource:
    """Async iterator over one replay's recorded events and gap markers (see module doc).

    Single pass: once exhausted or closed it stays stopped; a seek builds a new source."""

    def __init__(
        self, request: ReplayRequest, tiers: ReplayTiers, *, config: ReadAheadConfig | None = None
    ) -> None:
        cfg = config or ReadAheadConfig()
        if request.end_us - request.start_us > cfg.max_span_us:
            raise ReplayWindowTooLarge(f"replay window exceeds {cfg.max_span_us} µs")
        self._merge = RecordedMerge(
            request,
            tiers,
            budget_bytes=cfg.memory_ceiling_bytes - cfg.readahead_bytes,
            window_us=cfg.window_us,
            max_window_us=cfg.max_window_us,
            io_timeout_s=cfg.io_timeout_s,
            max_rows_per_read=cfg.max_rows_per_read,
        )
        slots = -(-cfg.readahead_events // cfg.batch_events)
        self._queue: asyncio.Queue[list[ReplayItem] | _End | _Failed] = asyncio.Queue(slots)
        self._batch_events = cfg.batch_events
        self._batch_bytes = max(1, cfg.readahead_bytes // slots)
        self._task: asyncio.Task[None] | None = None
        self._batch: list[ReplayItem] = []
        self._pos = 0
        self._buffered = 0
        self._done = False

    @property
    def buffered_events(self) -> int:
        """Events read from storage and not yet handed to the consumer (queued or in flight)."""
        return self._buffered

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ReplayItem:
        if self._pos < len(self._batch):
            item = self._batch[self._pos]
            self._pos += 1
            return item
        if self._done:
            raise StopAsyncIteration
        self._start()
        got = await self._queue.get()
        if isinstance(got, _End):
            self._done = True
            raise StopAsyncIteration
        if isinstance(got, _Failed):
            self._done = True
            raise got.error
        self._release(len(got))
        self._batch, self._pos = got, 1
        return got[0]

    async def __aenter__(self) -> Self:
        self._start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Stop the producer and release the read-ahead buffer. Idempotent. A consumer parked
        on the queue in another task wakes and stops instead of waiting forever."""
        self._done = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(_END)  # the queue was just emptied, so this never blocks
        self._release(self._buffered)
        self._batch, self._pos = [], 0

    async def anchor_at(self, symbol: str, at_us: int) -> RecordedEvent | None:
        """Seek anchor for E26-T04 (see `RecordedMerge.anchor_at`)."""
        return await self._merge.anchor_at(symbol, at_us)

    def _start(self) -> None:
        if self._task is None and not self._done:
            self._task = spawn(self._produce(), name="replay-source")

    def _release(self, events: int) -> None:
        if events:
            self._buffered -= events
            replay_readahead_depth.dec(events)

    async def _produce(self) -> None:
        batches = self._merge.batches(max_events=self._batch_events, max_bytes=self._batch_bytes)
        try:
            async with aclosing(batches):
                async for batch in batches:
                    self._buffered += len(batch)
                    replay_readahead_depth.inc(len(batch))
                    await self._queue.put(batch)  # blocks while full: storage reads stop
        except Exception as exc:  # handed to the consumer after every event merged before it
            await self._queue.put(_Failed(exc))
        else:
            await self._queue.put(_END)
