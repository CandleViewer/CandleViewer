"""`ReplaySource`: one replay's recorded events behind a bounded read-ahead (E26-T02).

Pull-based and speed-agnostic (pacing is the replay clock's, E26-T03): `async for item in source`
yields the recorded events and `ReplayGap` markers of `replay.merge`, in its documented order,
then stops. One consumer, one pass (a seek builds a new source). Use it as `async with source:`
so the producer task is always stopped.

**Read-ahead** (C-2.18; `20-architecture.md` Sec.4.2). One producer task, owned by the source
(`spawn`, stopped by `aclose`), drives the merge and puts its batches on a bounded queue. A full
queue blocks the producer, so a slow or paused consumer stops the storage reads instead of
growing memory, and no event is dropped: the replay clock slows instead (`24-internal-schemas.md`
Sec.13.7). The read-ahead holds at most `readahead_events` events and `readahead_bytes` estimated
bytes, whichever binds first, counting every batch the source keeps for its consumer: the queued
ones, the one the producer holds (being built, or waiting for a queue slot) and the one the
consumer is iterating. A batch ends at its event count or at its share of the bytes less the
largest row the request can produce, so it never exceeds the share; the queue has two slots
fewer than there are batches in all. `buffered_events` is what is queued. The producer yields to
the event loop after every batch (C-2.17: merging a batch of 1 024 events took 1-3 ms here). The
consumer owns its own yields: `__anext__` suspends only to wait for a batch, so a loop that awaits
nothing else drains a full read-ahead in one turn (E26-T03's clock is to yield every 256
deliveries).

**Memory ceiling.** `memory_ceiling_bytes` is the session's estimated budget: the read-ahead
takes `readahead_bytes` of it and the merge's cursors share the rest, each read capped at its
share in rows and at the merge's `DEFAULT_MAX_ROWS_PER_READ`. A session too wide or a stream too
dense for it fails with `ReplayMemoryCeilingExceeded`; gap markers sit outside it (see
`replay.merge`). Every byte figure is an estimate, not a measured resident size: an event counts
512 B plus 128 B per snapshot level (`merge.approx_bytes`); E26-K01's marginal cost was 0.3-0.4 KB
an event over a fixed 55 MB baseline, so 512 B is above it, and E26-Q03 is to re-measure it.

**Failures** reach the consumer in order. A `ReplayError` is raised after every event merged
before it (the merge yields its batch in progress first). Any other failure is a bug or a
contract breach below the source (a reader raising something untyped, a producer cancelled by
anyone but `aclose`): it is logged and reaches the consumer as `ReplayInternalError`, with a fixed
text and nothing of the original (RP-I02), after every batch the merge had yielded. Every storage
await is bounded by `io_timeout_s` (in the merge), and so is closing: `aclose` waits that long for
the producer, then logs and returns, and a producer that ignored the cancellation stops at its next
batch instead of queueing for a closed source.

**Window cap.** The request's `max_span_us` (E26-T01's `CV_REPLAY_MAX_WINDOW_HOURS`) is the one
cap; the source has none of its own. It re-validates the request it is given, because
`model_copy(update=...)` and `model_construct` skip validation (a seek would derive its request
that way) and this is the last line before storage reads.
"""

from __future__ import annotations

import asyncio
import enum
import math
from contextlib import aclosing, suppress
from dataclasses import dataclass
from typing import Any, Final, Self

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.metrics import Gauge
from candleviewer.replay.errors import ReplayConfigInvalid, ReplayError, ReplayInternalError
from candleviewer.replay.merge import (
    DEFAULT_IO_TIMEOUT_S,
    DEFAULT_MAX_WINDOW_US,
    DEFAULT_WINDOW_US,
    RecordedMerge,
    row_bytes,
)
from candleviewer.replay.models import ReplayItem, ReplayRequest, ReplayTiers
from candleviewer.storage.repositories.recorded import RecordedEvent

replay_readahead_depth = Gauge(
    "replay_readahead_depth", "Events buffered ahead of replay consumers, all sessions."
)

#: Batches the source holds at least: one queue slot, the producer's and the consumer's.
_MIN_BATCHES: Final = 3


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _report(event: str, **fields: Any) -> None:
    """Log an error. A logger that fails must neither change what the consumer is told nor leave
    it waiting, so nothing it raises gets out of here."""
    with suppress(Exception):
        _log().error(event, **fields)


@dataclass(frozen=True, slots=True)
class ReadAheadConfig:
    """Read-ahead and memory bounds of one replay (ADR-0035 proposed; 20-architecture Sec.4.2).

    `window_us` is the initial per-stream read window (ADR-0035: 30 s of replay time), widened up
    to `max_window_us` while a stream is sparse. `readahead_events` defaults to ~30 s of the
    busiest dense 200-depth minute E26-K01 measured (121 k rows); it and `readahead_bytes` bound
    everything the source holds for its consumer (see the module docstring), and
    `batch_events` is the most events one batch holds (less when the bounds leave room for fewer
    than three of them). `memory_ceiling_bytes` is the session's estimated budget, the read-ahead
    included (512 B per event, `merge.approx_bytes`). `io_timeout_s` bounds each storage await and
    the wait for the producer to stop.

    The window cap is not here: it is the request's `max_span_us`. A bound outside its range
    raises `ReplayConfigInvalid`."""

    window_us: int = DEFAULT_WINDOW_US
    max_window_us: int = DEFAULT_MAX_WINDOW_US
    readahead_events: int = 131_072
    readahead_bytes: int = 64 * 1024 * 1024
    memory_ceiling_bytes: int = 256 * 1024 * 1024
    batch_events: int = 1_024
    io_timeout_s: float = DEFAULT_IO_TIMEOUT_S

    def __post_init__(self) -> None:
        if self.window_us < 1 or self.max_window_us < self.window_us:
            raise ReplayConfigInvalid("read windows need 1 µs <= window_us <= max_window_us")
        if not (math.isfinite(self.io_timeout_s) and self.io_timeout_s > 0):
            raise ReplayConfigInvalid("io_timeout_s must be a positive, finite number of seconds")
        if self.batch_events < 1 or self.readahead_bytes < 1:
            raise ReplayConfigInvalid("batch_events and readahead_bytes must be positive")
        if self.readahead_events < _MIN_BATCHES:
            raise ReplayConfigInvalid("readahead_events must allow at least three batches")
        if self.memory_ceiling_bytes <= self.readahead_bytes:
            raise ReplayConfigInvalid("memory_ceiling_bytes must exceed readahead_bytes")


@dataclass(frozen=True, slots=True)
class _Plan:
    """How the read-ahead bounds become batches: events per batch, the byte count a batch is cut
    at, and queue slots."""

    batch_events: int
    cut_bytes: int
    slots: int


def _plan(cfg: ReadAheadConfig, request: ReplayRequest) -> _Plan:
    """Cut `cfg`'s bounds into batches for `request`. `held` batches are in memory at once (the
    queue's, the producer's and the consumer's), each of at most `batch_events` events and
    `per_batch` estimated bytes, so `held * batch_events <= readahead_events` and `held *
    per_batch <= readahead_bytes`. The merge ends a batch once it reaches `cut_bytes`, so a batch
    is under `cut_bytes` plus its last row: a marker or a row of the deepest requested stream,
    `largest` bytes at most."""
    largest = max(row_bytes(stream, request.depth) for stream in request.streams)
    batch_events = min(cfg.batch_events, cfg.readahead_events // _MIN_BATCHES)
    held = min(cfg.readahead_events // batch_events, cfg.readahead_bytes // largest)
    if held < _MIN_BATCHES:
        raise ReplayConfigInvalid("readahead_bytes must hold three rows of the requested depth")
    per_batch = cfg.readahead_bytes // held
    return _Plan(batch_events=batch_events, cut_bytes=per_batch - largest, slots=held - 2)


@dataclass(frozen=True, slots=True)
class _Failed:
    """The producer's failure, queued after every batch it delivered before it."""

    error: Exception


class _Mark(enum.Enum):
    END = "end"  # the producer finished: every batch it merged is queued ahead of this
    STOPPED = "stopped"  # something other than `aclose` cancelled the producer


type _Queued = list[ReplayItem] | _Failed | _Mark


def _failure(exc: Exception) -> _Failed:
    """What the consumer is told: a typed failure as it is, anything else only as a fixed
    `ReplayInternalError` (RP-I02), the original logged by type and traceback."""
    if isinstance(exc, ReplayError):
        return _Failed(exc)
    _report("replay_source_failed", error_type=type(exc).__name__, exc_info=exc)
    return _Failed(ReplayInternalError())


class ReplaySource:
    """Async iterator over one replay's recorded events and gap markers (see module doc).

    One consumer, one pass: once exhausted, failed or closed it stays stopped. Iteration raises
    the typed `ReplayError`s of the merge (`ReplayTierStraddle`, `ReplaySourceUnavailable`,
    `ReplayMemoryCeilingExceeded`) after every event merged before them, and `ReplayInternalError`
    for any other failure below it, a producer cancelled by anything but `aclose` included. A
    source that is neither exhausted nor closed keeps its producer parked on the full queue:
    close it (`async with`)."""

    def __init__(
        self, request: ReplayRequest, tiers: ReplayTiers, *, config: ReadAheadConfig | None = None
    ) -> None:
        cfg = config or ReadAheadConfig()
        request = ReplayRequest.model_validate(request.model_dump())
        self._plan = _plan(cfg, request)
        self._merge = RecordedMerge(
            request,
            tiers,
            budget_bytes=cfg.memory_ceiling_bytes - cfg.readahead_bytes,
            window_us=cfg.window_us,
            max_window_us=cfg.max_window_us,
            io_timeout_s=cfg.io_timeout_s,
        )
        self._stop_timeout_s = cfg.io_timeout_s
        self._queue: asyncio.Queue[_Queued] = asyncio.Queue(maxsize=self._plan.slots)
        self._task: asyncio.Task[None] | None = None
        self._batch: list[ReplayItem] = []
        self._pos = 0
        self._queued = 0
        self._done = False

    @property
    def buffered_events(self) -> int:
        """Events read from storage and queued, not yet handed to the consumer."""
        return self._queued

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ReplayItem:
        pos = self._pos
        if pos < len(self._batch):
            self._pos = pos + 1
            return self._batch[pos]
        return await self._advance()

    async def __aenter__(self) -> Self:
        if not self._done:
            self._start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Stop the producer, release everything buffered and end the iteration. Idempotent. A
        consumer parked on the queue in another task wakes and stops. Everything is released
        even if this call is itself cancelled while it waits for the producer. It waits at most
        `io_timeout_s` for the producer (per call): one that ignores the cancellation is logged
        and left, and stops at its next batch."""
        self._done = True
        try:
            task = self._task
            if task is not None:
                task.cancel()
                try:
                    async with asyncio.timeout(self._stop_timeout_s):
                        await asyncio.wait({task})
                except TimeoutError:
                    _report("replay_source_producer_did_not_stop", wait_s=self._stop_timeout_s)
        finally:
            self._release()

    async def anchor_at(self, symbol: str, at_us: int) -> RecordedEvent | None:
        """Seek anchor for E26-T04: `RecordedMerge.anchor_at`, whatever the read-ahead is doing
        (before the first read, mid-replay, after close). It raises `ReplayRequestInvalid` for a
        symbol or instant outside the replay and `ReplaySourceUnavailable` when storage fails or
        answers outside the bound; neither is ever turned into "no anchor"."""
        return await self._merge.anchor_at(symbol, at_us)

    def _start(self) -> asyncio.Task[None]:
        if self._task is None:
            self._task = spawn(self._produce(), name="replay-source")
            self._task.add_done_callback(self._producer_ended)
        return self._task

    def _producer_ended(self, task: asyncio.Task[None]) -> None:
        """Wake a consumer parked on the empty queue when the producer ended without leaving its
        own end marker: cancelled (by `aclose`, which clears the queue and leaves its own end
        marker afterwards, or by anyone else) or dead of an exception. A full queue means the
        consumer is not parked: `_advance` finds the ended producer once it has drained the
        queue. A closed source lets go of the task: nothing starts it again, and a cancelled task
        keeps its exception, and that the producer's frame and its batch."""
        if (task.cancelled() or task.exception() is not None) and not self._queue.full():
            self._queue.put_nowait(_Mark.STOPPED)
        if self._done:
            self._task = None

    async def _advance(self) -> ReplayItem:
        """The first item of the next batch, or the end of the replay (a stop or typed error)."""
        if self._done:
            raise StopAsyncIteration
        self._batch, self._pos = [], 0  # the finished batch is released before waiting
        task = self._start()
        got: _Queued
        if task.done() and self._queue.empty():  # it ended and left no marker
            got = _Mark.STOPPED
        else:
            got = await self._queue.get()
        if self._done:  # closed while waiting: whatever woke us, there is nothing more
            raise StopAsyncIteration
        if isinstance(got, list):
            self._queued -= len(got)
            replay_readahead_depth.dec(len(got))
            self._batch, self._pos = got, 1
            return got[0]
        self._done = True
        if isinstance(got, _Failed):
            raise got.error
        if got is _Mark.STOPPED:
            _report("replay_source_producer_stopped")
            raise ReplayInternalError
        raise StopAsyncIteration

    def _release(self) -> None:
        """Drop every batch held, return the gauge and leave an end marker for a parked consumer
        (the queue was just emptied, so it fits)."""
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(_Mark.END)
        replay_readahead_depth.dec(self._queued)
        self._queued = 0
        self._batch, self._pos = [], 0
        if self._task is not None and self._task.done():
            self._task = None  # an ended task keeps its exception, and that the frame and its batch

    async def _produce(self) -> None:
        outcome: _Failed | _Mark = _Mark.END
        try:
            batches = self._merge.batches(
                max_events=self._plan.batch_events, max_bytes=self._plan.cut_bytes
            )
            async with aclosing(batches):
                async for batch in batches:
                    if self._done:  # closed while a read was in flight: queue nothing for it
                        return
                    await self._queue.put(batch)  # blocks while full: storage reads stop
                    self._queued += len(batch)
                    replay_readahead_depth.inc(len(batch))
                    await asyncio.sleep(0)  # C-2.17: a batch is 1-3 ms of merge work, not a fill
        except Exception as exc:  # reaches the consumer after every batch queued before it
            outcome = _failure(exc)
        if self._done:
            return
        await self._queue.put(outcome)
