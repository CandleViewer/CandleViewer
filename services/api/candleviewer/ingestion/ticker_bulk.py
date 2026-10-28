"""The shared venue-wide ticker snapshot behind `GET /market/tickers` (E08-T08, #4707; 22).

One venue-wide read (`TickersFetcher`, the adapter's read of every linear ticker) serves every
consumer, the route and the scanner alike (`UniverseTickerSource`, #4708), so however many ask, the
venue sees at most one call per `REFRESH_S`:

- A read starts at most once per `REFRESH_S` (5 s), a failed one included; the last good answer,
  normalised into `TickerEvent`s, is the snapshot. Its age counts from its receipt on this
  server's clock (monotonic), never from the venue's time, which stamps the items
  (`UniverseSnapshot.exchange_ts_us`); `received_at_us` is that receipt on the wall clock.
- A request is answered from the snapshot while it is at most `FRESH_S` (5 s) old. Otherwise it
  waits, at most `wait_s` (`WAIT_S`), for the one read in flight, shared under `asyncio.shield` (a
  request that is cancelled leaves it to the others): single flight, no request reads on its own.
- When that read fails or outlasts the wait, or none may start yet, the snapshot still answers
  while it is at most `SERVE_MAX_S` (15 s) old, its items `stale`; past that, or with none, there
  is no answer (`None`; the route's `TickersUnavailable`, a 503 whose `retry_after_s` is the whole
  seconds until the next read may start, 1 to 5). No value older than `SERVE_MAX_S` is served.

Bounds (C-2.18): one read in flight, cut at `READ_TIMEOUT_S` (`asyncio.timeout`); at most
`MAX_WAITERS` requests wait on it, and a request past that does not queue: it is answered from the
snapshot within its bound, or not at all. It holds no WS upstream lease and no demand. `aclose()`
cancels the read in flight, and no read starts after it. Metrics (facade):
`ticker_bulk_cache_refresh_total{outcome}` once per read, and `ticker_bulk_cache_age_seconds`, the
snapshot's age read at scrape time (+Inf before the first). Logs name the outcome and the error
class, never a value. For the event loop that runs the routes; the rows are normalised off it.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

import structlog

from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.base.universe import TickerPage, TickersFetcher, UniverseSnapshot
from candleviewer.ingestion.ticker_stream import ticker_event
from candleviewer.observability.context import spawn

REFRESH_S: Final = 5.0
FRESH_S: Final = 5.0
SERVE_MAX_S: Final = 15.0
#: How long a request waits for the read in flight before it falls back on the snapshot.
WAIT_S: Final = 2.0
#: One venue read, cut short past this; under `REFRESH_S`, so reads never overlap.
READ_TIMEOUT_S: Final = 4.0
#: Requests that may wait on one read at once; the next one is answered without waiting.
MAX_WAITERS: Final = 256
OUTCOMES: Final = ("ok", "error", "timeout")


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _wall_us() -> int:
    return time.time_ns() // 1000


class _Child(Protocol):
    def inc(self, amount: float = 1) -> None: ...


class _Counter(Protocol):
    """A facade metric's `labels`: `ticker_bulk_cache_refresh_total`."""

    def labels(self, *values: str) -> _Child: ...


@runtime_checkable
class AgeGauge(Protocol):
    """A gauge child a scrape reads through a function: `ticker_bulk_cache_age_seconds`."""

    def set_function(self, f: Callable[[], float]) -> None: ...


@dataclass(frozen=True, slots=True)
class BulkTickers:
    """The route's answer: the snapshot, and whether it is over `FRESH_S` old (items `stale`)."""

    universe: UniverseSnapshot
    stale: bool


class TickersUnavailable(Exception):
    """No snapshot within `SERVE_MAX_S`: the route's `503 exchange_unavailable`."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__("no ticker snapshot within its serve bound")
        self.retry_after_s = retry_after_s


def normalise(page: TickerPage, received_at_us: int) -> tuple[UniverseSnapshot, int]:
    """`page` as `TickerEvent`s received at `received_at_us`, and the rows the model refused."""
    tickers: dict[str, TickerEvent] = {}
    refused = 0
    for symbol, row in page.tickers.items():
        try:
            tickers[symbol] = ticker_event(
                symbol, row.fields, ts_event_us=row.ts_event_us, ts_ingest_us=received_at_us
            )
        except ValueError:
            refused += 1
    snapshot = UniverseSnapshot(MappingProxyType(tickers), received_at_us, page.ts_event_us)
    return snapshot, refused


async def off_loop(page: TickerPage, received_at_us: int) -> tuple[UniverseSnapshot, int]:
    """`normalise` on a worker thread, off the event loop: one answer holds every contract."""
    return await asyncio.to_thread(normalise, page, received_at_us)


def _settled(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()  # retrieved: its waiters, if any are left, have their answer


class TickerBulkCache:
    """The snapshot and its single-flight read: a `UniverseTickerSource` (module docstring)."""

    def __init__(
        self,
        fetch: TickersFetcher,
        *,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _wall_us,
        refreshes: _Counter | None = None,
        age: AgeGauge | None = None,
        normalised: Callable[[TickerPage, int], Awaitable[tuple[UniverseSnapshot, int]]] = off_loop,
        wait_s: float = WAIT_S,
        read_timeout_s: float = READ_TIMEOUT_S,
        max_waiters: int = MAX_WAITERS,
    ) -> None:
        self._fetch, self._clock, self._now_us, self._normalised = fetch, clock, now_us, normalised
        self._wait_s, self._read_timeout_s, self._max_waiters = wait_s, read_timeout_s, max_waiters
        self._snapshot: tuple[UniverseSnapshot, float] | None = None  # and its receipt (clock)
        self._last_start = -math.inf
        self._task: asyncio.Task[None] | None = None
        self._waiters = 0
        self._closed = False
        self._outcomes = {o: refreshes.labels(o) for o in OUTCOMES} if refreshes else {}
        if age is not None:  # read at scrape time
            age.set_function(self.age_s)

    @property
    def waiters(self) -> int:
        return self._waiters

    def age_s(self) -> float:
        """Seconds since the snapshot's receipt; +Inf while there is none."""
        snapshot = self._snapshot
        return math.inf if snapshot is None else max(0.0, self._clock() - snapshot[1])

    def latest(self) -> UniverseSnapshot | None:
        """The snapshot while it is at most `SERVE_MAX_S` old: no I/O, no demand, no read."""
        snapshot = self._snapshot
        return None if snapshot is None or self.age_s() > SERVE_MAX_S else snapshot[0]

    async def refresh(self) -> UniverseSnapshot | None:
        """The snapshot, read again first when it is over `FRESH_S` old (single flight)."""
        if self.age_s() > FRESH_S:
            await self._refreshed()
        return self.latest()

    async def serve(self) -> BulkTickers:
        """The route's answer; `TickersUnavailable` when no snapshot is within `SERVE_MAX_S`, its
        retry 1 when no read ever started (closed before the first)."""
        universe = await self.refresh()
        if universe is None:
            wait = self._last_start + REFRESH_S - self._clock()  # -inf before the first read
            retry = math.ceil(wait) if math.isfinite(wait) else 1
            raise TickersUnavailable(min(int(REFRESH_S), max(1, retry)))
        return BulkTickers(universe, self.age_s() > FRESH_S)

    async def _refreshed(self) -> None:
        """Join the read in flight, or start one when it may start; at most `wait_s`."""
        task = self._task
        idle = task is None or task.done()
        if idle and not self._closed and self._clock() - self._last_start >= REFRESH_S:
            task = self._start()
        if task is None or task.done() or self._waiters >= self._max_waiters:
            return  # none may start yet, or the waiters are full: the snapshot answers
        self._waiters += 1
        try:
            # A read that fails is counted and logged by `_read`; one that outlasts the wait goes
            # on for the requests after this one.
            with contextlib.suppress(Exception):
                async with asyncio.timeout(self._wait_s):
                    await asyncio.shield(task)
        finally:
            self._waiters -= 1

    def _start(self) -> asyncio.Task[None]:
        self._last_start = self._clock()
        task = self._task = spawn(self._read(), name="ticker-bulk-read")
        task.add_done_callback(_settled)
        return task

    async def _read(self) -> None:
        try:
            async with asyncio.timeout(self._read_timeout_s):
                page = await self._fetch()
                received = self._clock(), self._now_us()  # its receipt, on this server's clocks
                universe, refused = await self._normalised(page, received[1])
        except TimeoutError:
            self._count("timeout")
            _log().warning("ticker_bulk_read_failed", outcome="timeout")
            raise
        except Exception as exc:
            self._count("error")
            _log().warning("ticker_bulk_read_failed", outcome="error", error=type(exc).__name__)
            raise
        self._snapshot = universe, received[0]
        self._count("ok")
        if page.rejected or refused:
            _log().warning("ticker_bulk_rows_rejected", rejected=page.rejected + refused)

    def _count(self, outcome: str) -> None:
        child = self._outcomes.get(outcome)
        if child is not None:
            child.inc()

    async def aclose(self) -> None:
        """Cancel the read in flight; no read starts after this."""
        self._closed = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})


__all__ = [
    "FRESH_S",
    "MAX_WAITERS",
    "OUTCOMES",
    "READ_TIMEOUT_S",
    "REFRESH_S",
    "SERVE_MAX_S",
    "WAIT_S",
    "AgeGauge",
    "BulkTickers",
    "TickerBulkCache",
    "TickersUnavailable",
    "normalise",
    "off_loop",
]
