"""E16-FR-03 (#1739): the hot-tier presence reader against a real QuestDB (docker required).

The E16 `StreamWriter` writes recorded events through ILP, exactly as recording does. The
`QuestDbStoredPresence` then reads them back over PGWire: its `SAMPLE BY 1m ALIGN TO CALENDAR`
statements and its `GROUP BY` update-id read must be accepted by the real engine, the minutes
that hold rows must come back per reconciled stream (a minute with none stays absent, and another
symbol's rows never fill it), and a book update-id discontinuity must surface as a break.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import asyncpg
import pytest

from candleviewer.recorder.writer import STREAMS, StreamWriter, WriterConfig
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.questdb.stored_presence import BUCKET_US, QuestDbStoredPresence
from tests.integration.storage import test_questdb_hot_tier as hot_tier
from tests.unit.recorder._writer_helpers import (
    OPEN_GATE,
    T0,
    FakeClock,
    FakeEvents,
    FakeStore,
    delta,
    ticker,
    trade,
)

pytestmark = pytest.mark.integration

#: The QuestDB container fixture the hot-tier suite already maintains.
questdb_container = hot_tier.questdb_container

M = BUCKET_US
#: The first calendar minute at or after `T0`: the helpers stamp `T0 + offset`.
BASE = T0 + (-T0 % M)
OFF = BASE - T0
S = 1_000_000
LO, HI = BASE, BASE + 4 * M
#: Book updates, as `T0 + update_id` stamps them: minute 0, then minute 1 (it follows), then
#: minute 3 with a `prev_update_id` that does not (a break from the second to the third).
U1, U2, U3 = OFF + S, OFF + M + 2 * S, OFF + 3 * M + S


class _Records:
    """`RecordFetcher` over a raw asyncpg connection: the driver's own records, uncopied, as
    `LazyPgWire.fetch_records` returns them, so the reader is proven on real `Record`s."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def fetch_records(self, sql: str, *params: object) -> list[Mapping[str, object]]:
        return cast(list[Mapping[str, object]], await self._conn.fetch(sql, *params))


async def _seed(host: str, ilp_port: int, wal_dir: Path) -> None:
    sinks = {
        s: IlpWriter(hot_tier._AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS) for s in STREAMS
    }
    for sink in sinks.values():
        await sink.start()
    try:
        clock = FakeClock()
        writer = StreamWriter(
            sinks.__getitem__,
            FakeStore(),
            FakeEvents(),
            WriterConfig(wal_dir=wal_dir, env="live"),
            clock=clock,
            wall_clock_us=lambda: 0,
            disk_gate=OPEN_GATE,
        )
        await writer.open()
        writer.seed(["BTCUSDT", "ETHUSDT"])
        # Trades in minutes 0 and 2; another symbol's trade in minute 1 must not fill BTC's.
        await writer.on_trade(trade(1, ts=BASE + S))
        await writer.on_trade(trade(2, ts=BASE + 2 * M + 5 * S))
        await writer.on_trade(trade(3, symbol="ETHUSDT", ts=BASE + M + S))
        await writer.on_trade(trade(4, ts=HI))  # on the window's end: never read
        await writer.on_book_delta(delta(U1))
        await writer.on_book_delta(delta(U2, prev=U1))
        await writer.on_book_delta(delta(U3, prev=U2 + 5))
        await writer.on_ticker(ticker(OFF + 30 * S))  # minute 0 only
        clock.advance(0.2)
        for stream in STREAMS:
            await writer.pump(stream)
    finally:
        for sink in sinks.values():
            await sink.stop()


@pytest.mark.asyncio
async def test_stored_presence_reads_the_minutes_and_breaks_real_questdb_holds(
    questdb_container: tuple[str, int, int],
    tmp_path: Path,
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await hot_tier._connect(host, pg_port)
    try:
        await run_migrations(hot_tier._AsyncpgExecutor(conn), hot_tier.DDL_DIR)
        await _seed(host, ilp_port, tmp_path / "wal")
        for table, n in {"trades": 4, "orderbook_deltas": 6, "tickers": 1}.items():
            await hot_tier.wait_for_row_count(conn, table, n)

        reader = QuestDbStoredPresence(_Records(conn))
        # Minutes 1 and 3 hold no BTC trade (ETH's minute-1 trade and the trade on `HI` aside).
        assert await reader.stored_spans("BTCUSDT", "trades", LO, HI) == [
            (BASE, BASE + M),
            (BASE + 2 * M, BASE + 3 * M),
        ]
        # Adjacent minutes 0 and 1 merge; minute 2 holds no book update.
        assert await reader.stored_spans("BTCUSDT", "orderbook_delta", LO, HI) == [
            (BASE, BASE + 2 * M),
            (BASE + 3 * M, HI),
        ]
        assert await reader.stored_spans("BTCUSDT", "tickers", LO, HI) == [(BASE, BASE + M)]
        # A window inside an empty span reads nothing; a bucket is clipped to the window.
        assert await reader.stored_spans("BTCUSDT", "tickers", BASE + M, HI) == []
        assert await reader.stored_spans("ETHUSDT", "trades", BASE + M + S, HI) == [
            (BASE + M + S, BASE + 2 * M)
        ]

        # Per depth, the third update does not follow the second: the span between them.
        assert await reader.seq_breaks("BTCUSDT", LO, HI) == [(BASE + M + 2 * S, BASE + 3 * M + S)]
        assert await reader.seq_breaks("BTCUSDT", LO, BASE + 3 * M) == []
        assert await reader.seq_breaks("ETHUSDT", LO, HI) == []
    finally:
        await conn.close()
