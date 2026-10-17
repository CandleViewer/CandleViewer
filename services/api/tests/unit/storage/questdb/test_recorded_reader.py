"""`QuestDbRecordedReader` (E26-T02): the hot tier behind the recorded-event interface."""

from __future__ import annotations

import asyncio
import inspect
import re
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import asyncpg
import pytest

from candleviewer.domain.sql_names import ts_param
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.natural_keys import TABLE_BY_STREAM
from candleviewer.storage.questdb import recorded_reader
from candleviewer.storage.questdb.recorded_reader import (
    ANCHOR_ROWS,
    ANCHOR_SQL,
    MAX_READ_ROWS,
    RANGE_SQL,
    HotReplayReadError,
    QuestDbRecordedReader,
    build_read_recorded,
    build_snapshot_anchor,
)
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.recorded import (
    BOOK_STREAMS,
    REPLAYABLE_STREAMS,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedQueryRejected,
    RecordedStreamReader,
    RecordedTrade,
    event_from_row,
)

RNG = TimeRange(start_us=1_000, end_us=2_000)
NAIVE = datetime(1970, 1, 1) + timedelta(microseconds=1_500)  # PGWire TIMESTAMP shape


class FakePgWire:
    """`RecordFetcher` double recording every query."""

    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_records(self, sql: str, *params: object) -> list[Mapping[str, object]]:
        self.calls.append((sql, params))
        return list(self.rows)


class StuckPgWire(FakePgWire):
    async def fetch_records(self, sql: str, *params: object) -> list[Mapping[str, object]]:
        await asyncio.Event().wait()  # never answers
        return []


class FailingPgWire(FakePgWire):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def fetch_records(self, sql: str, *params: object) -> list[Mapping[str, object]]:
        raise self.error


def _snapshot_row(update_id: int, *, epoch_id: int | None = None) -> dict[str, object]:
    return {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "depth": 200,
        "epoch_id": epoch_id,
        "update_id": update_id,
        "cross_seq": None,
        "bids": '[["65000.0","1.5"]]',
        "asks": '[["65000.5","2"]]',
    }


@pytest.mark.parametrize("stream", REPLAYABLE_STREAMS)
def test_every_range_query_passes_the_hot_tier_query_lint(stream: StreamKind) -> None:
    """21 Sec.13.2: symbol equality, two-sided ts bound, ORDER BY the designated ts only."""
    qb = build_read_recorded("BTCUSDT", stream, RNG, depth=200, limit=10)

    assert "symbol = $1" in qb.sql and "ts >= $2" in qb.sql and "ts < $3" in qb.sql
    assert re.findall(r"ORDER BY\s+(\w+)", qb.sql) == ["ts"]
    assert qb.sql.endswith("LIMIT 10")
    assert qb.params[:3] == ("BTCUSDT", ts_param(1_000), ts_param(2_000))
    assert "BTCUSDT" not in qb.sql


@pytest.mark.parametrize("stream", REPLAYABLE_STREAMS)
def test_only_book_streams_are_filtered_by_depth(stream: StreamKind) -> None:
    qb = build_read_recorded("BTCUSDT", stream, RNG, depth=50, limit=10)

    if stream in BOOK_STREAMS:
        assert "depth = $4" in qb.sql and qb.params[3] == 50
    else:
        assert "depth" not in qb.sql and len(qb.params) == 3


def test_every_recorded_stream_reads_its_allowlisted_table() -> None:
    assert set(RANGE_SQL) == set(REPLAYABLE_STREAMS)
    for stream in REPLAYABLE_STREAMS:
        assert f"FROM {TABLE_BY_STREAM[stream]} WHERE" in RANGE_SQL[stream]


@pytest.mark.parametrize(
    ("symbol", "stream", "limit"),
    [
        ("BTC'; DROP TABLE trades", StreamKind.TRADES, 10),
        ("BTCUSDT", StreamKind.BARS, 10),  # derived data is not a recorded table
        ("BTCUSDT", StreamKind.TRADES, 0),
        ("BTCUSDT", StreamKind.TRADES, True),
        ("BTCUSDT", StreamKind.TRADES, MAX_READ_ROWS + 1),
    ],
)
def test_unusable_reads_are_refused_before_any_sql(
    symbol: str, stream: StreamKind, limit: int
) -> None:
    with pytest.raises(RecordedQueryRejected):
        build_read_recorded(symbol, stream, RNG, depth=200, limit=limit)


def test_the_anchor_query_is_bounded_on_both_sides() -> None:
    qb = build_snapshot_anchor("BTCUSDT", 200, 5_000, 1_000)

    assert qb.sql == ANCHOR_SQL
    assert f"ts >= $3 AND ts <= $4 ORDER BY ts DESC LIMIT {ANCHOR_ROWS}" in qb.sql
    assert qb.params == ("BTCUSDT", 200, ts_param(1_000), ts_param(5_000))
    with pytest.raises(RecordedQueryRejected):
        build_snapshot_anchor("not a symbol", 200, 5_000, 1_000)


async def test_rows_come_back_as_recorded_events_with_exact_decimals() -> None:
    row: dict[str, object] = {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "side": "buy",
        "price": 65000.5,
        "size": 0.001,
        "trade_id": "t1",
        "seq": 3,
    }
    conn = FakePgWire([row])

    got = await QuestDbRecordedReader(conn).read(
        "BTCUSDT", StreamKind.TRADES, RNG, depth=200, limit=5
    )

    assert [(e.ts_us, e.seq, e.tiebreak) for e in got] == [(1_500, 3, ("t1",))]
    assert isinstance(got[0].payload, RecordedTrade)
    assert str(got[0].payload.price) == "65000.5"
    expected = build_read_recorded("BTCUSDT", StreamKind.TRADES, RNG, depth=200, limit=5)
    assert conn.calls == [(expected.sql, expected.params)]


async def test_snapshot_at_maps_the_one_row_or_returns_none() -> None:
    row: dict[str, object] = {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "depth": 200,
        "update_id": 7,
        "cross_seq": 70,
        "bids": '[["65000.0","1.5"]]',
        "asks": '[["65000.5","2"]]',
    }

    found = await QuestDbRecordedReader(FakePgWire([row])).snapshot_at(
        "BTCUSDT", 200, 2_000, not_before_us=0
    )
    missing = await QuestDbRecordedReader(FakePgWire()).snapshot_at(
        "BTCUSDT", 200, 2_000, not_before_us=0
    )

    assert found is not None and isinstance(found.payload, RecordedBookSnapshot)
    assert found.seq == 70
    assert missing is None


async def test_a_fetch_that_never_answers_times_out() -> None:
    reader = QuestDbRecordedReader(StuckPgWire(), timeout_s=0.01)

    with pytest.raises(TimeoutError):
        await reader.read("BTCUSDT", StreamKind.TRADES, RNG, depth=200, limit=5)


def test_the_reader_is_addressed_by_stream_id_never_by_path() -> None:
    """SR-097 / ticket AC 5: no public parameter of the hot reader is a filesystem path."""
    assert isinstance(QuestDbRecordedReader(FakePgWire()), RecordedStreamReader)
    for member in (
        QuestDbRecordedReader.__init__,
        QuestDbRecordedReader.read,
        QuestDbRecordedReader.snapshot_at,
    ):
        for name, param in inspect.signature(member).parameters.items():
            assert "path" not in name and "path" not in str(param.annotation).lower()


async def test_snapshots_sharing_the_latest_instant_resolve_by_the_order_key() -> None:
    """Same row whichever tier answers (24 Sec.13.7): never the storage order of a tie."""
    rows = [_snapshot_row(3, epoch_id=1), _snapshot_row(9, epoch_id=2), _snapshot_row(5)]

    found = await QuestDbRecordedReader(FakePgWire(rows)).snapshot_at(
        "BTCUSDT", 200, 2_000, not_before_us=0
    )

    assert found is not None and found.seq == 9


async def test_an_anchor_tie_wider_than_the_lookup_is_refused_not_guessed() -> None:
    rows = [_snapshot_row(i, epoch_id=i) for i in range(ANCHOR_ROWS)]

    with pytest.raises(HotReplayReadError):
        await QuestDbRecordedReader(FakePgWire(rows)).snapshot_at(
            "BTCUSDT", 200, 2_000, not_before_us=0
        )


async def test_rows_are_mapped_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.17: a read's row cap of mapping never runs on the loop thread."""
    threads: list[int] = []

    def tracked(stream: StreamKind, row: Mapping[str, object]) -> RecordedEvent:
        threads.append(threading.get_ident())
        return event_from_row(stream, row)

    monkeypatch.setattr(recorded_reader, "event_from_row", tracked)
    row = {"ts": NAIVE, "symbol": "BTCUSDT", "side": "buy", "price": 1.0, "size": 1.0}
    conn = FakePgWire([row | {"trade_id": f"t{i}", "seq": i} for i in range(3)])

    await QuestDbRecordedReader(conn).read("BTCUSDT", StreamKind.TRADES, RNG, depth=200, limit=5)

    assert threads and threading.get_ident() not in threads


class _Records:
    """An asyncpg-shaped connection whose rows must come back uncopied."""

    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        self.rows = rows

    async def fetch(self, sql: str, *params: object) -> Sequence[Mapping[str, object]]:
        return self.rows

    async def close(self) -> None:
        return None


async def test_lazy_pgwire_hands_the_driver_records_over_without_a_dict_copy() -> None:
    record: Mapping[str, object] = {"n": 1}
    conn = _Records([record])

    async def connect(**_: object) -> _Records:
        return conn

    wire = LazyPgWire("h", 1, "u", "p", connect=connect)

    (got,) = await wire.fetch_records("SELECT 1")

    assert got is record
    assert await wire.fetch("SELECT 1") == [{"n": 1}]
    await wire.close()


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("questdb pg-wire in reconnect backoff"),
        asyncpg.InterfaceError("connection is closed"),
    ],
)
async def test_driver_failures_become_a_typed_hot_read_error(error: Exception) -> None:
    """Chaos scenario 10: a datastore outage reaches the replay as one typed storage error."""
    with pytest.raises(HotReplayReadError):
        await QuestDbRecordedReader(FailingPgWire(error)).read(
            "BTCUSDT", StreamKind.TRADES, RNG, depth=200, limit=5
        )
