"""`MarketDataRepository` Protocol — hot/cold market-data read/write surface.

`Protocol`, not an ABC (ticket "Technical notes / design"): implementations
(E07-T02 Postgres relational bits, E07-T03 QuestDB, E07-T04 cold tier, and
this ticket's own in-memory fake) need no inheritance, so a fake stays a
plain class that happens to structurally match.

Write methods are batch-only (`Sequence[...]`) on purpose — a per-row API
would make the ILP batching budget of `docs/plan/20-architecture.md` Sec.4.14
unreachable (ticket "Technical notes / design"). Every read method takes a
`TierHint`; `"auto"` resolution lives in E07-T05's router, never here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from candleviewer.storage.models import TierHint, TimeRange
from candleviewer.storage.repositories.rows import (
    BarRow,
    BookDeltaRow,
    BookSnapshotRow,
    FootprintCellRow,
    KlineRow,
    OrderflowMetricRow,
    TickerRow,
    TradeRow,
    TradeTotals,
)


@runtime_checkable
class MarketDataRepository(Protocol):
    """Batch writes, tier-aware reads, for every raw and derived market stream.

    Ordering guarantee: every `read_*` method returns rows ordered by
    ascending `ts_us` (ties broken by natural key — `trade_id`/`seq`/price
    level — where the row type has one); callers must not re-sort. Writes do
    not guarantee ordering is preserved (implementations may reorder for
    batching), but a `read_*` immediately following a `write_*` of the same
    range always reflects the write once the coroutine returns.
    """

    async def write_trades(self, rows: Sequence[TradeRow]) -> None:
        """Append trade prints. Dedup key: `(symbol, trade_id)`."""
        ...

    async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None:
        """Append book deltas. Dedup key: `(symbol, seq)`."""
        ...

    async def write_book_snapshot(self, row: BookSnapshotRow) -> None:
        """Persist a full book snapshot. Dedup key: `(symbol, seq)`."""
        ...

    async def write_tickers(self, rows: Sequence[TickerRow]) -> None:
        """Append ticker updates. Dedup key: `(symbol, ts_us)`."""
        ...

    async def write_bars(self, rows: Sequence[BarRow]) -> None:
        """Append/upsert bars. Dedup key: `(symbol, family, param, ts_us)`."""
        ...

    async def write_klines(self, rows: Sequence[KlineRow]) -> None:
        """Append/upsert exchange klines (E08-S06). Dedup key:
        `(symbol, interval, ts_us)` — a later write of the same key
        overwrites the earlier one, which is how a `confirmed=False`
        in-progress row is superseded by the final `confirmed=True` row
        (`docs/plan/21-database-schema.md` §4.5)."""
        ...

    async def read_bars(
        self,
        sym: str,
        family: str,
        param: str,
        rng: TimeRange,
        tier: TierHint = "auto",
    ) -> list[BarRow]:
        """Read bars for `(sym, family, param)` within `rng`, ascending `ts_us`."""
        ...

    async def read_klines(
        self,
        sym: str,
        interval: str,
        rng: TimeRange,
        tier: TierHint = "auto",
        limit: int | None = None,
    ) -> list[KlineRow]:
        """Read klines for `(sym, interval)` within `rng`, ascending `ts_us`
        (E08-S06 cache-first read path). `limit` keeps the **newest** `limit` rows and is
        applied in the query, so a wide window never loads every row (E12-S05)."""
        ...

    async def read_trades(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[TradeRow]:
        """Read trades for `sym` within `rng`, ascending `(ts_us, trade_id)`."""
        ...

    async def first_trade_us(self, sym: str) -> int | None:
        """Open time (µs) of the oldest stored trade for `sym` (where recorded tape begins),
        or `None` when no tape exists (E12-S05 `meta.recording_started_at`)."""
        ...

    async def trade_totals(self, sym: str, rng: TimeRange, tier: TierHint = "auto") -> TradeTotals:
        """Print count and summed qty of `sym`'s trades within `rng`: one bounded aggregate, never
        the rows (SR-E12-02 pre-query estimate for non-time `/market/bars`, #2093)."""
        ...

    async def read_book_snapshot_at(
        self, sym: str, ts_us: int, depth: int, tier: TierHint = "auto"
    ) -> BookSnapshotRow | None:
        """Latest snapshot at or before `ts_us`, truncated to `depth` levels
        per side, or `None` if no snapshot exists at/before that time."""
        ...

    async def read_book_deltas(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[BookDeltaRow]:
        """Read deltas for `sym` within `rng`, ascending `(ts_us, seq)`."""
        ...

    async def read_orderflow_metrics(
        self, sym: str, metric: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[OrderflowMetricRow]:
        """Read one metric series for `sym` within `rng`, ascending `ts_us`."""
        ...

    async def read_footprint_cells(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[FootprintCellRow]:
        """Read footprint cells for `sym` within `rng`, ascending
        `(bar_ts_us, price_level)`."""
        ...

    async def latest_ticker(self, sym: str, tier: TierHint = "auto") -> TickerRow | None:
        """Most recent ticker for `sym`, or `None` if none has been written."""
        ...
