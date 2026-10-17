"""Composition-root wiring (not a module): `BarBuilderSet` + `BarWriter` lifecycle (E12 #2031).

Only the composition root sees the bus, the storage tier and the bars module together (C-3.1).

* Flag `bars_enabled` (C-4.13, default **off**): no consumer calls `register()` yet; E12-T05 (#398)
  and E12-T06 (#399) land the consumers and remove the flag. Never gates a safety invariant.
* `BarsRuntime` is the one lifecycle owner started/stopped by the lifespan. The set's ticker and
  lane tasks and the writer's drain task are spawned and tracked by those classes (C-2.18); every
  queue is bounded (`BarWriter(max_buffered)`, lane `maxsize`).
* Shutdown order: **set first, then writer** - the set's final closes/blobs are submitted to the
  writer, which is then drained.
* Emit path (E12-T06, #399): the WS series store, then the WS publisher, then the writer. The store
  comes first so a generation swap's re-snapshot reads the new generation; neither awaits, so both
  run before the writer, whose full queue would otherwise hold every WS delta back.
* `GuardedRowSink` fails closed with `StorageTierUnavailable` when no QuestDB ILP sink is
  composed (fake storage backend). With `storage_backend="real"` the composition root passes a
  `QuestDbRowSink` (#2037) as `inner_sink`. Shutdown: set -> writer -> sink (ILP drain,
  transport, PG-wire).
* `StorageTape` reads the trades table through `MarketDataRepository.read_trades` (no SQL here).
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.bars.builder_set import BarBuilderSet, production_factory
from candleviewer.bars.emit import BarSink, EmitRouter, WriterSink
from candleviewer.bars.kline_rows import PrecedenceHealth
from candleviewer.bars.state_store import StateStore
from candleviewer.bars.writer import BarWriter, RowSink, default_is_permanent
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.storage.errors import IlpRowError, StorageTierUnavailable
from candleviewer.storage.models import TimeRange

if TYPE_CHECKING:
    from candleviewer.app import AppContext


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: `head_us` looks this far back; an older tape reports None (the ahead-of-tape check is skipped).
HEAD_WINDOW_US: Final = 5 * 60 * 1_000_000
#: `since` reads the tape in windows of this size so memory stays bounded after a long outage.
READ_WINDOW_US: Final = 5 * 60 * 1_000_000
#: A window returning more rows than this is re-read narrower (down to MIN_WINDOW_US), so a
#: busy symbol cannot pull an unbounded window into memory at once.
MAX_WINDOW_ROWS: Final = 20_000
MIN_WINDOW_US: Final = 1_000_000
_FAR_FUTURE_US: Final = 2**62


def _permanent(exc: Exception) -> bool:
    return default_is_permanent(exc) or isinstance(exc, IlpRowError)


class GuardedRowSink:
    """`RowSink` that fails closed when no hot-tier ILP sink is injected (fake storage backend):
    every batch fails after the retry limit and is DROPPED (bounded loss, surfaced by the
    `bars_writer` health probe, `bars_write_*` logs and metrics)."""

    def __init__(self, ctx: AppContext, inner: RowSink | None) -> None:
        self._ctx = ctx
        self._inner = inner

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        if self._inner is None:
            _ = self._ctx.storage.market_data  # raises StorageTierUnavailable until started
            raise StorageTierUnavailable("no hot-tier ILP writer is wired for bars")
        await self._inner.write_rows(table, rows, ts_us_key)


class StorageTape:
    """`TapeSource` over the trades table (`MarketDataRepository.read_trades`), oldest first."""

    def __init__(
        self,
        ctx: AppContext,
        now_us: Callable[[], int],
        tick_size: Callable[[str], Decimal | None] = lambda _s: None,
    ) -> None:
        self._ctx = ctx
        self._now = now_us
        self._tick_size = tick_size

    async def head_us(self, symbol: str) -> int | None:
        now = self._now()
        rows = await self._ctx.storage.market_data.read_trades(
            symbol, TimeRange(start_us=now - HEAD_WINDOW_US, end_us=now + 1)
        )
        return max((r.ts_us for r in rows), default=None)

    async def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]:
        end = self._now() + 1
        start = ts_us
        tick = self._tick_size(symbol)
        width = READ_WINDOW_US
        while start < end:
            stop = min(start + width, end)
            rows = await self._ctx.storage.market_data.read_trades(
                symbol, TimeRange(start_us=start, end_us=stop)
            )
            if len(rows) > MAX_WINDOW_ROWS and width > MIN_WINDOW_US:
                width = max(MIN_WINDOW_US, width // 2)
                continue  # too dense: drop this read, retry the same start narrower
            for r in rows:
                price = Decimal(r.price)
                qty = Decimal(r.qty)
                yield TradeEvent.model_validate(
                    {
                        "event_id": uuid7(r.ts_us // 1000),
                        "ts_event": r.ts_us,
                        "ts_ingest": r.ts_us,
                        "source": "replay",
                        "symbol": r.symbol,
                        "trade_id": r.trade_id,
                        "price": price,
                        "qty": qty,
                        "side": r.side,
                        "is_block_trade": False,
                        "price_ticks": int((price / tick).to_integral_value()) if tick else 0,
                        "notional": price * qty,
                        "seq": 0,  # the table keeps no sequence; order is (ts, trade_id)
                    }
                )
            start = stop


class BarsRuntime:
    """Lifecycle of the set and its writer; started/stopped by the ASGI lifespan."""

    def __init__(
        self,
        builder_set: BarBuilderSet,
        writer: BarWriter,
        state_root: Path,
        sink_stop: Callable[[], Awaitable[None]] | None = None,
        sink_degraded: Callable[[], bool] | None = None,
        precedence: PrecedenceHealth | None = None,
    ) -> None:
        self.precedence = precedence if precedence is not None else PrecedenceHealth()
        self.builder_set = builder_set
        self.writer = writer
        self._sink_stop = sink_stop
        self._sink_degraded = sink_degraded
        self._root = state_root

    async def start(self) -> None:
        # `mode` applies to the leaf only; intermediate parents get the umask default. Fine:
        # the leaf is chmod'd 0700 below and holds everything sensitive (the blobs).
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if sys.platform != "win32":  # blobs hold trade-derived state: owner-only
            os.chmod(self._root, 0o700)
        await self.writer.start()
        await self.builder_set.start()

    def writer_state(self) -> tuple[bool, str]:
        degraded = (
            self.writer.degraded
            or not self.writer.healthy
            or (self._sink_degraded is not None and self._sink_degraded())
        )
        if degraded:
            return True, "bars_writer_degraded"
        if self.precedence.degraded:  # #2053: kline rows refused, tape state unknown
            return True, self.precedence.reason()
        return False, ""

    async def stop(self) -> None:
        """Set before writer, so the set's final closes reach the writer's drain."""
        await self.builder_set.stop()
        remaining = await self.writer.stop()
        if remaining:
            logger().error("bars_writer_rows_unwritten_at_shutdown", remaining=remaining)
        if self._sink_stop is not None:
            try:
                await self._sink_stop()
            except Exception:
                logger().exception("bars_sink_stop_failed")


def wire_bars(
    ctx: AppContext,
    *,
    now_us: Callable[[], int],
    inner_sink: RowSink | None = None,
    sink_stop: Callable[[], Awaitable[None]] | None = None,
    sink_degraded: Callable[[], bool] | None = None,
    tick_size: Callable[[str], Decimal | None] = lambda _s: None,
    series: BarSink | None = None,
    publisher: BarSink | None = None,
) -> BarsRuntime:
    """Build the set + writer, attach the set to `ctx.bars`, return the lifecycle owner. `series`
    and `publisher`: the WS series store and bars publisher, emitted to in that order (module
    docstring)."""
    if inner_sink is None:
        logger().warning(
            "bars_rows_not_persisted",
            reason="no hot-tier row sink composed (non-QuestDB storage backend); bar rows dropped",
        )
    writer = BarWriter(GuardedRowSink(ctx, inner_sink), is_permanent=_permanent)
    root = Path(ctx.settings.bars_state_root)
    builder_set = BarBuilderSet(
        ctx.bus.bus,
        ctx.settings.environment.value,
        EmitRouter([*(s for s in (series, publisher) if s is not None), WriterSink(writer)]),
        StateStore(root),
        tape=StorageTape(ctx, now_us, tick_size),
        now_us=now_us,
        factory=production_factory(tick_size, renko_enabled=ctx.settings.bars_renko_enabled),
    )
    ctx.bars.attach(builder_set)
    return BarsRuntime(builder_set, writer, root, sink_stop, sink_degraded)
