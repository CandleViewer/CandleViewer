"""Async batched bars write path (E12-T02, #345; BR-34 bounded buffer).

Layering (who owns what): `IlpWriter` owns reconnect, at-least-once delivery and never-drop of
rows it has admitted (`storage/questdb/ilp_writer.py`). `BarWriter` only maps and **orders**.
It drains one batch at a time (a single in-flight sink call), so a retried batch always lands
before any later batch for the same key: an original close can never overwrite a later amended
close (DEDUP keeps the last write). Errors are classified: *permanent* (invalid row, closed
sink) are surfaced as a typed error, counted and not retried; *transient* get a bounded
exponential backoff, then the batch is counted failed (`bars_write_failed_total{reason}`) and
the writer is marked `degraded` (sticky until a success leaves the buffer empty). Rows of a
permanently failed or exhausted table batch ARE dropped; they are counted by row.
Producers never lose rows to a full buffer (`submit()` awaits).
`stop(timeout_s)` is bounded (mirrors IlpWriter's 30 s contract) and returns the remaining count.
BR-34: a *new* spec is refused (`BarBufferFull`) while the buffer is saturated.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

import structlog

from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.rows import (
    BAR_PARAM_CAPACITY,
    LIVE_GENERATION,
    SOURCE_RANK,
    BarParamCapacityExceeded,
    BarPersistError,
    bar_param_for,
    bar_row,
    table_for,
)
from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import Counter, Gauge, Histogram


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


bars_rows_written_total = Counter(
    "bars_rows_written_total", "Bar rows handed to QuestDB.", ["kind"]
)
bars_write_queue_depth = Gauge("bars_write_queue_depth", "Rows waiting in the bars write buffer.")
bars_write_saturation_total = Counter(
    "bars_write_saturation_total", "Submits that had to wait for buffer space (backpressure)."
)
bars_write_failed_total = Counter(
    "bars_write_failed_total",
    "Bar ROWS dropped by failed batches (reason: permanent | transient_exhausted).",
    ["reason"],
)
DEFAULT_STOP_TIMEOUT_S = 30.0
MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 0.5
BACKOFF_MAX_S = 10.0
bars_write_latency_seconds = Histogram(
    "bars_write_latency_seconds", "Wall time of one batched sink write."
)
bars_symbol_cardinality = Gauge(
    "bars_symbol_cardinality", "Distinct bar_param values seen per table.", ["table"]
)


bars_source_overwrite_refused_total = Counter(
    "bars_source_overwrite_refused_total",
    "Writes refused because a lower-precedence source would overwrite a higher one.",
    ["from_source", "to_source"],
)
#: Bound on the per-process precedence memory (LRU; SR-E12-05).
MAX_TRACKED_ROWS = 200_000


class SourceOverwriteRefused(BarsError):
    """SR-E12-10/BR-07: a kline row may not overwrite a tape row at the same dedup key."""


class BarWritePermanentError(BarsError):
    """A batch failed for a reason a retry cannot fix (invalid row, closed sink)."""


def default_is_permanent(exc: Exception) -> bool:
    """Bad-input errors cannot be fixed by a retry. The composition root passes a classifier that
    also knows the storage errors (`IlpRowError`, closed `StorageTierUnavailable`): `bars` must
    not import `storage` (C-3.1)."""
    return isinstance(exc, (ValueError, TypeError))


class BarBufferFull(BarsError):
    """BR-34: the write buffer is saturated; a new spec is refused (existing series still wait)."""


class RowSink(Protocol):
    async def write_rows(
        self, table: str, rows: list[dict[str, object]], ts_us_key: str
    ) -> None: ...


class BarWriter:
    def __init__(
        self,
        sink: RowSink,
        *,
        max_buffered: int = 10_000,
        batch_rows: int = 500,
        refuse_new_specs_at: float = 0.9,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        is_permanent: Callable[[Exception], bool] = default_is_permanent,
    ) -> None:
        if max_buffered < 1 or batch_rows < 1:
            raise ValueError("max_buffered and batch_rows must be >= 1")
        self._sink = sink
        self._queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue(max_buffered)
        self._batch_rows = batch_rows
        self._sleep = sleep
        self._is_permanent = is_permanent
        self.last_error: BarWritePermanentError | None = None
        self._inflight_rows = 0
        self.degraded = False
        self._refuse_at = max(1, int(max_buffered * refuse_new_specs_at))
        self._params: dict[str, set[str]] = {}
        self._known_specs: set[tuple[str, str]] = set()
        self._task: asyncio.Task[None] | None = None
        self._sources: OrderedDict[tuple[str, str, int], str] = OrderedDict()

    @property
    def healthy(self) -> bool:
        """False at/over the refusal watermark (a failing sink shows up as a growing buffer)."""
        return self._queue.qsize() < self._refuse_at

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._drain(), name="bars-writer-drain")

    def _admit_param(self, table: str, spec: BarSpec) -> None:
        key = (table, spec.spec_hash)
        if key in self._known_specs:
            return
        if not self.healthy:
            raise BarBufferFull("The bars write buffer is saturated; the new bar spec is refused.")
        params = self._params.setdefault(table, set())
        param = bar_param_for(spec)
        if param not in params and len(params) >= BAR_PARAM_CAPACITY:
            _log().error("bar_param_capacity_exceeded", table=table, capacity=BAR_PARAM_CAPACITY)
            raise BarParamCapacityExceeded(
                f"{table} already holds {BAR_PARAM_CAPACITY} bar_params."
            )
        params.add(param)
        bars_symbol_cardinality.labels(table).set(len(params))
        self._known_specs.add(key)

    def _check_precedence(
        self, table: str, spec: BarSpec, rows: list[dict[str, object]], source: str
    ) -> None:
        for row in rows:
            prior = self._sources.get(
                (table, spec.spec_hash + str(row["symbol"]), int(str(row["ts"])))
            )
            if prior is not None and SOURCE_RANK[source] < SOURCE_RANK[prior]:
                bars_source_overwrite_refused_total.labels(source, prior).inc()
                _log().warning(
                    "bars_source_overwrite_refused", table=table, spec_hash=spec.spec_hash
                )
                raise SourceOverwriteRefused(
                    f"A '{source}' bar may not overwrite an existing '{prior}' bar."
                )

    def _record_sources(
        self, table: str, spec: BarSpec, rows: list[dict[str, object]], source: str
    ) -> None:
        for row in rows:
            key = (table, spec.spec_hash + str(row["symbol"]), int(str(row["ts"])))
            self._sources[key] = source
            self._sources.move_to_end(key)
        while len(self._sources) > MAX_TRACKED_ROWS:
            self._sources.popitem(last=False)

    async def submit(
        self,
        bars: Sequence[Bar],
        spec: BarSpec,
        *,
        source: str = "tape",
        generation: int = LIVE_GENERATION,
    ) -> None:
        """Queue rows (validates all first: one bad, synthetic or lower-precedence bar rejects all).
        `generation` is the series epoch stamped on every row (`WriterSink` passes the emission's).

        Precedence is enforced against rows written by this process; a read-side check against
        the stored row's `source` is the E12-T05 backfill caller's job (it owns the read path).
        """
        await self.submit_rows(
            [bar_row(b, spec, source=source, generation=generation) for b in bars],
            spec,
            source=source,
        )

    async def submit_rows(
        self, rows: list[dict[str, object]], spec: BarSpec, *, source: str
    ) -> None:
        """Queue pre-mapped rows (E12-S05 kline rows with NULL order-flow columns) through the
        same precedence, capacity and backpressure path as `submit`."""
        if source not in SOURCE_RANK or any(r.get("source") != source for r in rows):
            raise BarPersistError(f"Every row must carry source '{source}'.")
        table = table_for(spec)
        self._check_precedence(table, spec, rows, source)
        self._admit_param(table, spec)
        self._record_sources(table, spec, rows, source)
        for row in rows:
            if self._queue.full():
                bars_write_saturation_total.inc()
                _log().warning("bars_write_saturated", depth=self._queue.qsize(), table=table)
            await self._queue.put((table, row))  # awaits space - never discards
        bars_write_queue_depth.set(self._queue.qsize())

    async def _drain(self) -> None:
        while True:
            table, row = await self._queue.get()
            batch = {table: [row]}
            while sum(map(len, batch.values())) < self._batch_rows and not self._queue.empty():
                t, r = self._queue.get_nowait()
                batch.setdefault(t, []).append(r)
            self._inflight_rows = sum(map(len, batch.values()))
            try:
                for tbl, rows in batch.items():
                    await self._write_one(tbl, rows)
            finally:
                for _ in range(self._inflight_rows):
                    self._queue.task_done()
                self._inflight_rows = 0
                bars_write_queue_depth.set(self._queue.qsize())

    async def _write_one(self, table: str, rows: list[dict[str, object]]) -> None:
        """One table batch, in order: retry transient errors (bounded), never reorder."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                await self._sink.write_rows(table, rows, "ts")
            except Exception as exc:
                if self._is_permanent(exc):
                    self.last_error = BarWritePermanentError(type(exc).__name__)
                    bars_write_failed_total.labels("permanent").inc(
                        len(rows)
                    )  # rows lost, never silent
                    self.degraded = True
                    _log().error(
                        "bars_write_permanent_failure", table=table, error=type(exc).__name__
                    )
                    return
                if attempt == MAX_ATTEMPTS:
                    bars_write_failed_total.labels("transient_exhausted").inc(len(rows))
                    self.degraded = True
                    _log().error("bars_write_exhausted", table=table, rows=len(rows))
                    return
                await self._sleep(min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (attempt - 1)))
                continue
            if self._queue.empty():  # sticky: cleared only once the buffer has fully drained
                self.degraded = False
            bars_write_latency_seconds.observe(time.monotonic() - started)
            bars_rows_written_total.labels(table.removeprefix("bars_")).inc(len(rows))
            return

    async def stop(self, timeout_s: float | None = DEFAULT_STOP_TIMEOUT_S) -> int:
        """Drain within `timeout_s`; return the number of rows NOT written (0 = clean)."""
        try:
            async with asyncio.timeout(timeout_s):
                await self._queue.join()
        except TimeoutError:
            _log().error("bars_writer_stop_timeout", remaining=self._queue.qsize())
        remaining = self._queue.qsize() + self._inflight_rows
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        return remaining
