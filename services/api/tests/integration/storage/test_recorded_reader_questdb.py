"""E26-T02: the hot-tier recorded reader against a real QuestDB (docker required).

The E16 `StreamWriter` writes recorded events through ILP, exactly as recording does. The
`QuestDbRecordedReader` reads them back over PGWire, and they must equal `event_from_row` of the
recorder's own rows (DOUBLE round trip included). A `ReplaySource` on the `questdb` tier then
replays them in the §13.7 order.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import asyncpg
import pytest

from candleviewer.recorder.writer import (
    STREAMS,
    StreamWriter,
    WriterConfig,
    delta_records,
    snapshot_records,
    trade_records,
)
from candleviewer.replay import ReplayRequest, ReplaySource, ReplayTiers
from candleviewer.replay.merge import SEQUENCE_DOMAIN, STREAM_ORDINAL
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.recorded_reader import QuestDbRecordedReader
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.repositories.recorded import RecordedEvent, event_from_row
from candleviewer.storage.testing import StaticGapReader, StaticManifestCoverage
from tests.integration.storage import test_questdb_hot_tier as hot_tier
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

#: The QuestDB container fixture the hot-tier suite already maintains.
questdb_container = hot_tier.questdb_container

WINDOW = TimeRange(start_us=T0, end_us=T0 + 1_000)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class _Records:
    """`RecordFetcher` over a raw asyncpg connection: the driver's own records, uncopied, as
    `LazyPgWire.fetch_records` returns them, so the mapping is proven on real `Record`s."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def fetch_records(self, sql: str, *params: object) -> list[Mapping[str, object]]:
        return cast(list[Mapping[str, object]], await self._conn.fetch(sql, *params))


def _by_key(events: list[RecordedEvent]) -> list[RecordedEvent]:
    return sorted(events, key=lambda e: (e.ts_us, e.seq, e.tiebreak))


@pytest.mark.asyncio
async def test_recorded_rows_read_back_as_the_events_the_recorder_wrote(
    questdb_container: tuple[str, int, int],
    tmp_path: Path,
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await hot_tier._connect(host, pg_port)
    try:
        await run_migrations(hot_tier._AsyncpgExecutor(conn), hot_tier.DDL_DIR)
        sinks = {
            s: IlpWriter(hot_tier._AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
            for s in STREAMS
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
        trades, book_delta, book_snapshot = [trade(1), trade(2)], delta(5), snapshot(4)
        for ev in trades:
            await writer.on_trade(ev)
        await writer.on_book_delta(book_delta)
        await writer.on_book_snapshot(book_snapshot)
        await writer.on_ticker(ticker(1))
        await writer.on_liquidation(liquidation(1))
        clock.advance(0.2)
        for stream in STREAMS:
            await writer.pump(stream)
        for sink in sinks.values():
            await sink.stop()
        expected_rows = {
            "trades": 2,
            "orderbook_deltas": 2,
            "orderbook_snapshots": 1,
            "tickers": 1,
            "liquidations": 1,
        }
        for table, n in expected_rows.items():
            await hot_tier.wait_for_row_count(conn, table, n)

        reader = QuestDbRecordedReader(_Records(conn))
        got_trades = await reader.read("BTCUSDT", StreamKind.TRADES, WINDOW, depth=200, limit=100)
        got_deltas = await reader.read(
            "BTCUSDT", StreamKind.ORDERBOOK_DELTA, WINDOW, depth=200, limit=100
        )
        other_depth = await reader.read(
            "BTCUSDT", StreamKind.ORDERBOOK_DELTA, WINDOW, depth=50, limit=100
        )
        anchor = await reader.snapshot_at("BTCUSDT", 200, T0 + 10, not_before_us=T0)

        want_trades = [
            event_from_row(StreamKind.TRADES, r.row) for ev in trades for r in trade_records(ev)
        ]
        want_deltas = [
            event_from_row(StreamKind.ORDERBOOK_DELTA, r.row) for r in delta_records(book_delta)
        ]
        (snap_row,) = snapshot_records(book_snapshot)
        assert _by_key(got_trades) == _by_key(want_trades)
        assert _by_key(got_deltas) == _by_key(want_deltas)
        assert other_depth == []
        assert anchor == event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, snap_row.row)

        request = ReplayRequest.model_validate(
            {
                "symbols": ("BTCUSDT",),
                "streams": (
                    StreamKind.TRADES,
                    StreamKind.ORDERBOOK_DELTA,
                    StreamKind.ORDERBOOK_SNAPSHOT,
                    StreamKind.TICKERS,
                    StreamKind.LIQUIDATIONS,
                ),
                "start": EPOCH + timedelta(microseconds=WINDOW.start_us),
                "end": EPOCH + timedelta(microseconds=WINDOW.end_us),
                "source_tier": "questdb",
            }
        )
        tiers = ReplayTiers(
            hot=reader, cold=reader, coverage=StaticManifestCoverage(), gaps=StaticGapReader()
        )
        async with ReplaySource(request, tiers) as source:
            replayed = [item async for item in source]

        assert len(replayed) == sum(expected_rows.values())
        # The merge's order for one symbol (24 Sec.13.7): `seq` compares only inside a sequence
        # domain, and a trade, a ticker and a liquidation share an instant here.
        order = [
            (e.ts_us, SEQUENCE_DOMAIN[e.stream], e.seq, STREAM_ORDINAL[e.stream], e.tiebreak)
            for e in replayed
            if isinstance(e, RecordedEvent)
        ]
        assert order == sorted(order)
    finally:
        await conn.close()
