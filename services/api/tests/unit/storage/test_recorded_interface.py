"""The recorded-event read interface and its in-memory fakes (E26-T02).

The fakes are the public test surface the replay module (and later E26 tickets) code against,
so their semantics must match the real tiers': half-open ranges, the book-depth filter, the
row `limit` and the bounded anchor lookup.
"""

from __future__ import annotations

import inspect
import re
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    STREAM_BY_DB_KIND,
    ArchiveCoverage,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedGap,
    RecordedStreamReader,
    RecordedTrade,
    RecordingGapReader,
    covered_parts,
)
from candleviewer.storage.testing import (
    InMemoryRecordedTier,
    StaticArchiveCoverage,
    StaticGapReader,
)

SYM = "BTCUSDT"
SCHEMA_DOC = Path(__file__).resolve().parents[5] / "docs" / "plan" / "21-database-schema.md"


def _trade(ts_us: int, trade_id: str = "t", symbol: str = SYM) -> RecordedEvent:
    payload = RecordedTrade("buy", Decimal(1), Decimal(1), trade_id, None)
    return RecordedEvent(ts_us, 0, symbol, StreamKind.TRADES, (trade_id,), payload)


def _delta(ts_us: int, depth: int) -> RecordedEvent:
    payload = RecordedBookDelta(depth, "bid", Decimal(1), Decimal(1), ts_us, None)
    return RecordedEvent(ts_us, ts_us, SYM, StreamKind.ORDERBOOK_DELTA, (ts_us,), payload)


def _snapshot(ts_us: int, depth: int, update_id: int | None = None) -> RecordedEvent:
    uid = ts_us if update_id is None else update_id
    payload = RecordedBookSnapshot(depth, uid, None, (), ())
    return RecordedEvent(ts_us, uid, SYM, StreamKind.ORDERBOOK_SNAPSHOT, (uid,), payload)


def test_fakes_satisfy_the_reader_protocols() -> None:
    assert isinstance(InMemoryRecordedTier(), RecordedStreamReader)
    assert isinstance(StaticArchiveCoverage(), ArchiveCoverage)
    assert isinstance(StaticGapReader(), RecordingGapReader)


async def test_read_is_half_open_and_scoped_to_symbol_and_stream() -> None:
    tier = InMemoryRecordedTier([_trade(10), _trade(20), _trade(30), _trade(20, symbol="ETHUSDT")])

    got = await tier.read(
        SYM, StreamKind.TRADES, TimeRange(start_us=10, end_us=30), depth=200, limit=100
    )

    assert [e.ts_us for e in got] == [10, 20]
    other = TimeRange(start_us=0, end_us=99)
    assert await tier.read(SYM, StreamKind.TICKERS, other, depth=200, limit=100) == []


async def test_book_streams_are_filtered_to_the_requested_depth() -> None:
    tier = InMemoryRecordedTier([_delta(1, 50), _delta(2, 200)])
    rng = TimeRange(start_us=0, end_us=10)

    got = await tier.read(SYM, StreamKind.ORDERBOOK_DELTA, rng, depth=200, limit=10)

    assert [e.ts_us for e in got] == [2]


async def test_read_honours_the_row_limit_and_counts_calls() -> None:
    tier = InMemoryRecordedTier([_trade(t, str(t)) for t in range(10)])

    got = await tier.read(
        SYM, StreamKind.TRADES, TimeRange(start_us=0, end_us=10), depth=1, limit=3
    )

    assert len(got) == 3
    assert tier.reads == 1


async def test_snapshot_at_is_the_latest_at_or_before_within_the_lookback() -> None:
    tier = InMemoryRecordedTier([_snapshot(100, 200), _snapshot(200, 200), _snapshot(250, 50)])

    latest = await tier.snapshot_at(SYM, 200, 260, not_before_us=0)
    exact = await tier.snapshot_at(SYM, 200, 200, not_before_us=0)
    too_old = await tier.snapshot_at(SYM, 200, 260, not_before_us=201)

    assert latest is not None and latest.ts_us == 200
    assert exact is not None and exact.ts_us == 200
    assert too_old is None


async def test_added_events_are_served_and_only_snapshots_anchor() -> None:
    tier = InMemoryRecordedTier()
    tier.add(_trade(5), _delta(6, 200), _snapshot(7, 200))

    anchor = await tier.snapshot_at(SYM, 200, 10, not_before_us=0)
    window = TimeRange(start_us=0, end_us=10)
    trades = await tier.read(SYM, StreamKind.TRADES, window, depth=200, limit=10)

    assert anchor is not None and anchor.stream is StreamKind.ORDERBOOK_SNAPSHOT
    assert [e.ts_us for e in trades] == [5]


async def test_snapshot_ties_resolve_by_the_full_order_key_not_insertion_order() -> None:
    tier = InMemoryRecordedTier([_snapshot(100, 200, update_id=9), _snapshot(100, 200, 3)])

    anchor = await tier.snapshot_at(SYM, 200, 100, not_before_us=0)

    assert anchor is not None and anchor.seq == 9


async def test_archive_coverage_is_clipped_merged_and_grows_per_symbol_stream() -> None:
    spans = {(SYM, StreamKind.TRADES): [TimeRange(start_us=20, end_us=30)]}
    coverage = StaticArchiveCoverage(spans)
    coverage.archive(SYM, StreamKind.TRADES, TimeRange(start_us=0, end_us=20))
    window = TimeRange(start_us=5, end_us=25)

    got = await coverage.archived(SYM, StreamKind.TRADES, window)

    assert got == [TimeRange(start_us=5, end_us=25)]
    assert await coverage.archived(SYM, StreamKind.TICKERS, window) == []
    assert coverage.calls == 2


@pytest.mark.parametrize(
    ("spans", "want"),
    [
        ([], []),
        ([(0, 5), (50, 60)], []),
        ([(0, 15)], [(10, 15)]),
        ([(12, 14), (11, 13), (15, 30)], [(11, 14), (15, 20)]),
        ([(10, 12), (12, 20)], [(10, 20)]),
    ],
)
def test_covered_parts_clip_sort_and_merge(
    spans: list[tuple[int, int]], want: list[tuple[int, int]]
) -> None:
    got = covered_parts(spans, TimeRange(start_us=10, end_us=20))

    assert [(r.start_us, r.end_us) for r in got] == want


@pytest.mark.parametrize(
    ("start", "end", "hit"),
    [(0, 10, False), (0, 11, True), (19, 25, True), (20, 30, False), (5, 40, True)],
)
async def test_gap_reader_returns_half_open_intersections(start: int, end: int, hit: bool) -> None:
    gap = RecordedGap(SYM, StreamKind.TRADES, start, end, "ws_disconnect")
    reader = StaticGapReader([gap, RecordedGap("ETHUSDT", StreamKind.TRADES, 0, 99, "x")])

    got = await reader.recording_gaps(SYM, TimeRange(start_us=10, end_us=20))

    assert got == ([gap] if hit else [])


@pytest.mark.parametrize(
    ("port", "method"),
    [
        (RecordedStreamReader, "read"),
        (RecordedStreamReader, "snapshot_at"),
        (ArchiveCoverage, "archived"),
    ],
)
def test_reader_interface_takes_no_filesystem_path(port: type, method: str) -> None:
    """SR-097 / ticket AC 5: datasets are addressed by stream id + symbol + time only."""
    params = inspect.signature(getattr(port, method)).parameters

    allowed = {"self", "symbol", "stream", "rng", "depth", "limit", "at_us", "not_before_us"}
    assert set(params) <= allowed
    assert not any("path" in str(p.annotation).lower() for p in params.values())


def test_replayable_streams_follow_the_stream_kind_enum_order() -> None:
    """The replay tie-break ordinal is the Postgres `stream_kind` declaration order (21 Sec.1.2)."""
    ddl = SCHEMA_DOC.read_text(encoding="utf-8")
    match = re.search(r"CREATE TYPE stream_kind\s+AS ENUM \(([^)]*)\)", ddl)
    assert match is not None
    db_kinds = [value.strip().strip("'") for value in match.group(1).split(",")]

    assert list(STREAM_BY_DB_KIND) == db_kinds
    assert tuple(STREAM_BY_DB_KIND.values()) == REPLAYABLE_STREAMS
