"""Bounded, retrying hot-tier write-behind buffer (#1918, E08-Q03 chaos scenario 11).

Shared by `TradeStream` and `BookStream`. Rules:

* **Never blocks the reader** — `put` is sync; a full buffer evicts the oldest
  row (drop-oldest, C-2.18), counted in `*_writes_dropped_total{reason}`:
  `outage` while the writer is failing, else `queue_full`.
* **A failed batch is never discarded** — `requeue` puts it back at the head
  (order kept), then `backoff()` sleeps an exponential, jittered delay
  (injected sleep/rand; no real sleeps in tests). Rows leave only by a
  successful write or by eviction.
* **Lost rows are never hidden** — every evicted row's `(symbol, ts_us)` is
  folded into an O(1) per-symbol *open lost run* (evictions are oldest-first,
  so the run only grows); the next successful write for that symbol closes
  it. Closed runs are capped per symbol (`MAX_LOST_RUNS`): the two oldest are
  merged (a conservative superset, never hidden), counted in
  `write_behind_lost_runs_truncated_total`. Backfill reads `lost_ranges()`;
  `degraded` feeds the `hot_tier_write_behind` health component. The
  write-behind healer (#1944, `write_behind_heal.py`) takes `closed_ranges()`
  and drops what it healed with `clear()`.
* **At-least-once** — a batch that failed after partially reaching QuestDB
  is resent whole; that is safe only because every hot-tier table declares
  `DEDUP UPSERT KEYS` (`storage/natural_keys.py`).
* **Cancellation** — a batch taken but not written when the write loop is
  cancelled is `restore()`d to the head before `CancelledError` propagates.

Plain code on the hot path (C-2.20); single consumer (the write loop).
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from collections.abc import Awaitable, Callable, Iterable

from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import (
    questdb_write_queue_depth,
    write_behind_lost_runs_truncated_total,
)
from candleviewer.observability.metrics import Counter

BACKOFF_BASE_S = 0.1
BACKOFF_CAP_S = 10.0
_JITTER = random.SystemRandom().random
#: Evictions batched before one counter `inc` (also flushed on take/requeue).
_METRIC_FLUSH_EVERY = 1024
#: Closed lost runs kept per symbol before the oldest two are merged.
MAX_LOST_RUNS = 256


class WriteBehindBuffer[T]:
    def __init__(
        self,
        *,
        table: str,
        maxsize: int,
        dropped: Counter,
        key: Callable[[T], tuple[str, int]],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] | None = None,
        base_s: float = BACKOFF_BASE_S,
        cap_s: float = BACKOFF_CAP_S,
    ) -> None:
        self._table, self._max, self._dropped, self._key = table, maxsize, dropped, key
        self._sleep, self._base, self._cap = sleep, base_s, cap_s
        self._rand = rand if rand is not None else _JITTER
        # Pre-bound children: `.labels()` per row would dominate the hot path.
        self._drop_outage = dropped.labels(reason="outage")
        self._drop_full = dropped.labels(reason="queue_full")
        self._depth = questdb_write_queue_depth.labels(table=table)
        self._rows: deque[T] = deque()
        self._nonempty = asyncio.Event()
        self._open: dict[str, list[int]] = {}  # symbol -> [start_us, end_us) open run
        self._closed: dict[str, deque[Range]] = {}
        self.failures = 0  # consecutive failed writes; 0 = healthy
        self._unflushed = [0, 0]  # [outage, queue_full] evictions not yet on the counters
        self.evicted = 0

    def qsize(self) -> int:
        return len(self._rows)

    def full(self) -> bool:
        return len(self._rows) >= self._max

    @property
    def degraded(self) -> bool:
        return self.failures > 0

    def lost_ranges(self, symbol: str) -> list[Range]:
        """Hot-tier holes for `symbol`, oldest first (closed runs + the open one)."""
        out = list(self._closed.get(symbol, ()))
        run = self._open.get(symbol)
        if run is not None:
            out.append(Range(run[0], run[1]))
        return out

    def lost_symbols(self) -> list[str]:
        """Symbols whose `lost_ranges()` is not empty (closed runs or an open one)."""
        return sorted({*self._closed, *self._open})  # `clear` drops an emptied entry

    def closed_ranges(self, symbol: str) -> list[Range]:
        """`symbol`'s closed lost runs, oldest first. The open run is still growing (at both
        ends: `min` / `max` below), so a heal never takes it (#1944)."""
        return list(self._closed.get(symbol, ()))

    def clear(self, symbol: str, healed: Iterable[Range]) -> int:
        """#1944: drop the closed runs that one healed range wholly covers; returns how many.

        `healed` comes from a snapshot taken before the heal's awaits. A run that changed since
        (two merged at the cap) is no longer covered and stays whole: a run is cleared whole or
        not at all. The open run is never touched. No await: atomic on the event loop against
        `put` / `succeeded`."""
        runs = self._closed.get(symbol)
        if not runs:
            return 0
        done = list(healed)
        kept = deque(
            r
            for r in runs
            if not any(h.start_us <= r.start_us and r.end_us <= h.end_us for h in done)
        )
        removed = len(runs) - len(kept)
        if kept:
            self._closed[symbol] = kept
        else:
            del self._closed[symbol]
        return removed

    def _close_runs(self, symbols: Iterable[str]) -> None:
        for sym in symbols:
            run = self._open.pop(sym, None)
            if run is None:
                continue
            closed = self._closed.setdefault(sym, deque())
            closed.append(Range(run[0], run[1]))
            if len(closed) > MAX_LOST_RUNS:  # merge the two oldest: superset, never hidden
                a, b = closed.popleft(), closed.popleft()
                closed.appendleft(Range(min(a.start_us, b.start_us), max(a.end_us, b.end_us)))
                write_behind_lost_runs_truncated_total.labels(table=self._table).inc()

    def _evict_oldest(self) -> None:
        row = self._rows.popleft()
        self.evicted += 1
        pending = self._unflushed
        pending[0 if self.failures else 1] += 1
        if pending[0] + pending[1] >= _METRIC_FLUSH_EVERY:
            self.flush_metrics()
        sym, ts_us = self._key(row)
        run = self._open.get(sym)
        if run is None:
            self._open[sym] = [ts_us, ts_us + 1]
        else:  # O(1): oldest-first eviction only extends the run
            run[0] = min(run[0], ts_us)
            run[1] = max(run[1], ts_us + 1)

    def flush_metrics(self) -> None:
        """Publish batched eviction counts (one locked `inc` per batch, not per row)."""
        outage, full = self._unflushed
        if outage:
            self._drop_outage.inc(outage)
        if full:
            self._drop_full.inc(full)
        self._unflushed = [0, 0]

    def _gauge(self) -> None:
        self.flush_metrics()
        self._depth.set(len(self._rows))

    def put(self, row: T) -> None:
        if len(self._rows) >= self._max:  # full: depth unchanged, event already set
            self._evict_oldest()
            self._rows.append(row)
            return
        self._rows.append(row)
        self._nonempty.set()
        self._gauge()

    async def take(self, max_batch: int) -> list[T]:
        """Wait for a row, then pop up to `max_batch` oldest-first."""
        while not self._rows:
            self._nonempty.clear()
            await self._nonempty.wait()
        n = min(max_batch, len(self._rows))
        batch = [self._rows.popleft() for _ in range(n)]
        self._gauge()
        return batch

    def requeue(self, rows: Iterable[T]) -> None:
        """Failed write: rows back at the head (order kept); overflow evicts oldest."""
        self.failures += 1
        self.restore(rows)

    def restore(self, rows: Iterable[T]) -> None:
        """Unwritten rows back at the head without counting a failure (cancellation)."""
        self._rows.extendleft(reversed(list(rows)))
        while len(self._rows) > self._max:
            self._evict_oldest()
        if self._rows:
            self._nonempty.set()
        self._gauge()

    def delay_s(self) -> float:
        """Backoff for the current failure streak: base*2^(n-1), capped, x[1, 1.25)."""
        step = min(self._cap, self._base * 2.0 ** max(0, self.failures - 1))
        return step * (1.0 + 0.25 * self._rand())

    async def backoff(self) -> None:
        await self._sleep(self.delay_s())

    def succeeded(self, rows: Iterable[T] = ()) -> None:
        """A write landed: health resets and the written symbols' open lost runs close."""
        self.failures = 0
        if self._open:
            self._close_runs({self._key(r)[0] for r in rows} & self._open.keys())


__all__ = ["BACKOFF_BASE_S", "BACKOFF_CAP_S", "MAX_LOST_RUNS", "WriteBehindBuffer"]
