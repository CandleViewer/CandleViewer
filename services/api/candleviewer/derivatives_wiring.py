"""Composition-root wiring (not a module): the derivatives `/market/metrics` read path (E24-T04).

Only the composition root sees the bar reader, the three derivatives stores, the ticker stream
and the instruments catalogue together (C-3.1). The query is assembled per request from what is
attached at that moment, so it is None (the route's 503) until the bar reader and the
open-interest, funding and liquidation services all exist, and a store attached later is
picked up without a restart.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarReader, stored_bar
from candleviewer.orderflow.derivatives import DerivBar
from candleviewer.orderflow.derivatives_query import BarSource, DerivativesQuery
from candleviewer.storage.errors import StorageTierUnavailable

if TYPE_CHECKING:
    from candleviewer.app import AppContext


def bar_source(reader: BarReader) -> BarSource:
    """Stored time bars as the engine's grid: `[open, open + interval)`, open and close."""

    async def read(
        symbol: str, interval_ms: int, start_us: int, end_us: int, limit: int
    ) -> Sequence[DerivBar]:
        spec = BarSpec(kind="time", interval_ms=interval_ms)
        try:
            page = await reader.read_bars(symbol, spec, start_us, end_us, limit)
        except Exception as exc:  # a raw driver error (see `tape_time_bar_reader`): the 503
            raise StorageTierUnavailable("bars read failed") from exc
        grid: list[DerivBar] = []
        for row in page.rows:
            bar = stored_bar(row)
            start_ms = bar.ts_us // 1000
            grid.append(
                DerivBar(start_ms, start_ms + interval_ms, Decimal(bar.open), Decimal(bar.close))
            )
        return grid

    return read


def derivatives_query_provider(
    ctx: AppContext, bars: BarSource | None
) -> Callable[[], DerivativesQuery | None]:
    def _instrument(symbol: str) -> Any:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        return None if snap is None else snap.get(symbol)

    def _listed(symbol: str) -> bool | None:
        scheduler = ctx.ingestion.instruments
        if scheduler is None or scheduler.snapshot() is None:
            return None
        inst = _instrument(symbol)
        return inst is not None and inst.status == "trading"

    def provide() -> DerivativesQuery | None:
        flow = ctx.orderflow
        oi, funding, liqs = flow.open_interest, flow.funding, flow.liquidations
        if bars is None or oi is None or funding is None or liqs is None:
            return None
        return DerivativesQuery(
            bars=bars,
            oi=oi.store,
            funding=funding.store,
            liquidations=liqs.store,
            instrument=_instrument,
            listed=_listed,
            tickers=lambda: ctx.ingestion.tickers,
        )

    return provide


__all__ = ["bar_source", "derivatives_query_provider"]
