"""Shared `MarketDataRepository` contract suite (E07-T01 acceptance criterion
3: "a contract test suite written once is parametrized over [fake] today and
[questdb, timescale] later ... the same suite passes unchanged").

E07-T02/T03/T04 import `market_data_contract_tests` (or copy its test
bodies via a shared fixture) and parametrize `repo` over their own
implementations; this ticket runs it against `FakeMarketDataRepository` only.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.market_data import MarketDataRepository
from candleviewer.storage.repositories.rows import BarRow, BookDeltaRow, TradeRow, TradeTotals
from candleviewer.storage.testing import FakeMarketDataRepository


@pytest.fixture(params=["fake"])
def repo(request: pytest.FixtureRequest) -> MarketDataRepository:
    if request.param == "fake":
        return FakeMarketDataRepository()
    raise AssertionError(f"unknown param {request.param!r}")  # pragma: no cover


async def test_write_then_read_trades_round_trips(repo: MarketDataRepository) -> None:
    rows = [
        TradeRow(
            ts_us=1_000, symbol="BTCUSDT", price="50000", qty="0.1", side="buy", trade_id="t1"
        ),
        TradeRow(
            ts_us=2_000, symbol="BTCUSDT", price="50010", qty="0.2", side="sell", trade_id="t2"
        ),
    ]
    await repo.write_trades(rows)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=3_000))
    assert result == rows


async def test_read_trades_orders_by_ts_ascending(repo: MarketDataRepository) -> None:
    out_of_order = [
        TradeRow(ts_us=3_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a"),
        TradeRow(ts_us=1_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="b"),
        TradeRow(ts_us=2_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="c"),
    ]
    await repo.write_trades(out_of_order)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=10_000))
    assert [r.ts_us for r in result] == [1_000, 2_000, 3_000]


async def test_read_trades_filters_by_range(repo: MarketDataRepository) -> None:
    rows = [
        TradeRow(ts_us=ts, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id=str(ts))
        for ts in (100, 200, 300, 400)
    ]
    await repo.write_trades(rows)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=150, end_us=350))
    assert [r.ts_us for r in result] == [200, 300]


async def test_write_trades_dedups_on_natural_key(repo: MarketDataRepository) -> None:
    original = TradeRow(
        ts_us=1_000, symbol="BTCUSDT", price="50000", qty="0.1", side="buy", trade_id="t1"
    )
    updated = TradeRow(
        ts_us=1_000, symbol="BTCUSDT", price="50001", qty="0.2", side="buy", trade_id="t1"
    )
    await repo.write_trades([original])
    await repo.write_trades([updated])
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=2_000))
    assert result == [updated]


async def test_read_trades_scoped_by_symbol(repo: MarketDataRepository) -> None:
    await repo.write_trades(
        [
            TradeRow(ts_us=100, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a"),
            TradeRow(ts_us=100, symbol="ETHUSDT", price="1", qty="1", side="buy", trade_id="b"),
        ]
    )
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert [r.symbol for r in result] == ["BTCUSDT"]


async def test_trade_totals_count_and_sum_the_symbols_prints_in_the_range(
    repo: MarketDataRepository,
) -> None:
    """#2093: start-inclusive, end-exclusive, symbol-scoped, deduplicated like `read_trades`."""
    await repo.write_trades(
        [
            TradeRow(ts_us=ts, symbol=sym, price="1", qty=qty, side="buy", trade_id=f"{sym}{ts}")
            for ts, sym, qty in [(99, "BTCUSDT", "5"), (100, "BTCUSDT", "0.1"),
                                 (100, "ETHUSDT", "7"), (150, "BTCUSDT", "0.2"),
                                 (150, "BTCUSDT", "0.2"), (200, "BTCUSDT", "9")]
        ]
    )  # fmt: skip
    got = await repo.trade_totals("BTCUSDT", TimeRange(start_us=100, end_us=200))
    assert got == TradeTotals(2, Decimal("0.3"))
    none = await repo.trade_totals("BTCUSDT", TimeRange(start_us=300, end_us=400))
    assert none == TradeTotals(0, Decimal(0))


async def test_write_then_read_bars_round_trips(repo: MarketDataRepository) -> None:
    bar = BarRow(
        ts_us=60_000_000,
        symbol="BTCUSDT",
        family="time",
        param="60000",
        open="1",
        high="2",
        low="0.5",
        close="1.5",
        volume="10",
    )
    await repo.write_bars([bar])
    result = await repo.read_bars(
        "BTCUSDT", "time", "60000", TimeRange(start_us=0, end_us=120_000_000)
    )
    assert result == [bar]


async def test_latest_ticker_returns_none_when_unwritten(repo: MarketDataRepository) -> None:
    assert await repo.latest_ticker("BTCUSDT") is None


async def test_read_book_snapshot_at_returns_none_before_any_snapshot(
    repo: MarketDataRepository,
) -> None:
    assert await repo.read_book_snapshot_at("BTCUSDT", ts_us=1, depth=10) is None


# --- CS-07: replaying an identical batch leaves the row count unchanged. ---


async def test_replaying_identical_trade_batch_twice_is_idempotent(
    repo: MarketDataRepository,
) -> None:
    rows = [
        TradeRow(ts_us=ts, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id=str(ts))
        for ts in (100, 200, 300)
    ]
    await repo.write_trades(rows)
    await repo.write_trades(rows)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert len(result) == 3


async def test_replaying_identical_trade_batch_thrice_is_idempotent(
    repo: MarketDataRepository,
) -> None:
    rows = [
        TradeRow(ts_us=ts, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id=str(ts))
        for ts in (100, 200, 300)
    ]
    for _ in range(3):
        await repo.write_trades(rows)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert len(result) == 3


# --- CS-08/09/10: empty, future, and unknown-symbol ranges never raise. ---


async def test_empty_range_returns_empty_list(repo: MarketDataRepository) -> None:
    await repo.write_trades(
        [TradeRow(ts_us=100, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a")]
    )
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=100, end_us=100))
    assert result == []


async def test_range_entirely_in_the_future_returns_empty_list(
    repo: MarketDataRepository,
) -> None:
    await repo.write_trades(
        [TradeRow(ts_us=100, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a")]
    )
    result = await repo.read_trades(
        "BTCUSDT", TimeRange(start_us=1_000_000_000, end_us=2_000_000_000)
    )
    assert result == []


async def test_symbol_with_no_data_returns_empty_for_every_read(
    repo: MarketDataRepository,
) -> None:
    rng = TimeRange(start_us=0, end_us=1_000_000)
    assert await repo.read_trades("NODATA", rng) == []
    assert await repo.read_book_deltas("NODATA", rng) == []
    assert await repo.read_bars("NODATA", "time", "60000", rng) == []
    assert await repo.latest_ticker("NODATA") is None
    assert await repo.read_book_snapshot_at("NODATA", ts_us=1, depth=10) is None


# --- CS-11: a single-row partition round-trips (degenerate, not just N>=2). ---


async def test_single_row_partition_round_trips(repo: MarketDataRepository) -> None:
    row = TradeRow(ts_us=500, symbol="ETHUSDT", price="2500", qty="1", side="sell", trade_id="x")
    await repo.write_trades([row])
    result = await repo.read_trades("ETHUSDT", TimeRange(start_us=0, end_us=1_000))
    assert result == [row]


# --- CS-12: a range spanning a calendar-month boundary. ---


async def test_range_spanning_month_boundary_preserves_ordering_and_count(
    repo: MarketDataRepository,
) -> None:
    # 2026-01-31T23:59:59.900Z and 2026-02-01T00:00:00.100Z, in microseconds.
    before_us = 1_769_903_999_900_000
    after_us = 1_769_904_000_100_000
    rows = [
        TradeRow(ts_us=before_us, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="m1"),
        TradeRow(ts_us=after_us, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="m2"),
    ]
    await repo.write_trades(rows)
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=before_us, end_us=after_us + 1))
    assert [r.ts_us for r in result] == [before_us, after_us]


# --- CS-13/14/15: ts_us exactly at the caller-supplied boundary (inclusive-start,
# exclusive-end per `MarketDataRepository`'s documented range contract). ---


async def test_ts_at_range_start_boundary_is_included(repo: MarketDataRepository) -> None:
    boundary = 1_000
    row = TradeRow(ts_us=boundary, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="b")
    await repo.write_trades([row])
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=boundary, end_us=boundary + 1))
    assert result == [row]


async def test_ts_at_range_end_boundary_is_excluded(repo: MarketDataRepository) -> None:
    boundary = 1_000
    row = TradeRow(ts_us=boundary, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="b")
    await repo.write_trades([row])
    result = await repo.read_trades("BTCUSDT", TimeRange(start_us=boundary - 1, end_us=boundary))
    assert result == []


async def test_ts_one_us_after_end_boundary_is_excluded(repo: MarketDataRepository) -> None:
    boundary = 1_000
    row = TradeRow(
        ts_us=boundary + 1, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="b"
    )
    await repo.write_trades([row])
    result = await repo.read_trades(
        "BTCUSDT", TimeRange(start_us=boundary - 1, end_us=boundary + 1)
    )
    assert result == []


# --- CS-16: book-delta dedup on (symbol, seq), ordered (ts_us, seq). ---


async def test_book_deltas_dedup_on_seq_and_order_by_ts_then_seq(
    repo: MarketDataRepository,
) -> None:
    original = BookDeltaRow(ts_us=100, symbol="BTCUSDT", seq=1, side="bid", price="50000", qty="1")
    updated = BookDeltaRow(ts_us=100, symbol="BTCUSDT", seq=1, side="bid", price="50000", qty="2")
    other = BookDeltaRow(ts_us=50, symbol="BTCUSDT", seq=2, side="ask", price="50010", qty="1")
    await repo.write_book_deltas([original])
    await repo.write_book_deltas([updated, other])
    result = await repo.read_book_deltas("BTCUSDT", TimeRange(start_us=0, end_us=1_000))
    assert result == [other, updated]


# --- CS-17: latest_ticker returns the highest-ts_us row after out-of-order writes. ---


async def test_latest_ticker_returns_highest_ts_after_out_of_order_writes(
    repo: MarketDataRepository,
) -> None:
    from candleviewer.storage.repositories.rows import TickerRow

    rows = [
        TickerRow(
            ts_us=ts,
            symbol="BTCUSDT",
            last_price="1",
            mark_price="1",
            index_price="1",
            funding_rate="0",
            open_interest="0",
        )
        for ts in (300, 100, 200)
    ]
    await repo.write_tickers(rows)
    latest = await repo.latest_ticker("BTCUSDT")
    assert latest is not None
    assert latest.ts_us == 300
