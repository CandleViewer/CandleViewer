"""E12-S05 / BR-07 / SR-E12-10: kline-sourced `bars_time` rows carry NULL order-flow fields,
`source=kline`, and never overwrite a tape row (writer-side and stored-row-side)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.bars.kline_rows import (
    KLINE_SOURCE,
    ORDERFLOW_NULL_COLUMNS,
    KlineRowError,
    kline_row,
    kline_rows,
    kline_spec,
    stored_tape_lookup,
    submit_kline_bars,
)
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.rows import BarPersistError, row_checksum
from candleviewer.bars.writer import BarWriter, SourceOverwriteRefused
from candleviewer.domain.sql_names import ts_param, ts_us_from_row
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.schemas import BAR_SCHEMAS_BY_FAMILY

T0 = 1_700_000_000_000_000
W5 = 300_000_000
SPEC = kline_spec("5")


def _k(start: int = T0, *, confirmed: bool = True, symbol: str = "BTCUSDT") -> KlineEvent:
    return KlineEvent.model_validate(
        dict(
            event_id="00000000-0000-7000-8000-000000000001", ts_event=start, ts_ingest=start,
            source="backfill", symbol=symbol, interval="5", start=start, end=start + W5 - 1,
            open="100.1", high="101", low="99.5", close="100.5", volume="10", turnover="1001",
            confirmed=confirmed,
        )
    )  # fmt: skip


def _tape_bar(open_time: int) -> Bar:
    d = Decimal
    return Bar.model_validate(
        dict(
            spec_hash=SPEC.spec_hash, symbol="BTCUSDT", index=1, open_time=open_time,
            close_time=open_time + W5, open=d("1"), high=d("2"), low=d("1"), close=d("2"),
            volume=d("3"), buy_volume=d("2"), sell_volume=d("1"), delta=d("1"),
            min_delta=d("0"), max_delta=d("1"), trade_count=2, turnover=d("5"), vwap=d("1.5"),
            closed=True, partial=False, gap_before=False,
        )
    )  # fmt: skip


async def _none_stored(symbol: str, bar_param: str, ts: list[int]) -> set[int]:
    return set()


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def write_rows(self, t: str, rows: list[dict[str, object]], k: str) -> None:
        self.rows.extend(rows)


def test_kline_spec_maps_bybit_interval_to_time_spec() -> None:
    assert SPEC == BarSpec(kind="time", interval_ms=300_000)
    assert kline_spec("D").interval_ms == 86_400_000


def test_kline_row_orderflow_columns_are_null_not_zero() -> None:
    row = kline_row(_k(), SPEC)
    for col in ORDERFLOW_NULL_COLUMNS:
        assert row[col] is None, col
    assert {"delta", "min_delta", "max_delta"} <= set(ORDERFLOW_NULL_COLUMNS)
    assert row["source"] == KLINE_SOURCE and row["bar_param"] == "5m"
    assert row["open"] == 100.1 and row["volume"] == 10.0
    assert row["ts"] == T0 and row["close_ts"] == T0 + W5 and row["is_closed"] is True
    assert row["row_checksum"] == row_checksum(row)


def test_kline_row_ilp_line_omits_orderflow_fields_so_they_read_null() -> None:
    row = kline_row(_k(), SPEC)
    line = serialize_ilp_line(
        BAR_SCHEMAS_BY_FAMILY["time"], {k: v for k, v in row.items() if k != "ts"}, T0
    )
    for col in ORDERFLOW_NULL_COLUMNS:
        assert f"{col}=" not in line
    assert "source=kline" in line or 'source="kline"' in line


def test_kline_row_refuses_unconfirmed_and_non_time() -> None:
    with pytest.raises(KlineRowError):
        kline_row(_k(confirmed=False), SPEC)
    with pytest.raises(KlineRowError):
        kline_row(_k(), BarSpec(kind="tick", tick_count=100))


def test_kline_rows_skips_unconfirmed() -> None:
    rows = kline_rows([_k(T0), _k(T0 + W5, confirmed=False)], SPEC)
    assert [r["ts"] for r in rows] == [T0]


async def test_submit_kline_bars_queues_kline_rows() -> None:
    sink = _Sink()
    w = BarWriter(sink)
    await w.start()
    n = await submit_kline_bars(w, "BTCUSDT", "5", [_k(T0), _k(T0 + W5, confirmed=False)],
                                  stored_higher=_none_stored)  # fmt: skip
    await w.stop()
    assert n == 1
    assert [r["source"] for r in sink.rows] == ["kline"]
    assert sink.rows[0]["delta"] is None


async def test_submit_kline_bars_never_overwrites_tape_written_by_this_process() -> None:
    sink = _Sink()
    w = BarWriter(sink)
    await w.start()
    await w.submit([_tape_bar(T0 + W5)], SPEC, source="tape", generation=0)
    n = await submit_kline_bars(w, "BTCUSDT", "5", [_k(T0), _k(T0 + W5), _k(T0 + 2 * W5)],
                                  stored_higher=_none_stored)  # fmt: skip
    await w.stop()
    assert n == 2
    by_ts = {(r["ts"], r["source"]) for r in sink.rows}
    assert (T0 + W5, "tape") in by_ts and (T0 + W5, "kline") not in by_ts
    assert {(T0, "kline"), (T0 + 2 * W5, "kline")} <= by_ts


async def test_submit_kline_bars_drops_open_times_holding_a_stored_tape_row() -> None:
    sink = _Sink()
    w = BarWriter(sink)
    await w.start()
    asked: list[tuple[str, str, list[int]]] = []

    async def stored_higher(symbol: str, bar_param: str, ts: list[int]) -> set[int]:
        asked.append((symbol, bar_param, ts))
        return {T0}

    n = await submit_kline_bars(
        w, "BTCUSDT", "5", [_k(T0), _k(T0 + W5)], stored_higher=stored_higher
    )
    await w.stop()
    assert n == 1 and [r["ts"] for r in sink.rows] == [T0 + W5]
    assert asked == [("BTCUSDT", "5m", [T0, T0 + W5])]


async def test_submit_kline_bars_all_taken_or_foreign_symbol_queues_nothing() -> None:
    w = BarWriter(_Sink())

    async def all_taken(symbol: str, bar_param: str, ts: list[int]) -> set[int]:
        return set(ts)

    assert await submit_kline_bars(w, "BTCUSDT", "5", [_k()], stored_higher=all_taken) == 0
    assert await submit_kline_bars(w, "BTCUSDT", "5", [_k(symbol="ETHUSDT")],
                                   stored_higher=_none_stored) == 0  # fmt: skip
    assert await submit_kline_bars(w, "BTCUSDT", "5", [], stored_higher=_none_stored) == 0


async def test_writer_submit_rows_refuses_mislabelled_source() -> None:
    w = BarWriter(_Sink())
    row = kline_row(_k(), SPEC)
    with pytest.raises(BarPersistError):
        await w.submit_rows([row], SPEC, source="tape")
    with pytest.raises(BarPersistError):
        await w.submit_rows([row], SPEC, source="bogus")


async def test_writer_submit_rows_kline_over_tape_raises_source_overwrite_refused() -> None:
    w = BarWriter(_Sink())
    await w.start()
    await w.submit([_tape_bar(T0)], SPEC, source="tape", generation=0)
    with pytest.raises(SourceOverwriteRefused):
        await w.submit_rows([kline_row(_k(T0), SPEC)], SPEC, source="kline")
    await w.stop()


class _Conn:
    """Hot-tier fake: stored `bars_time` rows as the deployed key `(ts, symbol, bar_param)`."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.queries.append((sql, params))
        sym, param, lo_dt, hi_dt = params
        lo, hi = ts_us_from_row(lo_dt), ts_us_from_row(hi_dt)  # the real server gets datetimes
        return [
            r for r in self.rows
            if r["symbol"] == sym and r["bar_param"] == param and lo <= r["ts"] <= hi  # type: ignore[operator]
            and r["source"] != "kline"
        ]  # fmt: skip


async def test_fresh_writer_after_restart_refuses_kline_over_stored_tape_and_counts() -> None:
    """#2044 F4 / BR-07: a NEW writer (empty in-process precedence map) + a stored tape row
    at the same `(ts, symbol, bar_param)` -> the kline row is refused and counted."""
    from candleviewer.bars.writer import bars_source_overwrite_refused_total

    conn = _Conn([
        {"ts": T0, "symbol": "BTCUSDT", "bar_param": "5m", "source": "tape"},
        {"ts": T0 + W5, "symbol": "BTCUSDT", "bar_param": "5m", "source": None},  # legacy
        {"ts": T0 + 2 * W5, "symbol": "BTCUSDT", "bar_param": "5m", "source": "kline"},
    ])  # fmt: skip
    sink = _Sink()
    w = BarWriter(sink)
    await w.start()
    before = bars_source_overwrite_refused_total.labels("kline", "tape")._value.get()
    n = await submit_kline_bars(
        w, "BTCUSDT", "5", [_k(T0), _k(T0 + W5), _k(T0 + 2 * W5)],
        stored_higher=stored_tape_lookup(conn),
    )  # fmt: skip
    await w.stop()
    assert n == 1 and [r["ts"] for r in sink.rows] == [T0 + 2 * W5]  # kline over kline: ok
    after = bars_source_overwrite_refused_total.labels("kline", "tape")._value.get()
    assert after == before + 2
    sql, params = conn.queries[0]
    assert "$1" in sql
    assert params == ("BTCUSDT", "5m", ts_param(T0), ts_param(T0 + 2 * W5))


async def test_stored_tape_lookup_empty_input_makes_no_query() -> None:
    conn = _Conn([])
    assert await stored_tape_lookup(conn)("BTCUSDT", "5m", []) == set()
    assert conn.queries == []


def test_submit_kline_bars_stored_check_is_mandatory() -> None:
    import inspect

    param = inspect.signature(submit_kline_bars).parameters["stored_higher"]
    assert param.default is inspect.Parameter.empty


async def test_stored_tape_lookup_decodes_datetime_rows_and_binds_datetime() -> None:
    """#2170: a real QuestDB returns `ts` as datetime and rejects int binds."""
    from datetime import datetime

    from candleviewer.bars.kline_rows import stored_tape_lookup
    from candleviewer.domain.sql_names import ts_param

    seen: list[tuple[object, ...]] = []

    class _Conn:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            seen.append(params)
            return [{"ts": ts_param(1_700_000_000_000_001)}, {"ts": ts_param(5)}]

    got = await stored_tape_lookup(_Conn())(  # type: ignore[arg-type]
        "BTCUSDT", "time:1m", [1_700_000_000_000_001, 1_700_000_000_000_002]
    )
    assert got == {1_700_000_000_000_001}
    assert all(isinstance(p, datetime) for p in seen[0][2:])
