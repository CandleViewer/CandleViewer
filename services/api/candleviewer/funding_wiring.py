"""Composition-root wiring (not a module): funding service + supervised refresh (E24-T02-F1).

Only the composition root sees the store, the adapter fetcher, the instruments
cache and the ticker stream together (C-3.1). Rules:

* The store is reached through `GuardedFundingStore`: while the hot tier is not
  started (or has no funding client yet) every read/write raises
  `StorageTierUnavailable`, which the router maps to 503 (never 500).
* `FundingRefreshTask` is the one tracked task (C-2.18): a jittered periodic
  backfill over the catalogue's trading symbols. A rejected page
  (`FundingRowRejected`), an unknown interval or any per-symbol failure is
  counted by the service and skipped; the loop never dies.
* No fetcher is built unless one is injected, so dev/CI defaults never touch the network
  (C-13.5). On `storage_backend == "real"` there is no store yet, so no fetcher/task is
  composed (nothing is fetched that cannot be written) until the QuestDB funding client
  lands: follow-up issue #1939 (parent #1932 / #666).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.domain.funding import SettledFunding
from candleviewer.observability.context import spawn
from candleviewer.orderflow.funding import FundingFetcher, FundingService, FundingStore, TimeWindow
from candleviewer.storage.errors import StorageTierUnavailable

if TYPE_CHECKING:
    from candleviewer.app import AppContext


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


_US: Final = 1_000_000
_DAY_US: Final = 86_400 * _US
#: Periodic runs only re-fetch the recent past (idempotent store; the first run backfills deep).
RECENT_DAYS: Final = 2
#: Retry cadence while the instruments catalogue is not loaded yet.
CATALOGUE_RETRY_S: Final = 30.0
JITTER_FRACTION: Final = 0.1
#: First retry delay after a pass in which every symbol failed; doubles up to the interval.
FAILURE_BACKOFF_S: Final = 30.0


class GuardedFundingStore:
    """`FundingStore` that fails closed with `StorageTierUnavailable`."""

    def __init__(self, ctx: AppContext, inner: FundingStore | None) -> None:
        self._ctx = ctx
        self._inner = inner

    def _live(self) -> FundingStore:
        _ = self._ctx.storage.market_data  # raises StorageTierUnavailable until started
        if self._inner is None:
            raise StorageTierUnavailable("no hot-tier funding client is wired")
        return self._inner

    async def write_settled(self, rows: Sequence[SettledFunding]) -> None:
        await self._live().write_settled(rows)

    async def read_settled(self, symbol: str, rng: Any, limit: int) -> list[SettledFunding]:
        return list(await self._live().read_settled(symbol, rng, limit))

    async def coverage(self, symbol: str) -> tuple[int, int] | None:
        return await self._live().coverage(symbol)


class FundingRefreshTask:
    """Tracked, cancellable owner of the periodic funding backfill."""

    def __init__(
        self,
        service: FundingService,
        symbols: Callable[[], Sequence[str]],
        *,
        interval_s: float,
        backfill_days: int,
        closer: Callable[[], Awaitable[None]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] | None = None,
        now_us: Callable[[], int],
    ) -> None:
        self._service = service
        self._symbols = symbols
        self._interval_s = interval_s
        self._backfill_days = backfill_days
        self._closer = closer
        self._sleep = sleep
        self._random = random_fn if random_fn is not None else _default_random
        self._now_us = now_us
        self._task: asyncio.Task[None] | None = None
        self._first = True
        self._failures = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._run(), name="funding-refresh")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._closer is not None:
            await self._closer()

    async def run_once(self) -> int:
        """One pass over the catalogue; returns symbols refreshed OK."""
        symbols = list(self._symbols())
        days = self._backfill_days if self._first else RECENT_DAYS
        end = self._now_us()
        window = TimeWindow(end - days * _DAY_US, end)
        ok = 0
        for symbol in symbols:
            try:
                await self._service.backfill(symbol, window)
                ok += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # counted by the service; one symbol never stops the loop
                logger().warning("funding_refresh_skipped", symbol=symbol, error=type(exc).__name__)
        if ok > 0:
            self._first = False  # deep backfill is retried until one symbol succeeds
        return ok

    def _next_delay(self, ok: int, had_symbols: bool) -> float:
        if not had_symbols:
            return CATALOGUE_RETRY_S
        if ok > 0:
            self._failures = 0
            return float(self._interval_s * (1 + JITTER_FRACTION * self._random()))
        self._failures += 1
        base = min(FAILURE_BACKOFF_S * 2 ** (self._failures - 1), self._interval_s)
        return float(base * (1 + JITTER_FRACTION * self._random()))

    async def _run(self) -> None:
        while True:
            try:
                had_symbols = bool(self._symbols())
                ok = await self.run_once()
                delay = self._next_delay(ok, had_symbols)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger().exception("funding_refresh_failed")
                delay = self._next_delay(0, True)
            await self._sleep(delay)


def _default_random() -> float:
    import secrets

    return secrets.randbelow(10_000) / 10_000


def wire_funding(
    ctx: AppContext,
    *,
    store: FundingStore | None,
    fetcher: FundingFetcher | None,
    closer: Callable[[], Awaitable[None]] | None = None,
    now_us: Callable[[], int],
) -> FundingRefreshTask | None:
    """Attach `FundingService` to orderflow; return the refresh task (None when
    no fetcher exists - the read path then serves whatever the store holds)."""

    def _instrument(symbol: str) -> object | None:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        return None if snap is None else snap.get(symbol)

    def _symbols() -> list[str]:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        return [] if snap is None else sorted(i.symbol for i in snap.listing())

    service = FundingService(
        store=GuardedFundingStore(ctx, store),
        fetcher=fetcher,
        instruments=_instrument,  # type: ignore[arg-type]  # Instrument has funding_interval_min
        tickers=lambda: ctx.ingestion.tickers,
    )
    ctx.orderflow.attach_funding(service)
    if fetcher is None or not ctx.settings.funding_enabled:
        return None
    return FundingRefreshTask(
        service,
        _symbols,
        interval_s=float(ctx.settings.funding_refresh_interval_s),
        backfill_days=ctx.settings.funding_backfill_days,
        closer=closer,
        now_us=now_us,
    )
