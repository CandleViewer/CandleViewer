"""The recorded-event read interface and its in-memory fakes (E26-T02).

The fakes are the public test surface the replay module (and later E26 tickets) code against,
so their semantics must match the real tiers': half-open ranges, the book-depth filter, the
row `limit` (earliest first), storage order on equal timestamps, the inclusive bounds of the
anchor lookup, and order keys compared within one `(symbol, stream)` only.
"""

from __future__ import annotations

import inspect
import itertools
import re
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.storage.errors import StorageError
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    STREAM_BY_DB_KIND,
    ManifestCoverage,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedGap,
    RecordedQueryRejected,
    RecordedStreamReader,
    RecordedTrade,
    RecordingGapReader,
    covered_parts,
    order_key,
)
from candleviewer.storage.testing import (
    InMemoryRecordedTier,
    StaticGapReader,
    StaticManifestCoverage,
)

SYM = "BTCUSDT"
SCHEMA_DOC = Path(__file__).resolve().parents[5] / "docs" / "plan" / "21-database-schema.md"


def _trade(ts_us: int, trade_id: str = "t", *, symbol: str = SYM, seq: int = 0) -> RecordedEvent:
    payload = RecordedTrade("buy", Decimal(1), Decimal(1), trade_id, None)
    return RecordedEvent(ts_us, seq, symbol, StreamKind.TRADES, (trade_id,), payload)


def _delta(ts_us: int, depth: int, update_id: int = 1) -> RecordedEvent:
    payload = RecordedBookDelta(depth, "bid", Decimal(1), Decimal(1), update_id, None)
    tiebreak = (update_id, depth, "bid", Decimal(1))
    return RecordedEvent(ts_us, update_id, SYM, StreamKind.ORDERBOOK_DELTA, tiebreak, payload)


def _snapshot(ts_us: int, depth: int, update_id: int = 1) -> RecordedEvent:
    payload = RecordedBookSnapshot(depth, update_id, None, (), ())
    tiebreak = (update_id, depth, -1)
    return RecordedEvent(ts_us, update_id, SYM, StreamKind.ORDERBOOK_SNAPSHOT, tiebreak, payload)


def _window(start_us: int, end_us: int) -> TimeRange:
    return TimeRange(start_us=start_us, end_us=end_us)


async def _trade_times(tier: InMemoryRecordedTier, rng: TimeRange, limit: int = 100) -> list[int]:
    return [e.ts_us for e in await tier.read(SYM, StreamKind.TRADES, rng, depth=200, limit=limit)]


async def test_fakes_conform_to_the_reader_protocols_by_signature() -> None:
    """Typed assignments: `mypy --strict` checks each fake's signatures against its Protocol
    (a runtime `isinstance` on a `runtime_checkable` Protocol checks member names only), and
    the calls below go through the Protocol types."""
    reader: RecordedStreamReader = InMemoryRecordedTier()
    coverage: ManifestCoverage = StaticManifestCoverage()
    gaps: RecordingGapReader = StaticGapReader()
    window = _window(0, 10)

    assert list(await reader.read(SYM, StreamKind.TRADES, window, depth=200, limit=1)) == []
    assert await reader.snapshot_at(SYM, 200, 10, not_before_us=0) is None
    assert list(await coverage.archived(SYM, StreamKind.TRADES, window)) == []
    assert list(await gaps.recording_gaps(SYM, window, streams=(StreamKind.TRADES,), limit=1)) == []


async def test_read_includes_the_range_start_and_excludes_its_end() -> None:
    tier = InMemoryRecordedTier([_trade(9), _trade(10), _trade(29), _trade(30)])

    assert await _trade_times(tier, _window(10, 30)) == [10, 29]


async def test_read_ignores_other_symbols() -> None:
    tier = InMemoryRecordedTier([_trade(5, symbol="ETHUSDT")])

    assert await _trade_times(tier, _window(0, 10)) == []


async def test_read_ignores_other_streams() -> None:
    tier = InMemoryRecordedTier([_trade(5)])

    assert await tier.read(SYM, StreamKind.TICKERS, _window(0, 10), depth=200, limit=9) == []


async def test_read_filters_book_streams_to_the_requested_depth() -> None:
    tier = InMemoryRecordedTier([_delta(1, 50), _delta(2, 200)])
    rng = _window(0, 10)

    got = await tier.read(SYM, StreamKind.ORDERBOOK_DELTA, rng, depth=200, limit=10)

    assert [e.ts_us for e in got] == [2]


async def test_read_orders_rows_by_timestamp_whatever_the_storage_order() -> None:
    tier = InMemoryRecordedTier([_trade(30), _trade(10), _trade(20)])

    assert await _trade_times(tier, _window(0, 100)) == [10, 20, 30]


@pytest.mark.parametrize("trade_ids", [("b", "a"), ("a", "b")])
async def test_read_keeps_storage_order_among_equal_timestamps(trade_ids: tuple[str, ...]) -> None:
    """Never sorted by key on a tie: the larger key stored first stays first."""
    tier = InMemoryRecordedTier([_trade(5, trade_id) for trade_id in trade_ids])

    got = await tier.read(SYM, StreamKind.TRADES, _window(0, 10), depth=200, limit=10)

    assert [e.tiebreak for e in got] == [(trade_id,) for trade_id in trade_ids]


async def test_read_at_the_row_cap_keeps_the_earliest_rows() -> None:
    tier = InMemoryRecordedTier([_trade(ts, str(ts)) for ts in range(10)])

    assert await _trade_times(tier, _window(0, 10), limit=3) == [0, 1, 2]


@pytest.mark.parametrize("limit", [0, -1, True])
async def test_read_refuses_a_limit_below_one_before_touching_storage(limit: int) -> None:
    tier = InMemoryRecordedTier([_trade(5)])

    with pytest.raises(RecordedQueryRejected):
        await tier.read(SYM, StreamKind.TRADES, _window(0, 10), depth=200, limit=limit)
    assert tier.reads == 0


async def test_each_storage_call_is_counted() -> None:
    tier = InMemoryRecordedTier()

    await tier.read(SYM, StreamKind.TRADES, _window(0, 10), depth=200, limit=1)
    await tier.snapshot_at(SYM, 200, 10, not_before_us=0)

    assert tier.reads == 2


async def test_events_added_later_are_served() -> None:
    tier = InMemoryRecordedTier([_trade(1)])
    tier.add(_trade(2), _trade(3))

    assert await _trade_times(tier, _window(0, 10)) == [1, 2, 3]


async def test_snapshot_at_returns_the_latest_snapshot_at_or_before_the_target() -> None:
    tier = InMemoryRecordedTier(
        [_snapshot(100, 200, 9), _snapshot(200, 200, 3), _snapshot(300, 200)]
    )

    anchor = await tier.snapshot_at(SYM, 200, 260, not_before_us=0)

    assert anchor is not None and anchor.ts_us == 200


async def test_snapshot_at_includes_a_snapshot_exactly_at_the_target() -> None:
    tier = InMemoryRecordedTier([_snapshot(100, 200), _snapshot(200, 200)])

    anchor = await tier.snapshot_at(SYM, 200, 200, not_before_us=0)

    assert anchor is not None and anchor.ts_us == 200


async def test_snapshot_at_includes_a_snapshot_exactly_at_not_before() -> None:
    tier = InMemoryRecordedTier([_snapshot(200, 200)])

    anchor = await tier.snapshot_at(SYM, 200, 260, not_before_us=200)

    assert anchor is not None and anchor.ts_us == 200


async def test_snapshot_at_finds_nothing_older_than_not_before() -> None:
    tier = InMemoryRecordedTier([_snapshot(200, 200)])

    assert await tier.snapshot_at(SYM, 200, 260, not_before_us=201) is None


async def test_snapshot_at_ignores_other_depths() -> None:
    tier = InMemoryRecordedTier([_snapshot(100, 200), _snapshot(150, 50)])

    anchor = await tier.snapshot_at(SYM, 200, 200, not_before_us=0)

    assert anchor is not None and anchor.ts_us == 100


async def test_snapshot_at_anchors_only_on_snapshots() -> None:
    tier = InMemoryRecordedTier([_trade(9), _snapshot(7, 200), _delta(8, 200)])

    anchor = await tier.snapshot_at(SYM, 200, 10, not_before_us=0)

    assert anchor is not None and anchor.stream is StreamKind.ORDERBOOK_SNAPSHOT


@pytest.mark.parametrize("update_ids", [(3, 9), (9, 3)])
async def test_snapshot_at_resolves_an_instant_tie_by_the_order_key(
    update_ids: tuple[int, ...],
) -> None:
    """The larger key wins in either storage order: stored last, so "the first of the tied
    snapshots" fails, and stored first, so "the last stored" fails."""
    tier = InMemoryRecordedTier([_snapshot(100, 200, uid) for uid in update_ids])

    anchor = await tier.snapshot_at(SYM, 200, 100, not_before_us=0)

    assert anchor is not None and anchor.seq == 9


async def test_the_fakes_never_compare_order_keys_across_streams() -> None:
    """Order keys compare within one `(symbol, stream)` only. These events share `(ts_us, seq)`
    and their tiebreaks are not mutually comparable, so a fake that compared keys across
    streams would raise `TypeError` or answer with another stream's event."""
    trade, delta, snapshot = _trade(100, seq=7), _delta(100, 200, 7), _snapshot(100, 200, 7)
    tier = InMemoryRecordedTier([trade, delta, snapshot])
    rng = _window(0, 200)
    with pytest.raises(TypeError):
        sorted([trade, delta, snapshot], key=order_key)

    assert await tier.snapshot_at(SYM, 200, 100, not_before_us=0) == snapshot
    assert await tier.read(SYM, StreamKind.TRADES, rng, depth=200, limit=9) == [trade]
    assert await tier.read(SYM, StreamKind.ORDERBOOK_DELTA, rng, depth=200, limit=9) == [delta]


def test_order_key_orders_by_time_then_seq_then_tiebreak() -> None:
    first = _trade(1, "z", seq=9)
    second, third, fourth = _trade(2, "y", seq=1), _trade(2, "z", seq=1), _trade(2, "a", seq=2)

    got = sorted([fourth, third, second, first], key=order_key)

    assert got == [first, second, third, fourth]


@pytest.mark.parametrize(
    ("spans", "want"),
    [
        ([], []),
        ([(0, 5), (50, 60)], []),
        ([(0, 15)], [(10, 15)]),
        ([(12, 14), (11, 13), (15, 30)], [(11, 14), (15, 20)]),
        ([(10, 12), (12, 20)], [(10, 20)]),
        ([(10, 20), (12, 14)], [(10, 20)]),
        ([(11, 18), (12, 13), (17, 19)], [(11, 19)]),
    ],
)
def test_covered_parts_clips_sorts_and_merges(
    spans: list[tuple[int, int]], want: list[tuple[int, int]]
) -> None:
    """Includes nested spans: a span inside a merged run never shortens the run."""
    got = covered_parts(spans, _window(10, 20))

    assert [(r.start_us, r.end_us) for r in got] == want


@pytest.mark.parametrize(
    ("spans", "bounds"),
    [
        ([(0, 10)], (10, 20)),
        ([(20, 30)], (10, 20)),
        ([(12, 12)], (10, 20)),
        ([(0, 30)], (10, 10)),
    ],
    ids=["ends-at-range-start", "starts-at-range-end", "zero-width-span", "empty-range"],
)
def test_covered_parts_never_yields_a_zero_width_part(
    spans: list[tuple[int, int]], bounds: tuple[int, int]
) -> None:
    assert covered_parts(spans, _window(*bounds)) == []


@pytest.mark.parametrize("span", [(15, 12), (50, 40)], ids=["inside-range", "outside-range"])
def test_covered_parts_rejects_an_inverted_span_as_a_storage_error(span: tuple[int, int]) -> None:
    with pytest.raises(StorageError):
        covered_parts([span], _window(10, 20))


_SPAN = st.tuples(st.integers(0, 40), st.integers(0, 40)).map(lambda p: (min(p), max(p)))


@given(spans=st.lists(_SPAN, max_size=8), bounds=_SPAN)
def test_covered_parts_is_the_canonical_cover_of_the_range_and_the_union(
    spans: list[tuple[int, int]], bounds: tuple[int, int]
) -> None:
    """Sorted, disjoint, non-touching, non-empty parts inside `rng` covering `rng ∩ union`."""
    got = [(r.start_us, r.end_us) for r in covered_parts(spans, _window(*bounds))]

    union = {t for lo, hi in spans for t in range(lo, hi)}
    assert {t for lo, hi in got for t in range(lo, hi)} == union & set(range(*bounds))
    assert all(bounds[0] <= lo < hi <= bounds[1] for lo, hi in got)
    assert all(a_hi < b_lo for (_, a_hi), (b_lo, _) in itertools.pairwise(got))


async def test_archiving_a_span_grows_the_coverage() -> None:
    coverage = StaticManifestCoverage({(SYM, StreamKind.TRADES): [_window(20, 30)]})
    coverage.archive(SYM, StreamKind.TRADES, _window(0, 20))

    got = await coverage.archived(SYM, StreamKind.TRADES, _window(5, 25))

    assert got == [_window(5, 25)]


@pytest.mark.parametrize(
    ("symbol", "stream"), [(SYM, StreamKind.TICKERS), ("ETHUSDT", StreamKind.TRADES)]
)
async def test_archive_coverage_is_scoped_to_its_symbol_and_stream(
    symbol: str, stream: StreamKind
) -> None:
    coverage = StaticManifestCoverage({(SYM, StreamKind.TRADES): [_window(0, 50)]})

    assert await coverage.archived(symbol, stream, _window(0, 50)) == []


async def test_archive_coverage_counts_lookups() -> None:
    coverage = StaticManifestCoverage()

    for _ in range(2):
        await coverage.archived(SYM, StreamKind.TRADES, _window(0, 10))

    assert coverage.calls == 2


@pytest.mark.parametrize(
    ("start", "end", "hit"),
    [(0, 10, False), (0, 11, True), (19, 25, True), (20, 30, False), (5, 40, True)],
)
async def test_gap_reader_returns_half_open_intersections(start: int, end: int, hit: bool) -> None:
    gap = RecordedGap(SYM, StreamKind.TRADES, start, end, "ws_disconnect")
    reader = StaticGapReader([gap])

    got = await reader.recording_gaps(SYM, _window(10, 20), streams=(StreamKind.TRADES,), limit=5)

    assert got == ([gap] if hit else [])


async def test_gap_reader_ignores_other_symbols() -> None:
    reader = StaticGapReader([RecordedGap("ETHUSDT", StreamKind.TRADES, 0, 99, "x")])

    assert (
        await reader.recording_gaps(SYM, _window(10, 20), streams=(StreamKind.TRADES,), limit=5)
        == []
    )


async def test_gap_reader_at_the_row_cap_keeps_the_earliest_starts() -> None:
    stored = [RecordedGap(SYM, StreamKind.TRADES, start, 30, "x") for start in (14, 11, 13, 12)]
    reader = StaticGapReader(stored)

    got = await reader.recording_gaps(SYM, _window(10, 20), streams=(StreamKind.TRADES,), limit=3)

    assert [g.start_us for g in got] == [11, 12, 13]
    assert reader.limits == [3]


async def test_gap_reader_returns_only_the_asked_streams_and_caps_after_filtering() -> None:
    """Rows of a stream the caller does not read never take a place under its cap."""
    other = [RecordedGap(SYM, StreamKind.TICKERS, start, 30, "x") for start in (10, 11, 12)]
    wanted = RecordedGap(SYM, StreamKind.TRADES, 13, 30, "x")
    reader = StaticGapReader([*other, wanted])

    got = await reader.recording_gaps(SYM, _window(10, 20), streams=(StreamKind.TRADES,), limit=1)
    none = await reader.recording_gaps(SYM, _window(10, 20), streams=(), limit=5)

    assert (got, none) == ([wanted], [])
    assert reader.stream_sets == [frozenset({StreamKind.TRADES}), frozenset()]


@pytest.mark.parametrize("limit", [0, -1, True])
async def test_gap_reader_refuses_a_limit_below_one_before_touching_storage(limit: int) -> None:
    reader = StaticGapReader([RecordedGap(SYM, StreamKind.TRADES, 11, 12, "x")])

    with pytest.raises(RecordedQueryRejected):
        await reader.recording_gaps(SYM, _window(10, 20), streams=(StreamKind.TRADES,), limit=limit)
    assert reader.limits == []


@pytest.mark.parametrize(
    ("port", "method"),
    [
        (RecordedStreamReader, "read"),
        (RecordedStreamReader, "snapshot_at"),
        (ManifestCoverage, "archived"),
        (RecordingGapReader, "recording_gaps"),
    ],
)
def test_reader_interface_takes_no_filesystem_path(port: type, method: str) -> None:
    """SR-097 / ticket AC 5: datasets are addressed by stream id + symbol + time only."""
    params = inspect.signature(getattr(port, method)).parameters

    allowed = {
        "self",
        "symbol",
        "stream",
        "streams",
        "rng",
        "depth",
        "limit",
        "at_us",
        "not_before_us",
    }
    assert set(params) <= allowed
    assert not any("path" in str(p.annotation).lower() for p in params.values())


def test_replayable_streams_follow_the_stream_kind_enum_order() -> None:
    """The replay's stream ordinal, which orders streams sharing `ts_us`, is the Postgres
    `stream_kind` declaration order (21 Sec.1.2)."""
    ddl = SCHEMA_DOC.read_text(encoding="utf-8")
    match = re.search(r"CREATE TYPE stream_kind\s+AS ENUM \(([^)]*)\)", ddl)
    assert match is not None
    db_kinds = [value.strip().strip("'") for value in match.group(1).split(",")]

    assert list(STREAM_BY_DB_KIND) == db_kinds
    assert tuple(STREAM_BY_DB_KIND.values()) == REPLAYABLE_STREAMS


def test_the_stream_ordinal_mapping_is_read_only() -> None:
    assert isinstance(STREAM_BY_DB_KIND, MappingProxyType)
