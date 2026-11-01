"""E24-T01 (#665): the QuestDB open-interest store's rows and parameterised reads."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from candleviewer.domain.open_interest import OiPoint
from candleviewer.domain.sql_names import ts_param
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.oi_store import QuestDbOiStore
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS, OPEN_INTEREST_SCHEMA


class _Writer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]], str]] = []

    async def write_rows(self, table: str, rows: list[dict[str, object]], key: str) -> None:
        self.calls.append((table, rows, key))


class _Reader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.sql: list[tuple[str, tuple[object, ...]]] = []

    async def run(self, builder: object) -> list[dict[str, object]]:
        self.sql.append((builder.sql, builder.params))  # type: ignore[attr-defined]
        return self.rows


def _store(writer: _Writer, reader: _Reader) -> QuestDbOiStore:
    return QuestDbOiStore(writer, reader)  # type: ignore[arg-type]  # structural fakes


async def test_oi_store_writes_rest_row_without_value_and_ticker_row_with_it() -> None:
    writer = _Writer()
    rest = OiPoint(5, "BTCUSDT", Decimal("1.5"), None, "5min", "rest")
    tick = OiPoint(6, "BTCUSDT", Decimal("1.5"), Decimal("90"), "1s", "ws_ticker")
    await _store(writer, _Reader([])).write_points([rest, tick])
    await _store(writer, _Reader([])).write_points([])
    table, rows, key = writer.calls[0]
    assert (table, key, len(writer.calls)) == ("open_interest", "ts", 1)
    assert "oi_value" not in rows[0] and rows[1]["oi_value"] == 90.0
    assert (rows[0]["interval"], rows[0]["source"]) == ("5min", "rest")
    fields = {k: v for k, v in rows[1].items() if k != "ts"}
    line = serialize_ilp_line(OPEN_INTEREST_SCHEMA, fields, 6)
    assert line.startswith("open_interest,symbol=BTCUSDT,interval=1s,source=ws_ticker ")
    assert ALL_SCHEMAS["open_interest"] is OPEN_INTEREST_SCHEMA


async def test_oi_store_read_binds_every_predicate_and_maps_rows() -> None:
    ts = datetime(2026, 9, 14, 10, 25, tzinfo=UTC)
    row = {"ts": ts, "symbol": "BTCUSDT", "oi": 61180.22, "oi_value": None,
           "interval": "5min", "source": "rest"}  # fmt: skip
    reader = _Reader([row, {**row, "oi": None}])
    got = await _store(_Writer(), reader).read_points(
        "BTCUSDT", "5min", "rest", TimeRange(start_us=1, end_us=2), 11
    )
    sql, params = reader.sql[0]
    assert params == ("BTCUSDT", "5min", "rest", ts_param(1), ts_param(2))
    assert "interval = $2 AND source = $3" in sql and sql.endswith("ORDER BY ts LIMIT 11")
    assert got == [
        OiPoint(int(ts.timestamp()) * 1_000_000, "BTCUSDT", Decimal("61180.22"), None, "5min",
                "rest")
    ]  # fmt: skip


async def test_oi_store_coverage_is_min_max_or_none_when_empty() -> None:
    reader = _Reader([{"lo": 10, "hi": 20}])
    assert await _store(_Writer(), reader).coverage("BTCUSDT", "1s", "ws_ticker") == (10, 20)
    assert reader.sql[0][1] == ("BTCUSDT", "1s", "ws_ticker")
    empty = _Reader([{"lo": None, "hi": None}])
    assert await _store(_Writer(), empty).coverage("BTCUSDT", "1s", "ws_ticker") is None


async def test_oi_store_refuses_a_non_identifier_symbol_before_querying() -> None:
    reader = _Reader([])
    with pytest.raises(ValueError):
        await _store(_Writer(), reader).read_points(
            "BTC;DROP", "5min", "rest", TimeRange(start_us=1, end_us=2), 1
        )
    assert reader.sql == []
