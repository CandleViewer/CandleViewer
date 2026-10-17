"""In-memory implementations of every M10 repository Protocol.

Round-trip semantics: `write_*` then `read_*` for the same range returns
exactly what was written, ordered by `ts_us` ascending (deduplicated by each
row type's natural key, ties resolved by last-write-wins) — this is what
lets the same contract-test suite run against `[fake]` today and
`[questdb, timescale]` later unchanged (ticket acceptance criterion 3).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import ExportRun, RetentionDecision, StreamKind, TimeRange
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


def _in_range(ts_us: int, rng: TimeRange) -> bool:
    return rng.start_us <= ts_us < rng.end_us


class FakeMarketDataRepository:
    """In-memory `MarketDataRepository`. Not thread-safe; one event loop only."""

    def __init__(self) -> None:
        self._trades: dict[tuple[str, str], TradeRow] = {}
        self._deltas: dict[tuple[str, int], BookDeltaRow] = {}
        self._snapshots: dict[tuple[str, int], BookSnapshotRow] = {}
        self._tickers: dict[tuple[str, int], TickerRow] = {}
        self._bars: dict[tuple[str, str, str, int], BarRow] = {}
        self._klines: dict[tuple[str, str, int], KlineRow] = {}
        self._orderflow: dict[tuple[str, str, int], OrderflowMetricRow] = {}
        self._footprint: dict[tuple[str, int, str], FootprintCellRow] = {}

    async def write_trades(self, rows: object) -> None:
        for row in rows:  # type: ignore[attr-defined]
            self._trades[(row.symbol, row.trade_id)] = row

    async def write_book_deltas(self, rows: object) -> None:
        for row in rows:  # type: ignore[attr-defined]
            self._deltas[(row.symbol, row.seq)] = row

    async def write_book_snapshot(self, row: BookSnapshotRow) -> None:
        self._snapshots[(row.symbol, row.seq)] = row

    async def write_tickers(self, rows: object) -> None:
        for row in rows:  # type: ignore[attr-defined]
            self._tickers[(row.symbol, row.ts_us)] = row

    async def write_bars(self, rows: object) -> None:
        for row in rows:  # type: ignore[attr-defined]
            self._bars[(row.symbol, row.family, row.param, row.ts_us)] = row

    async def write_klines(self, rows: object) -> None:
        for row in rows:  # type: ignore[attr-defined]
            self._klines[(row.symbol, row.interval, row.ts_us)] = row

    async def read_bars(
        self, sym: str, family: str, param: str, rng: TimeRange, tier: str = "auto"
    ) -> list[BarRow]:
        rows = [
            r
            for (s, f, p, _ts), r in self._bars.items()
            if s == sym and f == family and p == param and _in_range(r.ts_us, rng)
        ]
        return sorted(rows, key=lambda r: r.ts_us)

    async def read_klines(
        self,
        sym: str,
        interval: str,
        rng: TimeRange,
        tier: str = "auto",
        limit: int | None = None,
    ) -> list[KlineRow]:
        rows = [
            r
            for (s, i, _ts), r in self._klines.items()
            if s == sym and i == interval and _in_range(r.ts_us, rng)
        ]
        rows.sort(key=lambda r: r.ts_us)
        return rows if limit is None else rows[-limit:] if limit else []

    async def first_trade_us(self, sym: str) -> int | None:
        return min((r.ts_us for r in self._trades.values() if r.symbol == sym), default=None)

    async def read_trades(self, sym: str, rng: TimeRange, tier: str = "auto") -> list[TradeRow]:
        rows = [r for r in self._trades.values() if r.symbol == sym and _in_range(r.ts_us, rng)]
        return sorted(rows, key=lambda r: (r.ts_us, r.trade_id))

    async def trade_totals(self, sym: str, rng: TimeRange, tier: str = "auto") -> TradeTotals:
        rows = [r for r in self._trades.values() if r.symbol == sym and _in_range(r.ts_us, rng)]
        return TradeTotals(len(rows), sum((Decimal(r.qty) for r in rows), Decimal(0)))

    async def read_book_snapshot_at(
        self, sym: str, ts_us: int, depth: int, tier: str = "auto"
    ) -> BookSnapshotRow | None:
        candidates = [r for r in self._snapshots.values() if r.symbol == sym and r.ts_us <= ts_us]
        if not candidates:
            return None
        latest = max(candidates, key=lambda r: r.ts_us)
        return BookSnapshotRow(
            ts_us=latest.ts_us,
            symbol=latest.symbol,
            seq=latest.seq,
            bids=latest.bids[:depth],
            asks=latest.asks[:depth],
        )

    async def read_book_deltas(
        self, sym: str, rng: TimeRange, tier: str = "auto"
    ) -> list[BookDeltaRow]:
        rows = [r for r in self._deltas.values() if r.symbol == sym and _in_range(r.ts_us, rng)]
        return sorted(rows, key=lambda r: (r.ts_us, r.seq))

    async def read_orderflow_metrics(
        self, sym: str, metric: str, rng: TimeRange, tier: str = "auto"
    ) -> list[OrderflowMetricRow]:
        rows = [
            r
            for r in self._orderflow.values()
            if r.symbol == sym and r.metric == metric and _in_range(r.ts_us, rng)
        ]
        return sorted(rows, key=lambda r: r.ts_us)

    async def read_footprint_cells(
        self, sym: str, rng: TimeRange, tier: str = "auto"
    ) -> list[FootprintCellRow]:
        rows = [
            r for r in self._footprint.values() if r.symbol == sym and _in_range(r.bar_ts_us, rng)
        ]
        return sorted(rows, key=lambda r: (r.bar_ts_us, r.price_level))

    async def latest_ticker(self, sym: str, tier: str = "auto") -> TickerRow | None:
        candidates = [r for r in self._tickers.values() if r.symbol == sym]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.ts_us)


class FakeUnitOfWork:
    """In-memory `UnitOfWork`. `commit()`/`rollback()` just flip a flag —
    there is no real transaction to demarcate without a Postgres connection,
    but the state machine (open -> committed|rolled_back, double-commit
    raises) matches what a real implementation must uphold."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None and not self.committed:
            self.rolled_back = True

    async def commit(self) -> None:
        if self.committed:
            raise RuntimeError("FakeUnitOfWork.commit() called twice")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeRelationalRepository:
    """In-memory `RelationalRepository` factory."""

    def unit_of_work(self) -> FakeUnitOfWork:
        return FakeUnitOfWork()


class FakeColdTierRepository:
    """In-memory `ColdTierRepository`. `verify_checksums` always succeeds for
    a run this fake produced; call `poison(run_id)` in a test to simulate a
    corrupted export and exercise the `StorageExportVerifyFailed` path."""

    def __init__(self) -> None:
        self._runs: dict[str, ExportRun] = {}
        self._poisoned: set[str] = set()
        self._rows: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def seed(self, symbol: str, stream: StreamKind, rows: list[dict[str, Any]]) -> None:
        """Test helper: preload rows `query()` should return."""
        self._rows[(symbol, stream.value)] = rows

    def poison(self, run_id: str) -> None:
        """Test helper: make a subsequent `verify_checksums(run)` fail."""
        self._poisoned.add(run_id)

    async def export_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> ExportRun:
        run = ExportRun(
            run_id=f"{symbol}:{stream.value}:{rng.start_us}:{rng.end_us}",
            symbol=symbol,
            stream=stream,
            partition_range=rng,
            row_count=len(self._rows.get((symbol, stream.value), [])),
            verified=False,
        )
        self._runs[run.run_id] = run
        return run

    async def list_manifest(self, symbol: str, stream: StreamKind) -> list[ExportRun]:
        runs = [r for r in self._runs.values() if r.symbol == symbol and r.stream == stream]
        return sorted(runs, key=lambda r: r.partition_range.start_us)

    async def query(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[dict[str, Any]]:
        rows = self._rows.get((symbol, stream.value), [])
        return [r for r in rows if _in_range(int(r["ts_us"]), rng)]

    async def verify_checksums(self, run: ExportRun) -> bool:
        if run.run_id in self._poisoned:
            raise StorageExportVerifyFailed(f"checksum mismatch for {run.run_id}")
        verified = ExportRun(**{**run.model_dump(), "verified": True})
        self._runs[run.run_id] = verified
        return True


class FakeRetentionRepository:
    """In-memory `RetentionRepository`. `apply()` just records decisions it
    was given so a test can assert the router/caller invoked it correctly —
    E07-T01 defines no retention logic (ticket "Out of scope")."""

    def __init__(self) -> None:
        self._pinned: set[tuple[str, str]] = set()
        self.applied: list[RetentionDecision] = []

    def pin(self, symbol: str, stream: StreamKind) -> None:
        """Test helper: mark a `(symbol, stream)` as pinned."""
        self._pinned.add((symbol, stream.value))

    def policies(self) -> list[Any]:
        return []

    async def plan(self, dry_run: bool = True) -> list[RetentionDecision]:
        return []

    async def apply(self, plan: list[RetentionDecision]) -> None:
        from candleviewer.storage.errors import StorageRetentionBlockedByPin

        for decision in plan:
            if (
                decision.action != "skip"
                and (decision.symbol, decision.stream.value) in self._pinned
            ):
                raise StorageRetentionBlockedByPin(
                    f"{decision.symbol}/{decision.stream.value} is pinned"
                )
            self.applied.append(decision)
        # Yield once so callers awaiting concurrently see deterministic
        # interleaving in tests (no real I/O to await here).
        await asyncio.sleep(0)
