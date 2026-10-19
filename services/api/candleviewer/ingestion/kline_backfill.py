"""Kline backfill service (E08-S06): paged history fetch, local cache-first
reads, rate-limit-safe paging and coverage-index-driven resume.

Kept in `ingestion` (M6) per the ticket's repo-paths guidance; M6 may not
import `candleviewer.storage` directly (C-3.1), so the cache dependency is a
narrow, locally-declared `Protocol` (mirrors `instruments_refresh.py`'s
`InstrumentsRepositoryLike` pattern) — the composition root (`candleviewer.
api`) wires the concrete `MarketDataRepository`/`QuestDbMarketDataRepository`
in without this module ever importing `candleviewer.storage`.

Design, tied to the ticket's Gherkin scenarios:
- "Backfill": `backfill_range` pages from `fetch_klines` (already-normalised
  `KlineEvent`s, ascending — see `exchange.base.ports.MarketDataPort`) until
  the requested range's coverage holes are closed, reporting progress via
  the injected `on_progress` callback after each page.
- "Cache hit": `read_range` first asks the injected cache reader for
  already-covered data and only calls `backfill_range` for the
  `CoverageIndex.holes()` of the request — a fully-covered request never
  touches the exchange.
- "Rate limited": `_fetch_page_with_retry` catches the exchange's
  rate-limit error, backs off with full jitter, and retries the same page;
  it never lets one throttled page fail the whole `backfill_range` call —
  rows already fetched and persisted before the throttle stay in the cache
  and are returned to the caller as partial progress.
- "Descending payload ordered correctly": `fetch_klines` already returns
  ascending-by-`start` `KlineEvent`s (E08-T02's adapter reverses the exchange's
  native descending order), so this module only has to preserve that order
  end to end and never re-sort by anything but `start`; a duplicate `start`
  across two pages is deduped by the storage layer's `(symbol, interval,
  ts_us)` write key, not re-implemented here.
- "Unconfirmed bar not cached as final": rows with `confirmed=False` are
  never included in what gets persisted as a *closed* range — see
  `_split_confirmed` — and the coverage index only marks a sub-range
  covered up to the start of the first unconfirmed row in a page (so a
  later, now-confirmed re-fetch of that same tail is still attempted).
- "Interrupted backfill resumes": `CoverageIndex` (kline_coverage.py) is the
  single source of truth for what has been fetched; a fresh
  `KlineBackfillService` reconstructed after a restart calls
  `load_coverage_from_cache` to rebuild it from whatever the repository
  already persisted, then `read_range`/`backfill_range` only ever fetch the
  remaining holes.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import random
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from candleviewer.domain.klines import KlinePageRejected
from candleviewer.domain.primitives import Symbol, TsUs
from candleviewer.exchange.base.errors import RateLimitError
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.errors import IngestionError
from candleviewer.ingestion.kline_coverage import CoverageIndex, Range, bar_open_us
from candleviewer.ingestion.metrics import (
    kline_backfill_duration_seconds,
    kline_backfill_jobs_total,
    kline_backfill_pages_rejected_total,
    kline_backfill_pages_total,
    kline_backfill_rate_limited_total,
    kline_cache_hit_ratio,
    kline_coverage_holes,
    symbol_label,
)
from candleviewer.observability.context import spawn

_MIN_BACKOFF_S = 1.0
#: SR-E12-08: full jitter from 1 s to 60 s.
_MAX_BACKOFF_S = 60.0
_PAGE_LIMIT = 1000
#: SR-E12-08 ceilings (E12 STRIDE model, BR-33).
MAX_PAGES_PER_JOB = 400
MAX_CONSECUTIVE_RATE_LIMITS = 5
#: Upper bound on `(symbol, interval)` keys whose coverage/lock state is kept in memory.
MAX_TRACKED_KEYS = 512
#: Progress `status` while a rate-limit backoff is pending: the UI shows "loading older bars…"
#: over the partial result instead of blocking (E12-S05 "Rate limited").
STATUS_LOADING_OLDER = "loading_older_bars"


def _wall_now_us() -> int:
    return time.time_ns() // 1000


class KlineFetcher(Protocol):
    """Structural type for `exchange.base.ports.MarketDataPort.fetch_klines`
    — declared locally so this module never imports the exchange adapter package
    directly (only `exchange.base` types, which M6 is allowed)."""

    async def __call__(
        self,
        symbol: Symbol,
        interval: str,
        start: TsUs,
        end: TsUs,
        limit: int = 1000,
    ) -> Sequence[KlineEvent]: ...


class KlineRowLike(Protocol):
    """The subset of `storage.repositories.rows.KlineRow` this module reads
    back from the cache — declared structurally so this module never
    imports `candleviewer.storage`."""

    @property
    def ts_us(self) -> int: ...
    @property
    def confirmed(self) -> bool: ...


class KlineCacheLike(Protocol):
    """Structural type for the storage-layer cache this service reads from
    and writes to. Matches `MarketDataRepository.read_klines`/
    `write_klines` (`storage/repositories/market_data.py`); the composition
    root injects the real repository (or the in-memory fake in tests)."""

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> Sequence[KlineRowLike]: ...

    async def write_klines(self, rows: Sequence[object]) -> None: ...


class ProgressCallback(Protocol):
    """Invoked after every fetched page (ticket "Backfill" scenario:
    "progress reported"). `fraction` is `covered_us / total_us` for the
    range currently being backfilled, in `[0.0, 1.0]`."""

    def __call__(self, *, symbol: str, interval: str, fraction: float, status: str) -> None: ...


class KlineBackfillError(IngestionError):
    """Raised only when a page could not be fetched after every retry —
    the caller still gets whatever partial rows were persisted before the
    failure (ticket "Rate limited" scenario: "partial result stays
    usable")."""


def _row_payload(
    *, symbol: str, interval: str, event: KlineEvent, source: str
) -> dict[str, object]:
    """A plain dict shaped like `storage.repositories.rows.KlineRow`'s
    fields — returned as a dict (not the dataclass itself) so this module
    stays free of the `candleviewer.storage` import; the composition root's
    cache adapter constructs the real `KlineRow` from this shape."""
    return {
        "ts_us": event.start,
        "symbol": symbol,
        "interval": interval,
        "open": str(event.open),
        "high": str(event.high),
        "low": str(event.low),
        "close": str(event.close),
        "volume": str(event.volume),
        "turnover": str(event.turnover),
        "confirmed": event.confirmed,
        "source": source,
    }


def _split_confirmed(events: Sequence[KlineEvent]) -> tuple[list[KlineEvent], TsUs | None]:
    """Split `events` (ascending by `start`) into the rows safe to persist
    as closed history plus the `start` of the first unconfirmed row, if any
    (ticket "Unconfirmed bar not cached as final" scenario). Only a
    *trailing* unconfirmed row is expected (the newest bar, still forming);
    everything at or after it is excluded from the coverage-covered set."""
    for idx, event in enumerate(events):
        if not event.confirmed:
            return list(events[:idx]), event.start
    return list(events), None


KlineSink = Callable[[str, str, Sequence[KlineEvent]], Awaitable[None]]
"""Optional second sink for confirmed klines: the composition root adapts it to
`bars.kline_rows.submit_kline_bars` (NULL order-flow columns, `source=kline`, never over tape).
Declared as a plain callable so `ingestion` never imports `bars` (C-3.1)."""


@dataclass(slots=True)
class BackfillResult:
    """Outcome of one backfill job. `partial=True` means the window was not fully covered;
    every page fetched before the stop is persisted and included in `fetched` (ticket "Rate
    limited": the partial result stays usable). `stop_reason` is a bounded label:
    `""` (complete), `fetch_failed`, `rate_limited`, `page_rejected`, `page_ceiling`."""

    fetched: list[KlineEvent]
    partial: bool
    pages: int = 0
    stop_reason: str = ""


class _Stop(Exception):
    """Internal: ends the current job, keeping everything already persisted."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class _Job:
    """Per-job SR-E12-08 counters (shared across every hole of one request)."""

    pages: int = 0
    consecutive_limits: int = 0


class KlineBackfillService:
    """Cache-first kline reads with rate-limit-safe, resumable, bounded paging.

    Every dependency (fetcher, cache, clock, sleep, jitter source, progress callback, kline sink)
    is injected so this class is unit-testable without a network or a database (C-13.2). One
    `CoverageIndex` per `(symbol, interval)` is kept in memory; `load_coverage_from_cache`
    rebuilds it after a restart. #3808: each index's horizon is the open time of the bar
    containing `now_us()` (the host clock, as the adapter's `confirmed` flag uses), and a page
    proves coverage only up to the newest bar the venue has returned, so no window, whoever
    requested it, can make the shared index claim bars that do not exist yet.

    SR-E12-08 / BR-33: at most `max_pages` pages per job, **one job per (symbol, interval)**
    (a concurrent request joins the running job), at most `max_concurrent_jobs` jobs at once,
    and a job stops (keeping its partial result) after `max_consecutive_rate_limits`
    consecutive rate-limit responses. Fetches use the adapter's `MARKET_DATA` bucket — the
    lowest REST class, separate from the stop/cancel/SL reserve (C-12.7).

    "Lowest ingestion lane" (SR-E12-08, BR-33): the #1957 `ingestion/dispatch.py` lanes order
    *inbound WS frames*; this service makes outbound REST calls and emits no frames, so it has
    no dispatch lane to join. Its priority is enforced instead by the governor's `MARKET_DATA`
    bucket (never the order/position reserve), at most `max_concurrent_jobs` jobs and the page
    ceiling. Bar emission onto the bars topic — where a lane would apply — is wired in part 2 /
    E12-T05 (#2045 / #398); lane assignment is deferred to that wiring.
    """

    def __init__(
        self,
        *,
        fetch_klines: KlineFetcher,
        cache: KlineCacheLike,
        source: str = "rest",
        max_retries: int = 5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = random.random,
        on_progress: ProgressCallback | None = None,
        kline_sink: KlineSink | None = None,
        max_pages: int = MAX_PAGES_PER_JOB,
        max_consecutive_rate_limits: int = MAX_CONSECUTIVE_RATE_LIMITS,
        max_concurrent_jobs: int = 2,
        page_limit: int = _PAGE_LIMIT,
        max_tracked_keys: int = MAX_TRACKED_KEYS,
        now_us: Callable[[], int] = _wall_now_us,
    ) -> None:
        self._fetch_klines = fetch_klines
        self._cache = cache
        self._source = source
        self._max_retries = max(1, max_retries)
        self._sleep = sleep
        self._random = random_fn
        self._on_progress = on_progress
        self._kline_sink = kline_sink
        self._max_pages = max(1, min(max_pages, MAX_PAGES_PER_JOB))
        self._max_limits = max(1, min(max_consecutive_rate_limits, MAX_CONSECUTIVE_RATE_LIMITS))
        self._page_limit = max(1, min(page_limit, _PAGE_LIMIT))
        self._job_slots = asyncio.Semaphore(max(1, max_concurrent_jobs))
        self._max_keys = max(1, max_tracked_keys)
        self._now_us = now_us
        self._coverage: OrderedDict[tuple[str, str], CoverageIndex] = OrderedDict()
        #: End (exclusive) of the newest bar the venue has returned per key: it has formed every
        #: bar before it, so an empty or short page proves nothing past it.
        self._newest: dict[tuple[str, str], int] = {}
        self._jobs: dict[tuple[str, str], asyncio.Task[BackfillResult]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _index_for(self, symbol: str, interval: str) -> CoverageIndex:
        key = (symbol, interval)
        index = self._coverage.get(key)
        if index is None:
            index = self._coverage[key] = CoverageIndex(
                horizon_us=lambda: bar_open_us(self._now_us(), interval)
            )
            self._evict()
        self._coverage.move_to_end(key)
        return index

    def _evict(self) -> None:
        """LRU-bound the per-key state (SR-E12-08 defence in depth; the route also refuses
        unknown symbols). A key with a running job is never evicted; an evicted key only
        loses its in-memory coverage, which `load_coverage_from_cache` rebuilds."""
        for key in list(self._coverage):
            if len(self._coverage) <= self._max_keys:
                break
            if self.job_running(*key):
                continue
            del self._coverage[key]
            self._newest.pop(key, None)
            lock = self._locks.get(key)
            if lock is not None and not lock.locked():
                del self._locks[key]

    @property
    def tracked_keys(self) -> int:
        return len(self._coverage)

    def coverage(self, symbol: str, interval: str) -> CoverageIndex | None:
        """The in-memory coverage index (for `meta.coverage_holes`), if one exists."""
        return self._coverage.get((symbol, interval))

    def job_running(self, symbol: str, interval: str) -> bool:
        task = self._jobs.get((symbol, interval))
        return task is not None and not task.done()

    async def load_coverage_from_cache(self, symbol: str, interval: str, rng: Range) -> None:
        """Rebuild the coverage index for `(symbol, interval)` from the repository (ticket
        "Interrupted backfill resumes"). Marks covered only the contiguous confirmed spans
        actually present, so a hole left by an interrupted backfill is never masked."""
        rows = await self._cache.read_klines(symbol, interval, rng)
        index = self._index_for(symbol, interval)
        confirmed_rows = sorted((r for r in rows if r.confirmed), key=lambda r: r.ts_us)
        if not confirmed_rows:
            return
        span_start = prev_ts = confirmed_rows[0].ts_us
        # Bar width = smallest gap between cached rows (a single row is a 1 µs span).
        bar_width_us = 1
        if len(confirmed_rows) > 1:
            bar_width_us = min(b.ts_us - a.ts_us for a, b in itertools.pairwise(confirmed_rows))
        for row in confirmed_rows[1:]:
            if row.ts_us - prev_ts > bar_width_us:
                index.mark_covered(Range(span_start, prev_ts + bar_width_us))
                span_start = row.ts_us
            prev_ts = row.ts_us
        index.mark_covered(Range(span_start, prev_ts + bar_width_us))

    async def read_range(self, symbol: str, interval: str, rng: Range) -> BackfillResult:
        """Cache-first read (ticket "Cache hit"): only the coverage holes of `rng` are fetched;
        a fully covered request never touches the exchange. Serialised per key (one job)."""
        lock = self._locks.setdefault((symbol, interval), asyncio.Lock())
        async with lock, self._job_slots:
            return await self._run_job(symbol, interval, rng)

    async def backfill_range(self, symbol: str, interval: str, rng: Range) -> BackfillResult:
        """Scheduled N-day backfill entry point; same semantics as `read_range`."""
        return await self.read_range(symbol, interval, rng)

    def start_backfill(
        self, symbol: str, interval: str, rng: Range
    ) -> asyncio.Task[BackfillResult]:
        """Run the backfill as a tracked background task so the chart is interactive before
        paging finishes (ticket "Backfill on chart open"). One job per `(symbol, interval)`:
        while one runs, the same task is returned instead of starting a second (SR-E12-08)."""
        key = (symbol, interval)
        running = self._jobs.get(key)
        if running is not None and not running.done():
            return running
        task = spawn(self.read_range(symbol, interval, rng), name=f"kline-backfill:{symbol}")
        self._jobs[key] = task
        task.add_done_callback(functools.partial(self._job_done, key))
        return task

    def _job_done(self, key: tuple[str, str], task: asyncio.Task[BackfillResult]) -> None:
        if self._jobs.get(key) is task:
            del self._jobs[key]
        if not task.cancelled() and task.exception() is not None:
            get_logger(__name__).error(
                "kline_backfill_job_crashed",
                symbol=key[0],
                interval=key[1],
                error=type(task.exception()).__name__,
            )

    async def aclose(self) -> None:
        """Cancel and await every running job (C-2.18: no orphaned task)."""
        tasks = list(self._jobs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_job(self, symbol: str, interval: str, rng: Range) -> BackfillResult:
        index = self._index_for(symbol, interval)
        holes = index.holes(rng)
        total_us = max(1, rng.end_us - rng.start_us)
        covered_us = total_us - sum(h.end_us - h.start_us for h in holes)
        labels = {"symbol": symbol_label(symbol), "interval": interval}
        kline_cache_hit_ratio.labels(**labels).set(covered_us / total_us)
        result = BackfillResult(fetched=[], partial=False)
        if not holes:
            return result
        log = get_logger(__name__)
        log.info("kline_backfill_started", symbol=symbol, interval=interval,
                 start_us=rng.start_us, end_us=rng.end_us, holes=len(holes))  # fmt: skip
        job = _Job()
        with kline_backfill_duration_seconds.labels(**labels).time():
            # Newest hole first: the chart's visible tail fills before older history.
            for hole in reversed(holes):
                try:
                    await self._backfill_hole(symbol, interval, hole, rng, job, result)
                except _Stop as stop:
                    result.partial, result.stop_reason = True, stop.reason
                    break
                except KlineBackfillError:
                    result.partial, result.stop_reason = True, "fetch_failed"
                    break
        result.pages = job.pages
        kline_coverage_holes.labels(**labels).set(len(index.holes(rng)))
        outcome = result.stop_reason or "complete"
        kline_backfill_jobs_total.labels(**labels, result=outcome).inc()
        # SR-E12-10 run log: symbol, interval, window, page count, outcome.
        log.info("kline_backfill_finished", symbol=symbol, interval=interval,
                 start_us=rng.start_us, end_us=rng.end_us, pages=job.pages,
                 rows=len(result.fetched), outcome=outcome)  # fmt: skip
        self._progress(symbol, interval, rng, "partial" if result.partial else "done")
        return result

    def _progress(self, symbol: str, interval: str, rng: Range, status: str) -> None:
        if self._on_progress is None:
            return
        total_us = max(1, rng.end_us - rng.start_us)
        remaining = sum(h.end_us - h.start_us for h in self._index_for(symbol, interval).holes(rng))
        fraction = min(1.0, max(0.0, 1.0 - remaining / total_us))
        self._on_progress(symbol=symbol, interval=interval, fraction=fraction, status=status)

    async def _backfill_hole(
        self,
        symbol: str,
        interval: str,
        hole: Range,
        requested: Range,
        job: _Job,
        result: BackfillResult,
    ) -> None:
        """Fill `hole` page by page, newest sub-hole first. Ordering-agnostic: a full page
        proves coverage only of the span it actually returned (the live port serves the
        newest `limit` rows of a window, other ports may serve the oldest); a short page holds
        every bar the venue has in its window, so it proves that window up to the newest bar
        the venue is known to have. Past that bar an empty or short page proves nothing (#3808:
        those bars may not exist yet), so that part waits for a later job while older
        sub-holes are still paged. Raises `_Stop` to end the job; everything persisted stays."""
        key = (symbol, interval)
        index = self._index_for(symbol, interval)
        ceiling = hole.end_us  # sub-holes at or after it wait for a later job
        while True:
            pending = index.holes(Range(hole.start_us, ceiling))
            if not pending:
                return
            target = pending[-1]
            if job.pages >= self._max_pages:
                raise _Stop("page_ceiling")
            page = await self._fetch_page_with_retry(
                symbol, interval, target.start_us, target.end_us - 1, job
            )
            job.pages += 1
            confirmed_events, unconfirmed_start = _split_confirmed(page)
            if confirmed_events:
                rows = [
                    _row_payload(symbol=symbol, interval=interval, event=e, source=self._source)
                    for e in confirmed_events
                ]
                await self._cache.write_klines(rows)
                if self._kline_sink is not None:
                    await self._kline_sink(symbol, interval, confirmed_events)
            if page and key in self._coverage:  # an evicted key keeps no frontier (bounded)
                newest = max(e.end for e in page) + 1
                self._newest[key] = max(newest, self._newest.get(key, newest))
            if len(page) >= self._page_limit:
                proven = Range(max(target.start_us, page[0].start), page[-1].end + 1)
            else:
                known = min(target.end_us, self._newest.get(key, target.start_us))
                proven = Range(target.start_us, max(target.start_us, known))
                ceiling = target.start_us
            if unconfirmed_start is not None:  # forming bar: returned, never covered
                proven = Range(proven.start_us, min(proven.end_us, unconfirmed_start))
            proven = Range(proven.start_us, min(proven.end_us, target.end_us))
            if proven.end_us > proven.start_us:
                index.mark_covered(proven)
            result.fetched.extend(page)
            result.fetched.sort(key=lambda e: e.start)
            self._progress(symbol, interval, requested, "fetching")
            progressed = index.holes(Range(hole.start_us, ceiling)) != pending
            if unconfirmed_start is not None or not progressed:
                return  # reached the forming bar (nothing newer exists yet) or no progress

    async def _fetch_page_with_retry(
        self, symbol: str, interval: str, start_us: TsUs, end_us: TsUs, job: _Job | None = None
    ) -> Sequence[KlineEvent]:
        """One page, retried with full-jitter exponential backoff (1 s .. 60 s).

        - `KlinePageRejected` (SR-E12-09): never retried; the job stops, prior pages kept.
        - `RateLimitError` (10006/10018/...): counted per job; the UI is told
          `loading_older_bars` while backing off; `max_consecutive_rate_limits` in a row stops
          the job (SR-E12-08). The adapter has already applied the shared governor's
          `hold_ip()` for 10018, so this backoff is on top of — not instead of — that limiter.
        - anything else: transient, up to `max_retries` attempts, then `fetch_failed`.
        """
        job = job if job is not None else _Job()
        labels = {"symbol": symbol_label(symbol), "interval": interval}
        log = get_logger(__name__)
        attempt = 0
        last_error: Exception | None = None
        while attempt < self._max_retries:
            try:
                page = await self._fetch_klines(
                    symbol, interval, start_us, end_us, limit=self._page_limit
                )
            except KlinePageRejected as exc:
                kline_backfill_pages_total.labels(**labels, result="rejected").inc()
                kline_backfill_pages_rejected_total.labels(**labels, reason=exc.reason).inc()
                log.warning("kline_backfill_page_rejected", symbol=symbol, interval=interval,
                            reason=exc.reason, start_us=start_us, end_us=end_us)  # fmt: skip
                raise _Stop("page_rejected") from exc
            except RateLimitError as exc:
                last_error = exc
                job.consecutive_limits += 1
                kline_backfill_rate_limited_total.labels(**labels).inc()
                kline_backfill_pages_total.labels(**labels, result="rate_limited").inc()
                if job.consecutive_limits >= self._max_limits:
                    log.warning("kline_backfill_rate_limit_abort", symbol=symbol,
                                interval=interval, consecutive=job.consecutive_limits)  # fmt: skip
                    raise _Stop("rate_limited") from exc
                delay = self._backoff(job.consecutive_limits - 1)
                log.warning("kline_backfill_rate_limited", symbol=symbol, interval=interval,
                            backoff_s=round(delay, 3),
                            consecutive=job.consecutive_limits)  # fmt: skip
                if self._on_progress is not None:
                    self._on_progress(symbol=symbol, interval=interval,
                                      fraction=-1.0, status=STATUS_LOADING_OLDER)  # fmt: skip
                await self._sleep(delay)
                continue  # a rate limit is governed by its own ceiling, not `max_retries`
            except Exception as exc:  # transient (5xx, transport): retried, then surfaced
                last_error = exc
                attempt += 1
                kline_backfill_pages_total.labels(**labels, result="retry").inc()
                log.warning("kline_backfill_page_retry", symbol=symbol, interval=interval,
                            attempt=attempt, error=type(exc).__name__)  # fmt: skip
                if attempt < self._max_retries:
                    await self._sleep(self._backoff(attempt - 1))
                continue
            job.consecutive_limits = 0
            kline_backfill_pages_total.labels(**labels, result="ok").inc()
            return page
        kline_backfill_pages_total.labels(**labels, result="error").inc()
        log.warning("kline_backfill_page_failed", symbol=symbol, interval=interval,
                    error=type(last_error).__name__)  # fmt: skip
        raise KlineBackfillError(
            f"kline page fetch failed for {symbol}/{interval} after {self._max_retries} attempts"
        ) from last_error

    def _backoff(self, attempt: int) -> float:
        """Full jitter in `[_MIN_BACKOFF_S, min(_MAX_BACKOFF_S, _MIN_BACKOFF_S * 2**attempt)]`."""
        cap = min(_MAX_BACKOFF_S, _MIN_BACKOFF_S * (2 ** min(attempt, 16)))
        return float(_MIN_BACKOFF_S + (cap - _MIN_BACKOFF_S) * self._random())


__all__ = [
    "MAX_CONSECUTIVE_RATE_LIMITS",
    "MAX_PAGES_PER_JOB",
    "MAX_TRACKED_KEYS",
    "STATUS_LOADING_OLDER",
    "BackfillResult",
    "KlineBackfillError",
    "KlineBackfillService",
    "KlineCacheLike",
    "KlineFetcher",
    "KlineSink",
    "ProgressCallback",
]
