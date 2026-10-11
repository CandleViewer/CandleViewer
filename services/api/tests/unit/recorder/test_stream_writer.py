"""E16-T03 StreamWriter: batching, per-stream isolation, row shapes and the effective set."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.writer import (
    STREAMS,
    RecorderWalVolumeError,
    StreamWriter,
    WriterConfig,
    check_wal_volume,
)
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from tests.unit.recorder._writer_helpers import (
    T0,
    FakeEvents,
    FakeSink,
    FakeStore,
    delta,
    liquidation,
    make_writer,
    snapshot,
    ticker,
    trade,
)

DDL_DIR = Path(__file__).resolve().parents[5] / "backend" / "db" / "questdb"


def _ddl_symbol_columns(table: str) -> set[str]:
    """SYMBOL columns from the DDL (#2199 `TableDef.symbol_columns`, ALTERs folded in)."""
    return set({t.name: t for t in parse_ddl_dir(DDL_DIR)}[table].symbol_columns)


def _changed(symbol: str, change: str) -> RecorderSetChanged:
    return RecorderSetChanged.model_validate(
        {
            "symbol": symbol,
            "change": change,
            "reason": "manual",
            "reasons": ("manual",) if change != "removed" else (),
            "priority": 300,
            "auto_evictable": False,
            "ts_event": T0,
        }
    )


async def test_flush_exactly_at_10000_rows_without_waiting(tmp_path: Path) -> None:
    w, sink, *_ = await make_writer(tmp_path)
    for i in range(9_999):
        await w.on_trade(trade(i))
    await w.pump("trades")
    assert sink.rows("trades") == []
    await w.on_trade(trade(9_999))
    await w.pump("trades")
    assert len(sink.rows("trades")) == 10_000
    assert w.backlog_rows == 0


async def test_flush_exactly_at_200ms_with_one_row(tmp_path: Path) -> None:
    w, sink, _, _, clock = await make_writer(tmp_path)
    await w.on_trade(trade(1))
    clock.advance(0.199)
    await w.pump("trades")
    assert sink.rows("trades") == []
    clock.advance(0.001)
    await w.pump("trades")
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t1"]


async def test_batch_is_capped_at_flush_rows(tmp_path: Path) -> None:
    w, sink, *_ = await make_writer(tmp_path)
    for i in range(10_005):
        await w.on_trade(trade(i))
    await w.pump("trades")
    assert len(sink.rows("trades")) == 10_000
    assert w.backlog_rows == 5


async def test_slow_stream_does_not_delay_trades(tmp_path: Path) -> None:
    """Scenario: orderbook_deltas writes delayed by 2 s; trades keep their 200 ms cadence."""
    w, sink, _, _, clock = await make_writer(tmp_path, write_timeout_s=30.0)
    release = asyncio.Event()
    original = sink.write_rows

    async def slow(table: str, rows: list[dict[str, object]], key: str) -> None:
        if table == "orderbook_deltas":
            await release.wait()  # stands in for the 2 s stall
        await original(table, rows, key)

    sink.write_rows = slow  # type: ignore[method-assign]
    await w.on_book_delta(delta(1))
    await w.on_trade(trade(1))
    clock.advance(0.2)
    stalled = asyncio.create_task(w.pump("orderbook_deltas"))
    await asyncio.sleep(0)
    await w.pump("trades")
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t1"]
    assert not stalled.done()
    release.set()
    await stalled
    assert len(sink.rows("orderbook_deltas")) == 2


async def test_unrecorded_symbol_is_ignored(tmp_path: Path) -> None:
    w, *_ = await make_writer(tmp_path)
    await w.on_trade(trade(1, symbol="ETHUSDT"))
    assert w.backlog_rows == 0


async def test_set_changed_subscribes_and_unsubscribes(tmp_path: Path) -> None:
    w, *_ = await make_writer(tmp_path)
    w.on_set_changed(_changed("ETHUSDT", "added"))
    await w.on_trade(trade(1, symbol="ETHUSDT"))
    assert w.backlog_rows == 1 and w.is_recording("ETHUSDT")
    w.on_set_changed(_changed("ETHUSDT", "reason_changed"))
    assert w.is_recording("ETHUSDT")
    w.on_set_changed(_changed("ETHUSDT", "removed"))
    await w.on_trade(trade(2, symbol="ETHUSDT"))
    assert w.backlog_rows == 1 and not w.is_recording("ETHUSDT")


async def test_every_stream_routes_to_its_table(tmp_path: Path) -> None:
    w, sink, _, _, clock = await make_writer(tmp_path)
    await w.on_trade(trade(1))
    await w.on_book_delta(delta(5))
    await w.on_book_snapshot(snapshot(4))
    await w.on_ticker(ticker(1))
    await w.on_liquidation(liquidation(1))
    clock.advance(0.2)
    for s in STREAMS:
        await w.pump(s)
    assert {t: len(sink.rows(t)) for t in STREAMS} == {
        "trades": 1,
        "orderbook_deltas": 2,
        "orderbook_snapshots": 1,
        "tickers": 1,
        "liquidations": 1,
    }
    liq = sink.rows("liquidations")[0]
    assert liq["side"] == "sell" and liq["stream"] == "all"
    deltas = sink.rows("orderbook_deltas")
    assert [(d["side"], d["action"]) for d in deltas] == [("bid", "update"), ("ask", "delete")]


async def test_prices_are_exact_decimal_text(tmp_path: Path) -> None:
    w, sink, _, _, clock = await make_writer(tmp_path)
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    row = sink.rows("trades")[0]
    assert row["price"] == "65000.5" and row["notional"] == "65.0005"


async def test_rows_serialize_every_ddl_column_and_symbols_as_tags(tmp_path: Path) -> None:
    """#2198/#2199 parity: every SYMBOL column is a tag; no row key is a non-DDL column."""
    w, sink, _, _, clock = await make_writer(tmp_path)
    await w.on_trade(trade(1))
    await w.on_book_delta(delta(5))
    await w.on_book_snapshot(snapshot(4))
    await w.on_ticker(ticker(1))
    await w.on_liquidation(liquidation(1))
    clock.advance(0.2)
    for s in STREAMS:
        await w.pump(s)
    ddl = {t.name: t for t in parse_ddl_dir(DDL_DIR)}
    for table in STREAMS:
        schema = ALL_SCHEMAS[table]
        assert _ddl_symbol_columns(table) == set(schema.tag_columns), table
        for row in sink.rows(table):
            assert set(row) <= set(ddl[table].columns), (table, set(row) - set(ddl[table].columns))
            body = {k: v for k, v in row.items() if k != "ts"}
            line = serialize_ilp_line(schema, body, int(str(row["ts"])))
            head, fields, _ = line.rsplit(" ", 2)
            for col in _ddl_symbol_columns(table):
                if col in row:
                    assert f",{col}=" in head and not fields.startswith(f"{col}="), (table, col)
                    assert f",{col}=" not in f",{fields}", (table, col)


async def test_delta_seq_jump_is_observed_not_healed(tmp_path: Path) -> None:
    w, *_ = await make_writer(tmp_path)
    await w.on_book_delta(delta(5))
    await w.on_book_delta(delta(9, prev=7))
    assert list(w.seq_jumps) == [("BTCUSDT", 5, 7)]
    assert w.backlog_rows == 4  # still recorded


async def test_seq_jump_windows_and_event_bounds_are_drained_for_sessions(
    tmp_path: Path,
) -> None:
    """E16-T04 signal: the jump window is (last delta ts, jumped delta ts); bounds feed the
    session's first/last_event_ts. Both drain on take."""
    w, *_ = await make_writer(tmp_path)
    await w.on_book_delta(delta(5))
    await w.on_book_delta(delta(9, prev=7))
    await w.on_trade(trade(1))
    await w.on_trade(trade(0))
    assert w.take_seq_jump_windows() == [("BTCUSDT", T0 + 5, T0 + 9)]
    assert w.take_seq_jump_windows() == []
    assert w.take_event_bounds() == {"BTCUSDT": (T0, T0 + 9)}
    assert w.take_event_bounds() == {}
    w.on_set_changed(
        RecorderSetChanged(symbol="BTCUSDT", change="removed", reason="manual", reasons=(),
                           priority=300, auto_evictable=False, ts_event=0)
    )  # fmt: skip
    w.on_set_changed(
        RecorderSetChanged(symbol="BTCUSDT", change="added", reason="manual", reasons=(),
                           priority=300, auto_evictable=False, ts_event=0)
    )  # fmt: skip
    await w.on_book_delta(delta(20, prev=17))  # re-add: no stale jump
    assert w.take_seq_jump_windows() == []


async def test_counters_written_every_10s_as_deltas(tmp_path: Path) -> None:
    w, _, store, _, clock = await make_writer(tmp_path)
    await w.start()
    try:
        await w.on_trade(trade(1))
        await w.on_trade(trade(2))
        w.note_reconnect("BTCUSDT")
        clock.advance(0.2)
        await w.pump("trades")
        clock.advance(9.0)
        await w.tick()
        assert store.counters == []
        clock.advance(1.0)
        await w.tick()
        ((symbol, kw),) = store.counters
        assert symbol == "BTCUSDT"
        assert kw["messages_received"] == 2 and kw["messages_dropped"] == 0
        assert kw["reconnect_count"] == 1 and kw["bytes_written"] > 0
        clock.advance(10.0)
        await w.tick()
        assert len(store.counters) == 1  # nothing new: no zero-delta write
    finally:
        await w.stop()


async def test_counters_retained_when_store_fails(tmp_path: Path) -> None:
    w, _, store, _, _ = await make_writer(tmp_path)
    await w.on_trade(trade(1))
    store.fail = True
    await w.flush_counters()
    store.fail = False
    await w.flush_counters()
    assert store.counters[0][1]["messages_received"] == 1


async def test_start_and_stop_drain_the_queue(tmp_path: Path) -> None:
    w, sink, *_ = await make_writer(tmp_path)
    await w.start()
    await w.on_trade(trade(1))
    await w.stop()
    assert len(sink.rows("trades")) == 1


def test_wal_volume_check_refuses_shared_device(tmp_path: Path) -> None:
    with pytest.raises(RecorderWalVolumeError):
        check_wal_volume(tmp_path / "wal", [tmp_path])
    check_wal_volume(tmp_path / "wal", [tmp_path / "missing"])


async def test_open_refuses_wal_on_the_protected_volume(tmp_path: Path) -> None:
    """SR-096 at start-up: `open()` (called by `start()`) refuses a shared volume."""
    with pytest.raises(RecorderWalVolumeError):
        await make_writer(tmp_path, protected_paths=(tmp_path,))


async def test_open_passes_when_protected_paths_are_elsewhere(tmp_path: Path) -> None:
    w, *_ = await make_writer(tmp_path, protected_paths=(tmp_path / "not-mounted",))
    assert w.spill_bytes == 0


async def test_liquidation_rows_carry_batch_index_for_dedup(tmp_path: Path) -> None:
    """Two prints in one batch with equal side/price/size stay distinct (QuestDB 0005 key)."""
    w, sink, _, _, clock = await make_writer(tmp_path)
    await w.on_liquidation(liquidation(0))
    await w.on_liquidation(liquidation(1).model_copy(update={"ts_event": T0}))
    clock.advance(0.2)
    await w.pump("liquidations")
    rows = sink.rows("liquidations")
    assert [r["batch_index"] for r in rows] == [0, 1] and rows[0]["ts"] == rows[1]["ts"]
    ddl = {t.name: t for t in parse_ddl_dir(DDL_DIR)}["liquidations"]
    assert "batch_index" in ddl.dedup_keys


async def test_remove_clears_stale_update_id(tmp_path: Path) -> None:
    w, *_ = await make_writer(tmp_path)
    await w.on_book_delta(delta(5))
    w.on_set_changed(_changed("BTCUSDT", "removed"))
    w.on_set_changed(_changed("BTCUSDT", "added"))
    await w.on_book_delta(delta(50))
    assert list(w.seq_jumps) == []


def test_writer_config_defaults_match_the_ticket(tmp_path: Path) -> None:
    cfg = WriterConfig(wal_dir=tmp_path)
    assert (cfg.flush_rows, cfg.flush_interval_s, cfg.wal_max_bytes) == (10_000, 0.2, 1 << 30)
    assert cfg.counters_interval_s == 10.0
    assert StreamWriter.__name__ == "StreamWriter"


def test_default_protected_paths_derive_from_settings(tmp_path: Path) -> None:
    from candleviewer.recorder.writer import writer_config_from_settings
    from candleviewer.settings import Settings

    s = Settings(parquet_root=str(tmp_path / "parquet"))
    cfg = writer_config_from_settings(s)
    assert Path(s.parquet_root) in cfg.protected_paths
    assert cfg.wal_dir == Path(s.recorder_wal_dir)
    assert cfg.wal_max_bytes == s.recorder_wal_max_bytes


async def test_wal_on_the_parquet_volume_is_refused_with_defaults(tmp_path: Path) -> None:
    from candleviewer.recorder.writer import writer_config_from_settings
    from candleviewer.settings import Settings

    (tmp_path / "parquet").mkdir()
    s = Settings(parquet_root=str(tmp_path / "parquet"))
    cfg = writer_config_from_settings(s)
    w = StreamWriter(
        lambda _s: FakeSink(),
        FakeStore(),
        FakeEvents(),
        cfg,
        clock=lambda: 0.0,
        wall_clock_us=lambda: T0,
    )
    with pytest.raises(RecorderWalVolumeError):
        await w.open()
