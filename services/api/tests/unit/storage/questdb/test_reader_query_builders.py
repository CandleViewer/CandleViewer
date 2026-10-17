"""Unit tests for `candleviewer.storage.questdb.reader` query builders (E07-T03).

Query-builder lint (ticket "Technical notes / design"): every builder must
(a) filter on `symbol` by equality, (b) bound `ts` on both sides where the
shape has a range, and (c) never `ORDER BY` a non-timestamp column. Also
asserts every value that varies by call site is a bind parameter (`$n`),
never string-interpolated into the SQL text (SR-047).
"""

from __future__ import annotations

import re

import pytest

from candleviewer.domain.sql_names import ts_param
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb import reader

RNG = TimeRange(start_us=1_000, end_us=2_000)

_BUILDERS_WITH_RANGE = [
    (reader.build_read_bars, ("BTCUSDT", "time", "1m", RNG)),
    (reader.build_read_trades, ("BTCUSDT", RNG)),
    (reader.build_trade_totals, ("BTCUSDT", RNG)),
    (reader.build_read_big_trades, ("BTCUSDT", RNG, 1000.0)),
    (reader.build_read_book_deltas, ("BTCUSDT", RNG)),
    (reader.build_read_orderflow_metrics, ("BTCUSDT", "cvd", RNG)),
    (reader.build_read_footprint_cells, ("BTCUSDT", "time", "1m", RNG)),
    (reader.build_asof_trades_to_tickers, ("BTCUSDT", RNG)),
]


@pytest.mark.parametrize("builder_fn,args", _BUILDERS_WITH_RANGE)
def test_range_builders_filter_symbol_equality_and_bound_ts(builder_fn, args) -> None:  # type: ignore[no-untyped-def]
    qb = builder_fn(*args)
    assert re.search(r"symbol\s*=\s*\$1", qb.sql, re.IGNORECASE) or "t.symbol = $1" in qb.sql
    assert "ts >=" in qb.sql or "t.ts >=" in qb.sql
    assert "ts <" in qb.sql or "t.ts <" in qb.sql


@pytest.mark.parametrize("builder_fn,args", _BUILDERS_WITH_RANGE)
def test_range_builders_never_order_by_non_timestamp(builder_fn, args) -> None:  # type: ignore[no-untyped-def]
    qb = builder_fn(*args)
    order_by_match = re.search(r"ORDER BY\s+([\w.]+)", qb.sql, re.IGNORECASE)
    if order_by_match:
        col = order_by_match.group(1).lower()
        assert col.endswith("ts") or col == "ts"


def test_no_builder_interpolates_symbol_into_sql_text() -> None:
    qb = reader.build_read_trades("BTCUSDT", RNG)
    assert "BTCUSDT" not in qb.sql
    assert qb.params[0] == "BTCUSDT"


def test_build_trade_totals_is_one_bound_aggregate_never_rows() -> None:
    """#2093: count and sum over the designated-timestamp range; the symbol is a bind."""
    qb = reader.build_trade_totals("BTCUSDT", RNG)
    assert qb.sql == (
        "SELECT count() AS n, sum(size) AS qty FROM trades "
        "WHERE symbol = $1 AND ts >= $2 AND ts < $3"
    )
    assert qb.params == ("BTCUSDT", ts_param(1_000), ts_param(2_000))


def test_build_read_bars_rejects_unknown_family() -> None:
    with pytest.raises(ValueError, match="unknown bar family"):
        reader.build_read_bars("BTCUSDT", "not-a-family", "1m", RNG)


def test_build_latest_ticker_uses_latest_on() -> None:
    qb = reader.build_latest_ticker("BTCUSDT")
    assert "LATEST ON ts PARTITION BY symbol" in qb.sql
    assert qb.params == ("BTCUSDT",)


def test_build_read_book_snapshot_at_bounds_ts_one_sided() -> None:
    qb = reader.build_read_book_snapshot_at("BTCUSDT", 5_000)
    assert "ts <= $2" in qb.sql
    assert "ORDER BY ts DESC LIMIT 1" in qb.sql


def test_build_asof_join_uses_asof_join_keyword() -> None:
    qb = reader.build_asof_trades_to_tickers("BTCUSDT", RNG)
    assert "ASOF JOIN" in qb.sql


def test_build_read_heatmap_trail_filters_symbol_and_since_ts() -> None:
    qb = reader.build_read_heatmap_trail("BTCUSDT", 5_000)
    assert qb.params == ("BTCUSDT", ts_param(5_000))
    assert "symbol = $1" in qb.sql
    assert "ts > $2" in qb.sql


def test_build_read_profile_filters_symbol_kind_and_period_ref() -> None:
    qb = reader.build_read_profile("BTCUSDT", "volume", "2026-09-14")
    assert qb.params == ("BTCUSDT", "volume", "2026-09-14")
    assert "profile_kind = $2" in qb.sql
    assert "period_ref = $3" in qb.sql


@pytest.mark.asyncio
async def test_questdb_reader_runs_builder_against_fake_connection() -> None:
    class _FakeConn:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            return [{"sql": sql, "params": params}]

    r = reader.QuestDbReader(_FakeConn())
    qb = reader.build_latest_ticker("BTCUSDT")
    rows = await r.run(qb)
    assert rows[0]["params"] == ("BTCUSDT",)
