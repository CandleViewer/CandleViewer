"""E16-T03: StreamWriter write-through to a real QuestDB for each of the five raw tables.

Fakes hide ILP rejections (#2198): a SYMBOL column sent as a field, or a type mismatch, makes
QuestDB reject the line while the TCP write "succeeds". So each table asserts the rows landed
*and* `wal_tables()` shows `sequencerTxn > 0` with an empty `errorTag`. Docker required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.recorder.writer import STREAMS, StreamWriter, WriterConfig
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from tests.integration.storage.test_questdb_hot_tier import (
    DDL_DIR,
    _AsyncpgExecutor,
    _AsyncpgTcpIlpTransport,
    _connect,
    questdb_container,  # noqa: F401 - pytest fixture
    wait_for_row_count,
)
from tests.unit.recorder._writer_helpers import (
    OPEN_GATE,
    T0,
    FakeClock,
    FakeEvents,
    FakeStore,
    delta,
    liquidation,
    snapshot,
    ticker,
    trade,
)

pytestmark = pytest.mark.integration

_EXPECTED = {
    "trades": 2,
    "orderbook_deltas": 2,
    "orderbook_snapshots": 1,
    "tickers": 1,
    "liquidations": 2,
}


@pytest.mark.asyncio
async def test_stream_writer_rows_commit_on_real_questdb(
    questdb_container: tuple[str, int, int],  # noqa: F811
    tmp_path: Path,
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        sinks = {
            s: IlpWriter(_AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS) for s in STREAMS
        }
        for sink in sinks.values():
            await sink.start()
        clock = FakeClock()
        writer = StreamWriter(
            sinks.__getitem__,
            FakeStore(),
            FakeEvents(),
            WriterConfig(wal_dir=tmp_path / "wal"),
            clock=clock,
            wall_clock_us=lambda: 0,
            disk_gate=OPEN_GATE,
        )
        await writer.open()
        writer.seed(["BTCUSDT"])
        await writer.on_trade(trade(1))
        await writer.on_trade(trade(2))
        await writer.on_book_delta(delta(5))
        await writer.on_book_snapshot(snapshot(4))
        await writer.on_ticker(ticker(1))
        await writer.on_liquidation(liquidation(1))
        # Same ts/side/price/size, next batch_index: a distinct print (QuestDB 0005 key).
        await writer.on_liquidation(liquidation(2).model_copy(update={"ts_event": T0 + 1}))
        clock.advance(0.2)
        for stream in STREAMS:
            await writer.pump(stream)
        for sink in sinks.values():
            await sink.stop()
        for table, n in _EXPECTED.items():
            await wait_for_row_count(conn, table, n)
            rows = await conn.fetch("SELECT * FROM wal_tables() WHERE name = $1", table)
            wal = dict(rows[0])
            assert int(wal["sequencerTxn"]) > 0, table
            assert wal.get("errorTag") in ("", None), (table, wal.get("errorTag"))
        assert writer.spill_bytes == 0
    finally:
        await conn.close()
