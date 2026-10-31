"""Composition-root wiring (not a module): open-interest service, ticker tap and backfill (E24-T01).

Only the composition root sees the store, the adapter fetcher, the bus and the instruments
cache together (C-3.1). Rules:

* The store is reached through `GuardedOiStore`: until the hot tier is started every read or
  write raises `StorageTierUnavailable` (the router's 503, never a 500). On the real backend
  the QuestDB store is built on first use over the hot tier's own ILP writer and PGWire reader.
* `OiRuntime` owns three tracked tasks (C-2.18): the ticker tap (a `CONFLATE_LATEST` bus
  subscription on `md.*.ticker`, so it never back-pressures the ticker stream, whose own
  write-behind is untouched), the backfill worker, and a jittered refresh that re-requests the
  recent window of every `(symbol, interval)` a client has asked for.
* No fetcher is built unless one is injected, so dev/CI defaults never touch the network
  (C-13.5); the read path then serves what the store holds.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.bus.models import WILDCARD, QueuePolicy, TopicPattern
from candleviewer.domain.open_interest import INTERVAL_US, OiPoint
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.observability.context import spawn
from candleviewer.orderflow.deriv_metrics import deriv_oi_rows_written_total
from candleviewer.orderflow.open_interest import (
    OiBackfill,
    OiFetcher,
    OiStore,
    OpenInterestService,
    TickerDownsampler,
    TimeWindow,
)
from candleviewer.storage.errors import StorageTierUnavailable

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.bus.bus import Subscription


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


REFRESH_INTERVAL_S: Final = 300.0
JITTER_FRACTION: Final = 0.1
TAP_QUEUE: Final = 1024


def _random() -> float:
    return secrets.randbelow(10_000) / 10_000


class GuardedOiStore:
    """`OiStore` that fails closed with `StorageTierUnavailable`."""

    def __init__(
        self,
        ctx: AppContext,
        inner: OiStore | None,
        factory: Callable[[object], OiStore | None] | None = None,
    ) -> None:
        self._ctx, self._inner, self._factory = ctx, inner, factory

    def _live(self) -> OiStore:
        repo = self._ctx.storage.market_data  # raises StorageTierUnavailable until started
        if self._inner is None and self._factory is not None:
            self._inner = self._factory(repo)
        if self._inner is None:
            raise StorageTierUnavailable("no hot-tier open-interest client is wired")
        return self._inner

    async def write_points(self, rows: Sequence[OiPoint]) -> None:
        await self._live().write_points(rows)

    async def read_points(
        self, symbol: str, interval: str, source: str, rng: Any, limit: int
    ) -> list[OiPoint]:
        return list(await self._live().read_points(symbol, interval, source, rng, limit))

    async def coverage(self, symbol: str, interval: str, source: str) -> tuple[int, int] | None:
        return await self._live().coverage(symbol, interval, source)


class OiRuntime:
    """The tracked tasks of the open-interest pipeline; started and stopped by the lifespan."""

    def __init__(
        self,
        ctx: AppContext,
        store: OiStore,
        backfill: OiBackfill | None,
        *,
        now_us: Callable[[], int],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = _random,
    ) -> None:
        self._ctx, self._store, self.backfill = ctx, store, backfill
        self._now_us, self._sleep, self._random = now_us, sleep, random_fn
        self.downsampler = TickerDownsampler()
        self._sub: Subscription | None = None
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        if self._tasks:
            return
        pattern = TopicPattern(
            env=self._ctx.settings.environment.value, domain="md", symbol=WILDCARD, detail="ticker"
        )
        bus = self._ctx.bus.bus
        self._sub = bus.subscribe("oi-ticker-tap", pattern, QueuePolicy.CONFLATE_LATEST,
                                  maxsize=TAP_QUEUE)  # fmt: skip
        self._tasks.append(spawn(self._tap(self._sub), name="oi-ticker-tap"))
        if self.backfill is not None:
            self._tasks.append(spawn(self.backfill.run(), name="oi-backfill"))
            self._tasks.append(spawn(self._refresh_loop(), name="oi-refresh"))

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._sub is not None:
            with contextlib.suppress(ValueError):
                self._ctx.bus.bus.unsubscribe(self._sub)
            self._sub = None

    async def on_ticker(self, event: object) -> bool:
        """One bus event; True when a point was written. A failed write is logged, never raised."""
        if not isinstance(event, TickerEvent):
            return False
        point = self.downsampler.offer(
            event.symbol, event.ts_event, event.open_interest, event.open_interest_value
        )
        if point is None:
            return False
        try:
            await self._store.write_points([point])
        except Exception as exc:  # the tap must never take ingest down
            logger().warning("oi_tap_write_failed", error=type(exc).__name__)
            return False
        deriv_oi_rows_written_total.labels("ws_ticker").inc()
        return True

    async def _tap(self, sub: Subscription) -> None:
        while True:
            await self.on_ticker(await sub.get())

    def refresh_once(self) -> int:
        """Re-request the recent window of every key a client asked for; returns jobs queued."""
        if self.backfill is None:
            return 0
        now, queued = self._now_us(), 0
        for symbol, interval in self.backfill.keys():
            window = TimeWindow(now - 2 * INTERVAL_US[interval], now)
            queued += self.backfill.request(symbol, interval, window, refresh=True)
        return queued

    async def _refresh_loop(self) -> None:
        while True:
            await self._sleep(REFRESH_INTERVAL_S * (1 + JITTER_FRACTION * self._random()))
            self.refresh_once()


def wire_open_interest(
    ctx: AppContext,
    *,
    store: OiStore | None,
    fetcher: OiFetcher | None,
    now_us: Callable[[], int],
    store_factory: Callable[[object], OiStore | None] | None = None,
) -> OiRuntime:
    """Attach `OpenInterestService` to orderflow and return the runtime the lifespan starts."""

    def _listed(symbol: str) -> bool | None:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        if snap is None:
            return None
        inst = snap.get(symbol)
        return inst is not None and inst.status == "trading"

    guarded = GuardedOiStore(ctx, store, store_factory)
    backfill = None
    if fetcher is not None:
        backfill = OiBackfill(store=guarded, fetcher=fetcher, random_fn=_random)
    ctx.orderflow.attach_open_interest(
        OpenInterestService(store=guarded, listed=_listed, backfill=backfill)
    )
    return OiRuntime(ctx, guarded, backfill, now_us=now_us)
