"""`MarketDataRepository` implementation over the QuestDB hot tier (E07-T03).

Passes the E07-T01 contract suite unchanged (`tests/contract/storage/
test_market_data_contract.py`) against the real engine. Writes go through
`IlpWriter`; reads through `QuestDbReader`'s query builders. Symbol/interval
values are validated against an allowlist derived from `instruments` before
reaching SQL (`docs/plan/04-security-program.md` Sec.5.8) — this ticket's
fixture-only scope uses a permissive default allowlist hook the real
`instruments` cache (E08+) overrides.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from decimal import Decimal

import asyncpg

from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import TierHint, TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import (
    QuestDbReader,
    build_first_trade,
    build_latest_ticker,
    build_read_bars,
    build_read_book_deltas,
    build_read_book_snapshot_at,
    build_read_footprint_cells,
    build_read_klines,
    build_read_orderflow_metrics,
    build_read_trades,
    build_trade_totals,
)
from candleviewer.storage.questdb.schemas import BAR_SCHEMAS_BY_FAMILY
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

#: A conservative default symbol allowlist check: venue USDT-perp symbols are
#: uppercase alnum (e.g. `BTCUSDT`). The real per-account `instruments` cache
#: (E08+) will inject a stricter, exchange-fed allowlist via
#: `symbol_allowlist`; this regex is the floor every symbol must clear
#: regardless (SR-047 — `SYMBOL` filters are the only user-controlled
#: predicate reaching SQL).
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,32}$")

#: asyncpg's three error roots: the server's, the client's and its client-internal ones
#: (`ProtocolError` and kin). `CancelledError`, a `BaseException`, is none of them and propagates.
_DRIVER_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, asyncpg.InternalClientError)


class SymbolNotAllowed(ValueError):
    """Raised when a `sym` argument fails the allowlist check before it
    would otherwise reach a parameterised query."""


def _default_symbol_allowlist(sym: str) -> bool:
    return bool(_SYMBOL_RE.fullmatch(sym))


class QuestDbMarketDataRepository:
    """`MarketDataRepository` Protocol implementation over QuestDB."""

    def __init__(
        self,
        writer: IlpWriter,
        reader: QuestDbReader,
        *,
        symbol_allowlist: Callable[[str], bool] = _default_symbol_allowlist,
    ) -> None:
        self._writer = writer
        self._reader = reader
        self._symbol_allowlist = symbol_allowlist

    def _check_symbol(self, sym: str) -> None:
        if not self._symbol_allowlist(sym):
            raise SymbolNotAllowed(f"symbol {sym!r} is not in the allowlist")

    async def write_trades(self, rows: Sequence[TradeRow]) -> None:
        payload = [
            {
                "ts": row.ts_us,
                "symbol": row.symbol,
                "side": row.side,
                "price": float(row.price),
                "size": float(row.qty),
                "notional": float(Decimal(row.price) * Decimal(row.qty)),
                "trade_id": row.trade_id,
            }
            for row in rows
        ]
        await self._writer.write_rows("trades", payload, "ts")

    async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None:
        payload = [
            {
                "ts": row.ts_us,
                "symbol": row.symbol,
                "side": row.side,
                "price": float(row.price),
                "size": float(row.qty),
                "update_id": row.seq,
                "cross_seq": row.seq,
            }
            for row in rows
        ]
        await self._writer.write_rows("orderbook_deltas", payload, "ts")

    async def write_book_snapshot(self, row: BookSnapshotRow) -> None:
        import json

        payload = [
            {
                "ts": row.ts_us,
                "symbol": row.symbol,
                "update_id": row.seq,
                "cross_seq": row.seq,
                "source": "exchange",
                "bids": json.dumps(row.bids),
                "asks": json.dumps(row.asks),
                "level_count": len(row.bids) + len(row.asks),
            }
        ]
        await self._writer.write_rows("orderbook_snapshots", payload, "ts")

    async def write_tickers(self, rows: Sequence[TickerRow]) -> None:
        payload: list[dict[str, object]] = []
        for row in rows:
            item: dict[str, object] = {
                "ts": row.ts_us,
                "symbol": row.symbol,
                "last_price": float(row.last_price),
                "mark_price": float(row.mark_price),
                "index_price": float(row.index_price),
                "funding_rate": float(row.funding_rate),
                "open_interest": float(row.open_interest),
            }
            for col in ("bid1_price", "bid1_size", "ask1_price", "ask1_size"):
                val = getattr(row, col)
                if val is not None:
                    item[col] = float(val)
            payload.append(item)
        await self._writer.write_rows("tickers", payload, "ts")

    async def write_bars(self, rows: Sequence[BarRow]) -> None:
        by_family: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_family.setdefault(row.family, []).append(
                {
                    "ts": row.ts_us,
                    "symbol": row.symbol,
                    "bar_param": row.param,
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume),
                    "is_closed": True,
                }
            )
        for family, table_rows in by_family.items():
            if family not in BAR_SCHEMAS_BY_FAMILY:
                raise ValueError(f"unknown bar family {family!r}")
            table = f"bars_{family}"
            await self._writer.write_rows(table, table_rows, "ts")

    async def write_klines(self, rows: Sequence[KlineRow]) -> None:
        payload = [
            {
                "ts": row.ts_us,
                "symbol": row.symbol,
                "interval": row.interval,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "turnover": float(row.turnover),
                "confirmed": row.confirmed,
                "source": row.source,
            }
            for row in rows
        ]
        await self._writer.write_rows("klines", payload, "ts")

    async def read_bars(
        self,
        sym: str,
        family: str,
        param: str,
        rng: TimeRange,
        tier: TierHint = "auto",
    ) -> list[BarRow]:
        self._check_symbol(sym)
        rows = await self._reader.run(build_read_bars(sym, family, param, rng))
        return [
            BarRow(
                ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                family=family,
                param=str(r["bar_param"]),
                open=str(r["open"]),
                high=str(r["high"]),
                low=str(r["low"]),
                close=str(r["close"]),
                volume=str(r["volume"]),
            )
            for r in rows
        ]

    async def read_klines(
        self,
        sym: str,
        interval: str,
        rng: TimeRange,
        tier: TierHint = "auto",
        limit: int | None = None,
    ) -> list[KlineRow]:
        self._check_symbol(sym)
        rows = await self._reader.run(build_read_klines(sym, interval, rng, limit))
        if limit is not None:
            rows = sorted(rows, key=lambda r: ts_us_from_row(r["ts"]))
        return [
            KlineRow(
                ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                interval=interval,
                open=str(r["open"]),
                high=str(r["high"]),
                low=str(r["low"]),
                close=str(r["close"]),
                volume=str(r["volume"]),
                turnover=str(r["turnover"]),
                confirmed=bool(r["confirmed"]),
                source=str(r["source"]),
            )
            for r in rows
        ]

    async def first_trade_us(self, sym: str) -> int | None:
        self._check_symbol(sym)
        rows = await self._reader.run(build_first_trade(sym))
        return ts_us_from_row(rows[0]["ts"]) if rows else None

    async def trade_totals(self, sym: str, rng: TimeRange, tier: TierHint = "auto") -> TradeTotals:
        self._check_symbol(sym)
        try:
            rows = await self._reader.run(build_trade_totals(sym, rng))
        except _DRIVER_ERRORS as exc:
            raise StorageTierUnavailable("the trades count failed in the driver") from exc
        n, qty = (rows[0]["n"], rows[0]["qty"]) if rows else (0, None)
        return TradeTotals(int(str(n)), Decimal(0) if qty is None else Decimal(str(qty)))

    async def read_trades(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[TradeRow]:
        self._check_symbol(sym)
        rows = await self._reader.run(build_read_trades(sym, rng))
        return [
            TradeRow(
                ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                price=str(r["price"]),
                qty=str(r["size"]),
                side=str(r["side"]),
                trade_id=str(r["trade_id"]),
            )
            for r in rows
        ]

    async def read_book_snapshot_at(
        self, sym: str, ts_us: int, depth: int, tier: TierHint = "auto"
    ) -> BookSnapshotRow | None:
        import json

        self._check_symbol(sym)
        rows = await self._reader.run(build_read_book_snapshot_at(sym, ts_us))
        if not rows:
            return None
        r = rows[0]
        bids = tuple(tuple(pair) for pair in json.loads(str(r["bids"]))[:depth])
        asks = tuple(tuple(pair) for pair in json.loads(str(r["asks"]))[:depth])
        return BookSnapshotRow(
            ts_us=ts_us_from_row(r["ts"]),
            symbol=str(r["symbol"]),
            seq=int(str(r["update_id"])),
            bids=bids,
            asks=asks,
        )

    async def read_book_deltas(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[BookDeltaRow]:
        self._check_symbol(sym)
        rows = await self._reader.run(build_read_book_deltas(sym, rng))
        return [
            BookDeltaRow(
                ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                seq=int(str(r["update_id"])),
                side=str(r["side"]),
                price=str(r["price"]),
                qty=str(r["size"]),
            )
            for r in rows
        ]

    async def read_orderflow_metrics(
        self, sym: str, metric: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[OrderflowMetricRow]:
        self._check_symbol(sym)
        allowed_metrics = {
            "cvd",
            "cvd_session",
            "delta_1s",
            "trades_per_sec",
            "notional_per_sec",
            "buy_ratio",
            "book_imbalance",
            "book_thickness",
            "spread_ticks",
            "realized_vol_1m",
            "atr_14",
        }
        if metric not in allowed_metrics:
            raise ValueError(f"unknown orderflow metric {metric!r}")
        rows = await self._reader.run(build_read_orderflow_metrics(sym, metric, rng))
        return [
            OrderflowMetricRow(
                ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                metric=metric,
                value=str(r[metric]),
            )
            for r in rows
        ]

    async def read_footprint_cells(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[FootprintCellRow]:
        self._check_symbol(sym)
        # A single-shape query across every (bar_family, bar_param) is not
        # meaningful for footprint cells (Sec.13.2 shape #2 is always scoped
        # to one bar_family/bar_param); callers needing this Protocol method
        # generically get the "time"/"1m" default, matching the fixture
        # smoke-test's bar spec.
        rows = await self._reader.run(build_read_footprint_cells(sym, "time", "1m", rng))
        return [
            FootprintCellRow(
                bar_ts_us=ts_us_from_row(r["ts"]),
                symbol=str(r["symbol"]),
                price_level=str(r["price"]),
                bid_qty=str(r["bid_volume"]),
                ask_qty=str(r["ask_volume"]),
            )
            for r in rows
        ]

    async def latest_ticker(self, sym: str, tier: TierHint = "auto") -> TickerRow | None:
        self._check_symbol(sym)
        rows = await self._reader.run(build_latest_ticker(sym))
        if not rows:
            return None
        r = rows[0]
        return TickerRow(
            ts_us=ts_us_from_row(r["ts"]),
            symbol=str(r["symbol"]),
            last_price=str(r["last_price"]),
            mark_price=str(r["mark_price"]),
            index_price=str(r["index_price"]),
            funding_rate=str(r["funding_rate"]),
            open_interest=str(r["open_interest"]),
        )
