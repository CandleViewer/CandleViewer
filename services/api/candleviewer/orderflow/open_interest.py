"""Open-interest service (E24-T01, #665): 1 Hz ticker downsampler, REST backfill, read side.

Module boundary (C-3.1): orderflow may not import `storage`, `ingestion` or the exchange adapter,
so the store and the fetcher are local structural Protocols the composition root injects.

Invariants (STRIDE `docs/security/threat-models/E24-derivatives.md` D5/D8/D12):
- the two series never mix: `1s` is `ws_ticker`, `5min`..`1d` are `rest` (`source_of`);
- a ticker without OI writes nothing, never 0 (BQ-12); one with OI but no OI value writes the
  OI with a NULL value, as the schema allows (`21-database-schema.md` §4.7);
- a missing span is reported in `gaps`, never filled;
- bounds are checked (`deriv_limits`) before the store is read;
- a request can only queue a backfill for a listed symbol, once per `(symbol, interval)` and
  older window, into a bounded queue drained by one worker (concurrency 1 per symbol);
- the "older window" floor is raised only when a job completes, so a failed job (retries
  exhausted, page rejected, store error) lets the next request queue it again;
- a request queues only the span older than the oldest stored point, so a page-capped job is
  resumed below what it wrote and each cycle makes progress;
- every fetcher and store await has its own timeout (`FETCH_TIMEOUT_S`, `STORE_TIMEOUT_S`): a
  fetch that times out is a retryable failure, a store write that does fails the job.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from candleviewer.domain.open_interest import (
    INTERVAL_US,
    REST_INTERVALS,
    SOURCE_WS_TICKER,
    OiFetchFailed,
    OiPage,
    OiPoint,
    OiRowRejected,
    source_of,
)
from candleviewer.orderflow.deriv_limits import (
    CURSOR_MAX_LEN,
    MAX_WINDOW_DAYS_OI,
    DerivInvalidRequest,
    DerivSymbolUnlisted,
    check_limit,
    check_window,
)
from candleviewer.orderflow.deriv_metrics import (
    deriv_oi_backfill_latency_seconds,
    deriv_oi_backfill_pages_total,
    deriv_oi_rows_written_total,
)
from candleviewer.orderflow.funding import FundingInvalidRequest, decode_cursor, encode_cursor
from candleviewer.orderflow.funding_metrics import (
    deriv_upstream_schema_rejected_total,
    symbol_label,
)


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Hard bound on pages per backfill job (200 rows x 200 pages = 40k points).
MAX_PAGES_PER_JOB: Final = 200
MAX_ATTEMPTS: Final = 5
BACKOFF_BASE_S: Final = 1.0
BACKOFF_MAX_S: Final = 60.0
JITTER_FRACTION: Final = 0.2
#: Bounded work queue and bounded set of `(symbol, interval)` keys a request may register.
QUEUE_MAX: Final = 64
MAX_KEYS: Final = 512
#: Per-await bounds in the backfill (C-2.18): one venue page, one store call.
FETCH_TIMEOUT_S: Final = 30.0
STORE_TIMEOUT_S: Final = 30.0
#: A ticker series has a gap when two points are further apart than this.
TICKER_GAP_US: Final = 10_000_000


class _Range(Protocol):
    @property
    def start_us(self) -> int: ...
    @property
    def end_us(self) -> int: ...


class OiStore(Protocol):
    async def write_points(self, rows: Sequence[OiPoint]) -> None: ...

    async def read_points(
        self, symbol: str, interval: str, source: str, rng: _Range, limit: int
    ) -> Sequence[OiPoint]: ...

    async def coverage(self, symbol: str, interval: str, source: str) -> tuple[int, int] | None: ...


class OiFetcher(Protocol):
    """One newest-first page in `[start_us, end_us]`; `cursor` is the venue's own."""

    async def __call__(
        self, symbol: str, interval: str, start_us: int, end_us: int, cursor: str | None
    ) -> OiPage: ...


#: `True` listed, `False` not listed, `None` while the catalogue is not loaded.
ListedLookup = Callable[[str], bool | None]


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start_us: int
    end_us: int


class TickerDownsampler:
    """First ticker per symbol per UTC second, in monotonic seconds.

    Nothing without OI (never a 0); OI without an OI value is kept with a NULL value.
    """

    def __init__(self) -> None:
        self._last_s: dict[str, int] = {}

    def offer(
        self, symbol: str, ts_us: int, oi: Decimal | None, oi_value: Decimal | None
    ) -> OiPoint | None:
        if oi is None:
            return None
        second = ts_us // 1_000_000
        last = self._last_s.get(symbol)
        if last is not None and second <= last:
            return None
        self._last_s[symbol] = second
        return OiPoint(ts_us, symbol, oi, oi_value, "1s", SOURCE_WS_TICKER)

    def forget(self, symbol: str) -> None:
        self._last_s.pop(symbol, None)


class OiBackfill:
    """Bounded queue of `(symbol, interval, window)` jobs, drained by one worker."""

    def __init__(
        self,
        *,
        store: OiStore,
        fetcher: OiFetcher,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float],
        clock_s: Callable[[], float] = time.monotonic,
        fetch_timeout_s: float = FETCH_TIMEOUT_S,
        store_timeout_s: float = STORE_TIMEOUT_S,
    ) -> None:
        self._store, self._fetcher = store, fetcher
        self._fetch_timeout_s, self._store_timeout_s = fetch_timeout_s, store_timeout_s
        self._sleep, self._random, self._clock = sleep, random_fn, clock_s
        self._queue: asyncio.Queue[tuple[str, str, TimeWindow]] = asyncio.Queue(QUEUE_MAX)
        self._pending: set[tuple[str, str]] = set()
        #: Oldest start a COMPLETED job covered per key: a later or equal window queues nothing.
        #: Raised only on success (`run_once`), so a failed job never blocks a re-queue.
        self._floor: dict[tuple[str, str], int] = {}

    def keys(self) -> list[tuple[str, str]]:
        """Every key a request registered: completed or still pending."""
        return sorted(self._floor.keys() | self._pending)

    def request(
        self, symbol: str, interval: str, window: TimeWindow, *, refresh: bool = False
    ) -> bool:
        """Queue a job; False when already pending, already covered, over the key cap or full."""
        key = (symbol, interval)
        if interval not in REST_INTERVALS or key in self._pending:
            return False
        floor = self._floor.get(key)
        if floor is None and len(self._floor.keys() | self._pending) >= MAX_KEYS:
            return False
        if not refresh and floor is not None and window.start_us >= floor:
            return False
        try:
            self._queue.put_nowait((symbol, interval, window))
        except asyncio.QueueFull:
            return False
        self._pending.add(key)
        return True

    async def run(self) -> None:
        """Worker loop (the composition root owns the task)."""
        while True:
            symbol, interval, window = await self._queue.get()
            try:
                await self.run_once(symbol, interval, window)
            except asyncio.CancelledError:
                raise
            except Exception:  # one job never stops the worker; the floor stays where it was
                logger().exception("oi_backfill_job_failed", symbol=symbol_label(symbol))
            finally:
                self._pending.discard((symbol, interval))
                self._queue.task_done()

    async def run_once(self, symbol: str, interval: str, window: TimeWindow) -> bool:
        """Run one job; raise the key's floor only when it completed. Returns completed."""
        _, completed = await self._job(symbol, interval, window)
        if completed:
            key = (symbol, interval)
            floor = self._floor.get(key)
            self._floor[key] = window.start_us if floor is None else min(floor, window.start_us)
        return completed

    async def run_job(self, symbol: str, interval: str, window: TimeWindow) -> int:
        """Page newest-first with the venue cursor until done; returns rows written."""
        written, _ = await self._job(symbol, interval, window)
        return written

    async def _job(self, symbol: str, interval: str, window: TimeWindow) -> tuple[int, bool]:
        """`(rows written, completed)`; not completed on a failed or rejected page, or page cap."""
        label, started, written, cursor = symbol_label(symbol), self._clock(), 0, None
        completed = True
        try:
            for _ in range(MAX_PAGES_PER_JOB):
                page = await self._fetch(symbol, interval, window, cursor)
                if page is None:
                    completed = False
                    break
                deriv_oi_backfill_pages_total.labels(label, interval, "ok").inc()
                for reason in page.rejected_reasons:
                    deriv_upstream_schema_rejected_total.labels("open_interest", reason).inc()
                rows = [p for p in page if window.start_us <= p.ts_us <= window.end_us]
                async with asyncio.timeout(self._store_timeout_s):
                    await self._store.write_points(rows)
                deriv_oi_rows_written_total.labels("rest").inc(len(rows))
                written += len(rows)
                cursor = page.next_cursor
                if cursor is None or not page:
                    break
            else:  # page budget spent with a cursor still present: more history is unfetched
                completed = False
        finally:
            deriv_oi_backfill_latency_seconds.observe(max(0.0, self._clock() - started))
        return written, completed

    async def _fetch(
        self, symbol: str, interval: str, window: TimeWindow, cursor: str | None
    ) -> OiPage | None:
        """One page with jittered exponential backoff; None when the job must stop."""
        label = symbol_label(symbol)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with asyncio.timeout(self._fetch_timeout_s):
                    return await self._fetcher(
                        symbol, interval, window.start_us, window.end_us, cursor
                    )
            except TimeoutError:
                deriv_oi_backfill_pages_total.labels(label, interval, "error").inc()
                logger().warning(
                    "oi_backfill_timeout", symbol=label, interval=interval, attempt=attempt
                )
                if attempt == MAX_ATTEMPTS:
                    return None
                await self._sleep(self.backoff_s(attempt))
                continue
            except OiRowRejected as exc:
                deriv_upstream_schema_rejected_total.labels("open_interest", exc.reason).inc()
                deriv_oi_backfill_pages_total.labels(label, interval, "rejected").inc()
                logger().warning("oi_backfill_page_rejected", symbol=label, reason=exc.reason)
                return None
            except OiFetchFailed as exc:
                deriv_oi_backfill_pages_total.labels(label, interval, "error").inc()
                logger().warning(
                    "oi_backfill_failed",
                    symbol=label,
                    interval=interval,
                    attempt=attempt,
                    http_status=exc.http_status,
                    ret_code=exc.ret_code,
                )
                if not exc.retryable or attempt == MAX_ATTEMPTS:
                    return None
                await self._sleep(self.backoff_s(attempt))
        return None

    def backoff_s(self, attempt: int) -> float:
        base = min(BACKOFF_BASE_S * 2.0 ** (attempt - 1), BACKOFF_MAX_S)
        return float(base * (1 + JITTER_FRACTION * self._random()))


@dataclass(frozen=True, slots=True)
class OiSeries:
    symbol: str
    interval: str
    source: str
    points: tuple[OiPoint, ...]
    next_cursor: str | None
    has_more: bool
    coverage: tuple[int, int] | None
    gaps: tuple[tuple[int, int], ...]


def find_gaps(
    points: Sequence[OiPoint], *, start_us: int, end_us: int, interval: str, tail: bool
) -> tuple[tuple[int, int], ...]:
    """Spans of `[start_us, end_us)` with no point where one was due: more than one native
    interval between points (10 s for the ticker series); the open tail allows two."""
    step = TICKER_GAP_US if interval == "1s" else INTERVAL_US[interval]
    gaps: list[tuple[int, int]] = []
    anchor = start_us
    for p in points:
        if p.ts_us - anchor > step:
            gaps.append((anchor, p.ts_us))
        anchor = p.ts_us
    if tail and end_us - anchor > 2 * step:
        gaps.append((anchor, end_us))
    return tuple(gaps)


class OpenInterestService:
    def __init__(
        self,
        *,
        store: OiStore,
        listed: ListedLookup,
        backfill: OiBackfill | None,
        clock_s: Callable[[], float] = time.time,
    ) -> None:
        self._store, self._listed = store, listed
        self.backfill = backfill
        self._clock_s = clock_s

    @property
    def store(self) -> OiStore:
        """The guarded store, read by the derivatives engine's `/market/metrics` path."""
        return self._store

    async def series(
        self,
        symbol: str,
        *,
        interval: str,
        start_us: int | None,
        end_us: int | None,
        limit: int,
        cursor: str | None,
    ) -> OiSeries:
        now_s = self._clock_s()
        now_us = int(now_s * 1_000_000)
        if cursor is not None and (not cursor or len(cursor) > CURSOR_MAX_LEN):
            raise DerivInvalidRequest("invalid_cursor", "pagination cursor is malformed or expired")
        if interval not in INTERVAL_US:
            raise DerivInvalidRequest("validation_failed", "unknown interval")
        check_limit(limit)
        start, end = check_window(start_us, end_us, now_us=now_us, max_days=MAX_WINDOW_DAYS_OI)
        listed = self._listed(symbol)
        if listed is False:
            raise DerivSymbolUnlisted(symbol)
        key = f"{symbol}:{interval}"  # a cursor is bound to its series, not just its symbol
        read_from = start
        if cursor is not None:
            try:
                read_from = max(start, decode_cursor(cursor, symbol=key, now_s=now_s) + 1)
            except FundingInvalidRequest as exc:
                raise DerivInvalidRequest(exc.code, exc.detail) from exc
        source = source_of(interval)
        coverage = await self._store.coverage(symbol, interval, source)
        rows = list(
            await self._store.read_points(
                symbol, interval, source, TimeWindow(read_from, end), limit + 1
            )
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        if listed and self.backfill is not None and (coverage is None or start < coverage[0]):
            # Only the span below the oldest stored point: a page-capped job leaves its rows,
            # so the next request resumes under them and the floor rises, never from the top.
            older_end = end if coverage is None else min(end, coverage[0] - 1)
            self.backfill.request(symbol, interval, TimeWindow(start, older_end))
        gaps = find_gaps(
            rows,
            start_us=read_from,
            end_us=min(end, now_us),
            interval=interval,
            tail=not has_more,
        )
        return OiSeries(
            symbol=symbol,
            interval=interval,
            source=source,
            points=tuple(rows),
            next_cursor=encode_cursor(key, rows[-1].ts_us, now_s=now_s) if has_more else None,
            has_more=has_more,
            coverage=coverage,
            gaps=gaps,
        )


__all__ = [
    "OiBackfill",
    "OiFetcher",
    "OiSeries",
    "OiStore",
    "OpenInterestService",
    "TickerDownsampler",
    "TimeWindow",
    "find_gaps",
]
