"""Unit tests for `candleviewer.storage.questdb.repository` (E07-T03).

Exercises `QuestDbMarketDataRepository`'s row-mapping and symbol-allowlist
logic against fake `IlpWriter`/`QuestDbReader` collaborators (no real
QuestDB connection — that's the integration suite,
`tests/integration/storage/test_questdb_hot_tier.py`, which needs docker and
is skipped in this environment).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.reader import build_trade_totals
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository, SymbolNotAllowed
from candleviewer.storage.repositories.rows import (
    BookDeltaRow,
    BookSnapshotRow,
    TickerRow,
    TradeRow,
    TradeTotals,
)


class _FakeWriter:
    def __init__(self) -> None:
        self.written: dict[str, list[dict[str, object]]] = {}

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self.written.setdefault(table, []).extend(rows)


class _FakeReader:
    def __init__(self, canned: list[dict[str, object]] | None = None) -> None:
        self.canned = canned or []
        self.last_builder: object | None = None

    async def run(self, builder: object) -> list[dict[str, object]]:
        self.last_builder = builder
        return self.canned


@pytest.mark.asyncio
async def test_write_trades_maps_row_fields_and_computes_notional() -> None:
    writer = _FakeWriter()
    repo = QuestDbMarketDataRepository(writer, _FakeReader())  # type: ignore[arg-type]
    await repo.write_trades(
        [TradeRow(ts_us=1_000, symbol="BTCUSDT", price="100", qty="2", side="buy", trade_id="t1")]
    )
    row = writer.written["trades"][0]
    assert row["notional"] == pytest.approx(200.0)
    assert row["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_write_trades_notional_uses_decimal_product_not_float_product() -> None:
    # float(0.1) * float(3) == 0.30000000000000004; the Decimal product is exactly 0.3.
    assert float("0.1") * float("3") != 0.3
    writer = _FakeWriter()
    repo = QuestDbMarketDataRepository(writer, _FakeReader())  # type: ignore[arg-type]
    await repo.write_trades(
        [TradeRow(ts_us=1_000, symbol="BTCUSDT", price="0.1", qty="3", side="buy", trade_id="t1")]
    )
    assert writer.written["trades"][0]["notional"] == 0.3


@pytest.mark.asyncio
async def test_write_book_snapshot_serialises_bids_asks_as_json() -> None:
    writer = _FakeWriter()
    repo = QuestDbMarketDataRepository(writer, _FakeReader())  # type: ignore[arg-type]
    snap = BookSnapshotRow(
        ts_us=1, symbol="BTCUSDT", seq=1, bids=(("100", "1"),), asks=(("101", "1"),)
    )
    await repo.write_book_snapshot(snap)
    row = writer.written["orderbook_snapshots"][0]
    assert json.loads(str(row["bids"])) == [["100", "1"]]


@pytest.mark.asyncio
async def test_write_bars_routes_by_family_to_correct_table() -> None:
    from candleviewer.storage.repositories.rows import BarRow

    writer = _FakeWriter()
    repo = QuestDbMarketDataRepository(writer, _FakeReader())  # type: ignore[arg-type]
    await repo.write_bars(
        [
            BarRow(
                ts_us=1,
                symbol="BTCUSDT",
                family="time",
                param="1m",
                open="1",
                high="2",
                low="0.5",
                close="1.5",
                volume="10",
            )
        ]
    )
    assert "bars_time" in writer.written


@pytest.mark.asyncio
async def test_write_bars_rejects_unknown_family() -> None:
    from candleviewer.storage.repositories.rows import BarRow

    writer = _FakeWriter()
    repo = QuestDbMarketDataRepository(writer, _FakeReader())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown bar family"):
        await repo.write_bars(
            [
                BarRow(
                    ts_us=1,
                    symbol="BTCUSDT",
                    family="bogus",
                    param="1m",
                    open="1",
                    high="2",
                    low="0.5",
                    close="1.5",
                    volume="10",
                )
            ]
        )


@pytest.mark.asyncio
async def test_read_trades_rejects_symbol_with_quote_character() -> None:
    """SQL-injection acceptance criterion: a symbol containing a quote must
    never reach the parameterised query — it fails the allowlist first."""
    repo = QuestDbMarketDataRepository(_FakeWriter(), _FakeReader())  # type: ignore[arg-type]
    with pytest.raises(SymbolNotAllowed):
        await repo.read_trades("BTC'; DROP TABLE trades;--", TimeRange(start_us=0, end_us=1))


@pytest.mark.asyncio
async def test_read_trades_passes_symbol_only_as_bind_parameter() -> None:
    reader = _FakeReader(
        canned=[
            {
                "ts": 1_000,
                "symbol": "BTCUSDT",
                "price": "100",
                "size": "1",
                "side": "buy",
                "trade_id": "t1",
            }
        ]
    )
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    rows = await repo.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=2_000))
    assert rows[0].trade_id == "t1"
    assert reader.last_builder is not None
    assert reader.last_builder.params[0] == "BTCUSDT"  # type: ignore[attr-defined]
    assert "BTCUSDT" not in reader.last_builder.sql  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("canned", "expected"),
    [
        ([{"n": 3, "qty": 0.30000000000000004}], TradeTotals(3, Decimal("0.30000000000000004"))),
        ([{"n": 0, "qty": None}], TradeTotals(0, Decimal(0))),  # QuestDB: sum of nothing is NULL
        ([], TradeTotals(0, Decimal(0))),
    ],
)
async def test_trade_totals_maps_the_one_aggregate_row(
    canned: list[dict[str, object]], expected: TradeTotals
) -> None:
    """#2093: the DOUBLE sum is read as its shortest repr, never re-rounded through float."""
    reader, rng = _FakeReader(canned), TimeRange(start_us=0, end_us=2_000)
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    assert await repo.trade_totals("BTCUSDT", rng) == expected
    assert reader.last_builder == build_trade_totals("BTCUSDT", rng)
    with pytest.raises(SymbolNotAllowed):
        await repo.trade_totals("BTC'; DROP TABLE trades;--", rng)


@pytest.mark.asyncio
async def test_latest_ticker_returns_none_when_no_rows() -> None:
    repo = QuestDbMarketDataRepository(_FakeWriter(), _FakeReader(canned=[]))  # type: ignore[arg-type]
    assert await repo.latest_ticker("BTCUSDT") is None


@pytest.mark.asyncio
async def test_latest_ticker_maps_row_to_ticker_row() -> None:
    reader = _FakeReader(
        canned=[
            {
                "ts": 1,
                "symbol": "BTCUSDT",
                "last_price": "1",
                "mark_price": "1",
                "index_price": "1",
                "funding_rate": "0",
                "open_interest": "0",
            }
        ]
    )
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    ticker = await repo.latest_ticker("BTCUSDT")
    assert isinstance(ticker, TickerRow)
    assert ticker.symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_read_orderflow_metrics_rejects_unknown_metric() -> None:
    repo = QuestDbMarketDataRepository(_FakeWriter(), _FakeReader())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown orderflow metric"):
        await repo.read_orderflow_metrics(
            "BTCUSDT", "not_a_metric", TimeRange(start_us=0, end_us=1)
        )


@pytest.mark.asyncio
async def test_write_book_deltas_maps_row_fields() -> None:
    writer = _FakeWriter()
    repo = QuestDbMarketDataRepository(writer, _FakeReader())  # type: ignore[arg-type]
    await repo.write_book_deltas(
        [BookDeltaRow(ts_us=1, symbol="BTCUSDT", seq=7, side="bid", price="100", qty="1")]
    )
    row = writer.written["orderbook_deltas"][0]
    assert row["update_id"] == 7
    assert row["side"] == "bid"


@pytest.mark.asyncio
async def test_write_tickers_maps_row_fields() -> None:
    from candleviewer.storage.repositories.rows import TickerRow as _TickerRow

    writer = _FakeWriter()
    repo = QuestDbMarketDataRepository(writer, _FakeReader())  # type: ignore[arg-type]
    await repo.write_tickers(
        [
            _TickerRow(
                ts_us=1,
                symbol="BTCUSDT",
                last_price="1",
                mark_price="1",
                index_price="1",
                funding_rate="0",
                open_interest="0",
            )
        ]
    )
    row = writer.written["tickers"][0]
    assert row["symbol"] == "BTCUSDT"
    assert row["last_price"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_read_bars_rejects_symbol_and_maps_row_fields() -> None:
    reader = _FakeReader(
        canned=[
            {
                "ts": 1,
                "symbol": "BTCUSDT",
                "bar_param": "1m",
                "open": "1",
                "high": "2",
                "low": "0.5",
                "close": "1.5",
                "volume": "10",
            }
        ]
    )
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    bars = await repo.read_bars("BTCUSDT", "time", "1m", TimeRange(start_us=0, end_us=2))
    assert bars[0].close == "1.5"
    assert bars[0].family == "time"
    with pytest.raises(SymbolNotAllowed):
        await repo.read_bars("bad'sym", "time", "1m", TimeRange(start_us=0, end_us=2))


@pytest.mark.asyncio
async def test_read_book_snapshot_at_returns_none_when_absent_and_maps_when_present() -> None:
    empty_repo = QuestDbMarketDataRepository(_FakeWriter(), _FakeReader(canned=[]))  # type: ignore[arg-type]
    assert await empty_repo.read_book_snapshot_at("BTCUSDT", 1, depth=5) is None

    reader = _FakeReader(
        canned=[
            {
                "ts": 1,
                "symbol": "BTCUSDT",
                "update_id": 9,
                "bids": json.dumps([["100", "1"], ["99", "2"]]),
                "asks": json.dumps([["101", "1"]]),
            }
        ]
    )
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    snap = await repo.read_book_snapshot_at("BTCUSDT", 1, depth=1)
    assert snap is not None
    assert snap.seq == 9
    assert snap.bids == (("100", "1"),)
    assert snap.asks == (("101", "1"),)

    with pytest.raises(SymbolNotAllowed):
        await repo.read_book_snapshot_at("bad'sym", 1, depth=1)


@pytest.mark.asyncio
async def test_read_book_deltas_maps_row_fields_and_checks_symbol() -> None:
    reader = _FakeReader(
        canned=[
            {
                "ts": 1,
                "symbol": "BTCUSDT",
                "update_id": 3,
                "side": "ask",
                "price": "100",
                "size": "1",
            }
        ]
    )
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    deltas = await repo.read_book_deltas("BTCUSDT", TimeRange(start_us=0, end_us=2))
    assert deltas[0].seq == 3
    assert deltas[0].side == "ask"
    with pytest.raises(SymbolNotAllowed):
        await repo.read_book_deltas("bad'sym", TimeRange(start_us=0, end_us=2))


@pytest.mark.asyncio
async def test_read_orderflow_metrics_maps_row_field_for_requested_metric() -> None:
    reader = _FakeReader(canned=[{"ts": 1, "symbol": "BTCUSDT", "cvd": "5"}])
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    rows = await repo.read_orderflow_metrics("BTCUSDT", "cvd", TimeRange(start_us=0, end_us=2))
    assert rows[0].metric == "cvd"
    assert rows[0].value == "5"
    with pytest.raises(SymbolNotAllowed):
        await repo.read_orderflow_metrics("bad'sym", "cvd", TimeRange(start_us=0, end_us=2))


@pytest.mark.asyncio
async def test_read_footprint_cells_maps_row_fields_and_checks_symbol() -> None:
    reader = _FakeReader(
        canned=[
            {
                "ts": 1,
                "symbol": "BTCUSDT",
                "price": "100",
                "bid_volume": "1",
                "ask_volume": "2",
            }
        ]
    )
    repo = QuestDbMarketDataRepository(_FakeWriter(), reader)  # type: ignore[arg-type]
    cells = await repo.read_footprint_cells("BTCUSDT", TimeRange(start_us=0, end_us=2))
    assert cells[0].price_level == "100"
    assert cells[0].bid_qty == "1"
    with pytest.raises(SymbolNotAllowed):
        await repo.read_footprint_cells("bad'sym", TimeRange(start_us=0, end_us=2))
