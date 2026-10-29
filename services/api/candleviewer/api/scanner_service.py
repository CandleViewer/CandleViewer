"""The scan behind `GET /scanner` (E08-T09 PR 2b, #4708; 22 `runScanner`): the inputs, the cache,
single flight and the bound on cache-cold evaluations.

- **Inputs.** The venue-wide ticker snapshot (`UniverseTickerSource`, the one `GET
  /market/tickers` reads, so the venue sees one poller), read again once per cache-cold scan
  (`refresh()`, single flight and at most one venue read per 5 s, shared); the recorded set
  (`RecordingReads`), a symbol `recorded` while its entry, as the caller's view shows it, is
  `recording` or `degraded`, read at most once per view per `ttl_s` whatever the filter (a
  caller varying a bound costs an evaluation, never a store read; an outage is not remembered);
  and the catalogue's trading symbols, when it has a snapshot.
- **Cache.** One serialised body per (view, canonical filter, `sort`, `limit`) for at most
  `ttl_s` (5 s); the view (`restricted`) is in the key because the recorded set differs by it,
  so nothing derived from one view is served to the other. Expired entries go first, then the
  oldest past `max_entries`. A body never outlives the recorded set it was built on: it
  expires `ttl_s` after that set's read at the latest.
- **Single flight.** Requests for one key share one evaluation: an owned task (`spawn`, kept in
  `_tasks` until it ends), each request waiting on it under `asyncio.shield`, so a request that
  is cancelled leaves it to the others (the `profile_cache` precedent).
- **Bound.** At most `max_cold` evaluations run at once (counted as the owned tasks not yet
  done, so one that has ended frees its place before its done-callbacks run); a cache-cold
  request past that is refused at once (`ScannerBusyError`, 429), never queued. A request
  joining a running evaluation does not count.
- **Refusals.** No ticker source, no snapshot within its 15 s bound, no recorded-set store, a
  store outage (of the recorded set or any other input) or an evaluation past its bound:
  `ScannerUnavailableError` (503 `store_unavailable`). Never a row degraded to `live_only`
  because the store is down.

The evaluation itself (`scanner_eval.evaluate`) and the body run in a worker thread. Logs carry
the outcome, the cap and the duration, never a filter value. `aclose()` cancels what is running.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Set
from dataclasses import dataclass
from typing import Any, Final, Protocol

import structlog

from candleviewer.api.scanner_criteria import CRITERIA
from candleviewer.api.scanner_eval import ScanQuery, build_body, evaluate, tickers_input
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.exchange.base.universe import UniverseTickerSource
from candleviewer.observability.context import run_in_thread, spawn
from candleviewer.recorder.control import (
    HIDDEN_CAUSES,
    EntryQuery,
    RecordingReads,
    restricted_view,
)

#: 22 `runScanner`: results are cached per normalised request for at most 5 s.
TTL_S: Final = 5.0
#: Cache-cold evaluations at once; the next is refused with 429.
MAX_COLD: Final = 4
MAX_ENTRIES: Final = 128
#: The ticker read again (`refresh()`), past which the snapshot in hand is used.
REFRESH_TIMEOUT_S: Final = 2.5
#: The recorded-set read and the evaluation, together.
EVAL_TIMEOUT_S: Final = 2.0
#: One page of the recorded-set read, and the most pages read (the recorded set is capped far
#: below this).
COVERAGE_PAGE: Final = 500
COVERAGE_MAX_PAGES: Final = 20
#: A recorded symbol's entry states while it is recording (`RecordingState`).
_RECORDING: Final = frozenset({"recording", "degraded"})
OUTCOMES: Final = ("ok", "rate_limited", "unavailable", "timeout", "error")

_Key = tuple[bool, ScanQuery]


class ScannerBusyError(Exception):
    """Too many cache-cold evaluations are running: 429 `rate_limited`, never queued."""


class ScannerUnavailableError(Exception):
    """An input cannot be read: 503 `store_unavailable`."""


class _Metric(Protocol):
    """A facade metric (`BoundedMetric`)."""

    def labels(self, *values: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class ScannerMetrics:
    """`scanner_evaluations_total{outcome}`, `scanner_evaluation_seconds`,
    `scanner_cache_hits_total` and `scanner_capped_total`."""

    evaluations: _Metric
    seconds: _Metric
    hits: _Metric
    capped: _Metric


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.scanner")


def _wall_us() -> int:
    return time.time_ns() // 1000


class ScannerService:
    """The scan (module docstring). `universe`, `recording` and `listed` are resolved on each
    cache-cold scan; `listed` answers `None` while the catalogue has no snapshot."""

    def __init__(
        self,
        universe: Callable[[], UniverseTickerSource | None],
        recording: Callable[[], RecordingReads | None],
        metrics: ScannerMetrics | None = None,
        *,
        listed: Callable[[], Set[str] | None] = lambda: None,
        clock_us: Callable[[], int] = _wall_us,
        monotonic: Callable[[], float] = time.monotonic,
        ttl_s: float = TTL_S,
        max_cold: int = MAX_COLD,
        max_entries: int = MAX_ENTRIES,
        refresh_timeout_s: float = REFRESH_TIMEOUT_S,
        timeout_s: float = EVAL_TIMEOUT_S,
    ) -> None:
        self._universe, self._recording, self._listed = universe, recording, listed
        self._clock_us, self._monotonic = clock_us, monotonic
        self._ttl_s, self._max_cold, self._max_entries = ttl_s, max_cold, max_entries
        self._refresh_timeout_s, self._timeout_s = refresh_timeout_s, timeout_s
        self._cache: dict[_Key, tuple[float, bytes]] = {}
        self._inflight: dict[_Key, asyncio.Task[bytes]] = {}
        self._tasks: set[asyncio.Task[bytes]] = set()
        #: The recorded set by view (`restricted`), with the monotonic time it expires.
        self._coverage: dict[bool, tuple[float, frozenset[str]]] = {}
        self._outcomes = (
            {o: metrics.evaluations.labels(o) for o in OUTCOMES} if metrics is not None else {}
        )
        self._seconds = None if metrics is None else metrics.seconds.labels()
        self._hits = None if metrics is None else metrics.hits.labels()
        self._capped = None if metrics is None else metrics.capped.labels()

    @property
    def cold_running(self) -> int:
        """The evaluations running now: owned tasks not yet done."""
        return sum(1 for task in self._tasks if not task.done())

    def start(self) -> None:
        """Nothing runs until a request asks (the lifespan's start/stop pair)."""

    async def stop(self) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Cancel every evaluation still running and wait for them to end."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.invalidate()

    def invalidate(self) -> None:
        """Drop every cached body and remembered recorded set; the next scan reads afresh."""
        self._cache.clear()
        self._coverage.clear()

    def _count(self, outcome: str) -> None:
        child = self._outcomes.get(outcome)
        if child is not None:
            child.inc()

    async def scan(self, q: ScanQuery, *, restricted: bool) -> bytes:
        """The serialised 200 body of `q` for the caller's view."""
        key: _Key = (restricted, q)
        cached = self._cache.get(key)
        if cached is not None and self._monotonic() < cached[0]:
            if self._hits is not None:
                self._hits.inc()
            return cached[1]
        task = self._inflight.get(key)
        if task is None or task.done():
            if self.cold_running >= self._max_cold:  # no await since the check: atomic
                self._count("rate_limited")
                raise ScannerBusyError
            task = spawn(self._evaluate(q, restricted=restricted), name="scanner-eval")
            self._inflight[key] = task
            self._tasks.add(task)
            task.add_done_callback(lambda t: self._settled(key, t))
        return await asyncio.shield(task)  # bounded inside `_evaluate`

    def _settled(self, key: _Key, task: asyncio.Task[bytes]) -> None:
        self._tasks.discard(task)
        if self._inflight.get(key) is task:
            del self._inflight[key]
        if not task.cancelled():
            task.exception()  # retrieved: its requests, if any are left, have their answer

    async def _evaluate(self, q: ScanQuery, *, restricted: bool) -> bytes:
        started = time.perf_counter()
        try:
            body, capped, expires = await self._evaluated(q, restricted=restricted)
        except ScannerUnavailableError:
            self._count("unavailable")
            raise
        except TimeoutError:
            self._count("timeout")
            _log().warning("scanner_scan", outcome="timeout")
            raise ScannerUnavailableError("the scan outlasted its bound") from None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if is_storage_outage(exc):  # another input's store (the catalogue): still a 503
                self._count("unavailable")
                # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
                _log().error("scanner_scan", outcome="unavailable", error=type(exc).__name__)
                raise ScannerUnavailableError("an input's store is unavailable") from None
            self._count("error")
            _log().error("scanner_scan", outcome="error", error=type(exc).__name__)
            raise
        elapsed = time.perf_counter() - started
        self._count("ok")
        if self._seconds is not None:
            self._seconds.observe(elapsed)
        if capped and self._capped is not None:
            self._capped.inc()
        _log().info("scanner_scan", outcome="ok", capped=capped, duration_s=round(elapsed, 4))
        self._install((restricted, q), body, expires)
        return body

    async def _evaluated(self, q: ScanQuery, *, restricted: bool) -> tuple[bytes, bool, float]:
        """The body, whether it is capped, and when the recorded set it used expires."""
        source = self._universe()
        if source is None:
            raise ScannerUnavailableError("no ticker source")
        try:
            async with asyncio.timeout(self._refresh_timeout_s):
                await source.refresh()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the snapshot in hand still answers within its bound
            _log().warning("scanner_ticker_refresh_failed", error=type(exc).__name__)
        snapshot = source.latest()
        if snapshot is None:
            raise ScannerUnavailableError("no ticker snapshot within its bound")
        async with asyncio.timeout(self._timeout_s):
            expires, recorded = await self._recorded(restricted=restricted)
            listed = self._listed()
            now_us = self._clock_us()
            inputs = [tickers_input(snapshot.exchange_ts_us, snapshot.received_at_us, now_us)]

            def work() -> tuple[bytes, bool]:
                result = evaluate(
                    snapshot.tickers, recorded, {}, q, criteria=CRITERIA, listed=listed
                )
                if result.dropped:
                    _log().info("scanner_catalogue_dropped", dropped=result.dropped)
                return build_body(result, generated_at_us=now_us, inputs=inputs), result.capped

            body, capped = await run_in_thread(work)
            return body, capped, expires

    async def _recorded(self, *, restricted: bool) -> tuple[float, frozenset[str]]:
        """The symbols recording now, as the caller's view shows the recorded set, and when that
        answer expires: remembered per view for `ttl_s`, so its cost does not follow the filter."""
        remembered = self._coverage.get(restricted)
        if remembered is not None and self._monotonic() < remembered[0]:
            return remembered
        reads = self._recording()
        if reads is None:
            raise ScannerUnavailableError("no recorded-set store")
        hidden = HIDDEN_CAUSES if restricted else frozenset()
        found: set[str] = set()
        after: tuple[str, str] | None = None
        try:
            for _ in range(COVERAGE_MAX_PAGES):
                page = await reads.list(EntryQuery(hidden=hidden, after=after, limit=COVERAGE_PAGE))
                for entry in page.items:
                    shown = restricted_view(entry) if restricted else entry
                    if shown is not None and shown.state in _RECORDING:
                        found.add(shown.symbol)
                if not page.has_more or not page.items:
                    break
                after = (page.items[-1].symbol, page.items[-1].id)
        except Exception as exc:
            if not is_storage_outage(exc):
                raise
            # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
            _log().error("scanner_recording_unavailable", error=type(exc).__name__)
            raise ScannerUnavailableError("the recorded-set store is unavailable") from None
        answer = (self._monotonic() + self._ttl_s, frozenset(found))
        self._coverage[restricted] = answer
        return answer

    def _install(self, key: _Key, body: bytes, expires: float) -> None:
        now = self._monotonic()
        for k in [k for k, (expires, _) in self._cache.items() if expires <= now]:
            del self._cache[k]
        self._cache.pop(key, None)
        while len(self._cache) >= self._max_entries:
            del self._cache[next(iter(self._cache))]
        self._cache[key] = (min(now + self._ttl_s, expires), body)


__all__ = [
    "MAX_COLD", "OUTCOMES", "TTL_S", "ScannerBusyError", "ScannerMetrics", "ScannerService",
    "ScannerUnavailableError",
]  # fmt: skip
