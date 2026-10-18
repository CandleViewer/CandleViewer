"""Gap reporting (E26-T02 AC 3): a recorded gap is a marker in the stream, never a silent jump.

A marker sorts on the merge key like an event: rank 0 (before the market events of its instant),
then its symbol, its stream's sequence domain and stream, then `(gap start, gap end, cause)`.
The gap read is bounded like every other read: more rows than the ceiling are refused whole.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Sequence

import pytest
import sqlalchemy as sa
from prometheus_client import REGISTRY

from candleviewer.replay import (
    ReplayGap,
    ReplayItem,
    ReplayMemoryCeilingExceeded,
    ReplaySourceUnavailable,
    ReplayTierStraddle,
)
from candleviewer.replay.merge import approx_bytes
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent, RecordedGap
from candleviewer.storage.testing import StaticGapReader
from tests.unit.replay._events import (
    SECOND,
    SYM,
    T0,
    Harness,
    drain,
    gap,
    request,
    ticker,
    trade,
)
from tests.unit.storage.test_recorder_repository_unit import _repo

START, END = 10 * SECOND, 20 * SECOND
ETH = "ETHUSDT"
TRADES, DELTAS = StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA
SNAPSHOTS, TICKERS = StreamKind.ORDERBOOK_SNAPSHOT, StreamKind.TICKERS
CEILING = 8_192


def markers(items: Sequence[ReplayItem]) -> list[ReplayGap]:
    return [item for item in items if isinstance(item, ReplayGap)]


def gap_count() -> float:
    return REGISTRY.get_sample_value("replay_gap_warnings_total") or 0.0


@pytest.mark.parametrize(
    ("gap_start", "gap_end", "at"),
    [
        (12 * SECOND, 15 * SECOND, 12 * SECOND),  # inside: marker at the gap start
        (5 * SECOND, 12 * SECOND, START),  # open before the window: clipped to its start
        (18 * SECOND, 30 * SECOND, 18 * SECOND),  # runs past the window end
        (5 * SECOND, START + 1, START),  # overlaps the window by 1 µs
        (END - 1, END + SECOND, END - 1),
    ],
)
async def test_a_gap_intersecting_the_window_becomes_one_marker_with_its_stored_bounds(
    gap_start: int, gap_end: int, at: int
) -> None:
    harness = Harness(gaps=[gap(gap_start, gap_end)], req=request(start_us=START, end_us=END))

    got = markers(await harness.read_all())

    want = ReplayGap(T0 + at, SYM, TRADES, T0 + gap_start, T0 + gap_end, "ws_disconnect")
    assert got == [want]


@pytest.mark.parametrize(
    ("gap_start", "gap_end"),
    [(5 * SECOND, START), (END, END + SECOND), (0, SECOND), (25 * SECOND, 30 * SECOND)],
)
async def test_a_gap_touching_or_outside_the_window_edges_emits_nothing(
    gap_start: int, gap_end: int
) -> None:
    """Half-open window: a gap ending at `from` or starting at `to` does not intersect it."""
    harness = Harness(gaps=[gap(gap_start, gap_end)], req=request(start_us=START, end_us=END))

    assert markers(await harness.read_all()) == []


def label(item: ReplayItem) -> str:
    if isinstance(item, ReplayGap):
        return f"gap {item.symbol} {item.stream.value}"
    return f"{item.stream.value} {item.symbol} {item.tiebreak[0] if item.tiebreak else ''}".strip()


async def test_a_marker_precedes_every_market_event_of_its_instant() -> None:
    """Rank 0 beats the symbol ordinal: the marker of the last symbol and domain still leads."""
    at = 12 * SECOND
    stored = [
        trade(at - 1, trade_id="before"),
        trade(at, trade_id="same"),
        ticker(at),
        trade(at, trade_id="other", symbol=ETH),
        trade(at + 1, trade_id="after"),
    ]
    harness = Harness(
        hot=stored,
        gaps=[gap(at, at + SECOND, stream=TICKERS, symbol=ETH)],
        req=request(start_us=START, end_us=END, symbols=(SYM, ETH), streams=(TRADES, TICKERS)),
    )

    got = [label(item) for item in await harness.read_all()]

    assert got == [
        "trades BTCUSDT before",
        "gap ETHUSDT tickers",
        "trades BTCUSDT same",
        "tickers BTCUSDT",
        "trades ETHUSDT other",
        "trades BTCUSDT after",
    ]


async def test_a_marker_clipped_to_the_window_start_precedes_the_events_there() -> None:
    harness = Harness(
        hot=[trade(START, trade_id="first")],
        gaps=[gap(START - 5 * SECOND, START + SECOND)],
        req=request(start_us=START, end_us=END),
    )

    got = [label(item) for item in await harness.read_all()]

    assert got == ["gap BTCUSDT trades", "trades BTCUSDT first"]


async def test_markers_of_one_instant_sort_by_symbol_then_domain_then_stream() -> None:
    """BTC's book markers precede ETH's trades marker (symbol first); inside the book domain the
    snapshot's marker precedes the delta's although the delta's gap began earlier (stream
    ordinal, not the bounds). Every gap is open at the window start, so all clip to one instant."""
    gaps = [
        gap(START - SECOND, START + SECOND, stream=TICKERS, symbol=ETH),
        gap(START - 5 * SECOND, START + SECOND, stream=DELTAS),
        gap(START - SECOND, START + SECOND, stream=TRADES, symbol=ETH),
        gap(START - 2 * SECOND, START + SECOND, stream=SNAPSHOTS),
        gap(START - SECOND, START + SECOND, stream=TRADES),
    ]
    streams = (TRADES, DELTAS, SNAPSHOTS, TICKERS)
    req = request(start_us=START, end_us=END, symbols=(ETH, SYM), streams=streams)

    got = markers(await Harness(gaps=gaps, req=req).read_all())

    assert {m.ts_us for m in got} == {T0 + START}
    assert [(m.symbol, m.stream) for m in got] == [
        (SYM, TRADES),
        (SYM, SNAPSHOTS),
        (SYM, DELTAS),
        (ETH, TRADES),
        (ETH, TICKERS),
    ]


async def test_markers_of_one_stream_and_instant_sort_by_start_then_end_then_cause() -> None:
    """All four clip to the window start and differ only in the stored bounds and cause."""
    rows = [
        gap(8 * SECOND, 11 * SECOND),
        gap(5 * SECOND, 12 * SECOND),
        gap(5 * SECOND, 12 * SECOND, cause="process_restart"),
        gap(5 * SECOND, 11 * SECOND),
    ]

    got = markers(await Harness(gaps=rows, req=request(start_us=START, end_us=END)).read_all())

    assert [(m.ts_us, m.gap_start_us, m.gap_end_us, m.cause) for m in got] == [
        (T0 + START, T0 + 5 * SECOND, T0 + 11 * SECOND, "ws_disconnect"),
        (T0 + START, T0 + 5 * SECOND, T0 + 12 * SECOND, "process_restart"),
        (T0 + START, T0 + 5 * SECOND, T0 + 12 * SECOND, "ws_disconnect"),
        (T0 + START, T0 + 8 * SECOND, T0 + 11 * SECOND, "ws_disconnect"),
    ]


async def test_gaps_of_unrequested_streams_are_ignored() -> None:
    before = gap_count()
    harness = Harness(
        gaps=[gap(12 * SECOND, 13 * SECOND, stream=DELTAS)],
        req=request(start_us=START, end_us=END),
    )

    assert markers(await harness.read_all()) == []
    assert gap_count() == before


async def test_market_events_are_untouched_by_markers() -> None:
    stored = [trade(t * SECOND, trade_id=f"t{t}") for t in range(10, 20)]
    window = request(start_us=START, end_us=END)
    harness = Harness(hot=stored, gaps=[gap(14 * SECOND, 15 * SECOND)], req=window)

    got = await harness.read_all()

    assert [item for item in got if isinstance(item, RecordedEvent)] == stored
    assert len(got) == len(stored) + 1


async def test_identical_gap_rows_report_once_and_count_once() -> None:
    before = gap_count()
    same = gap(12 * SECOND, 13 * SECOND, cause="process_restart")
    harness = Harness(gaps=[same, same], req=request(start_us=START, end_us=END))

    got = markers(await harness.read_all())

    assert [g.cause for g in got] == ["process_restart"]
    assert gap_count() == before + 1


async def test_rows_differing_in_stream_end_or_cause_are_reported_separately() -> None:
    rows = [
        gap(12 * SECOND, 13 * SECOND),
        gap(12 * SECOND, 14 * SECOND),
        gap(12 * SECOND, 13 * SECOND, cause="seq_jump"),
        gap(12 * SECOND, 13 * SECOND, stream=TICKERS),
    ]
    req = request(start_us=START, end_us=END, streams=(TRADES, TICKERS))

    got = markers(await Harness(gaps=rows, req=req).read_all())

    assert len(got) == 4


class _LaxGaps(StaticGapReader):
    """A reader that ignores its window and symbol: the merge must re-check both itself."""

    async def recording_gaps(
        self, symbol: str, rng: TimeRange, *, streams: Collection[StreamKind], limit: int
    ) -> list[RecordedGap]:
        self.limits.append(limit)
        return list(self._gaps)[:limit]


async def test_the_merge_re_checks_symbol_stream_and_window_of_every_gap_row() -> None:
    kept = [gap(12 * SECOND, 13 * SECOND), gap(15 * SECOND, 16 * SECOND, symbol=ETH)]
    dropped = [
        gap(START - SECOND, START),  # ends exactly at the window start
        gap(END, END + SECOND),  # starts exactly at the window end
        gap(30 * SECOND, 31 * SECOND),
        gap(12 * SECOND, 13 * SECOND, stream=DELTAS),
    ]
    harness = Harness(req=request(start_us=START, end_us=END, symbols=(SYM, ETH)))
    harness.replace_ports(gaps=_LaxGaps(kept + dropped))
    before = gap_count()

    got = markers(await harness.read_all())

    assert [(g.symbol, g.gap_start_us) for g in got] == [
        (SYM, kept[0].start_us),
        (ETH, kept[1].start_us),
    ]
    assert gap_count() == before + 2


class _BrokenGaps(StaticGapReader):
    """Fails for `bad` only, with a message that carries a path (RP-I02)."""

    def __init__(self, bad: str) -> None:
        super().__init__()
        self._bad = bad

    async def recording_gaps(
        self, symbol: str, rng: TimeRange, *, streams: Collection[StreamKind], limit: int
    ) -> list[RecordedGap]:
        if symbol == self._bad:
            raise StorageTierUnavailable("postgres unreachable at /var/lib/cv/pg")
        return await super().recording_gaps(symbol, rng, streams=streams, limit=limit)


class _StuckGaps(StaticGapReader):
    async def recording_gaps(
        self, symbol: str, rng: TimeRange, *, streams: Collection[StreamKind], limit: int
    ) -> list[RecordedGap]:
        await asyncio.Event().wait()  # never answers
        return []


async def test_an_unreadable_gap_table_fails_the_replay_rather_than_hiding_gaps() -> None:
    req = request(symbols=(SYM, ETH))
    harness = Harness(hot=[trade(SECOND)], req=req).replace_ports(gaps=_BrokenGaps(ETH))

    delivered, error = await drain(harness.merge(), batch=8)

    assert delivered == [] and harness.hot.reads == 0  # refused before any event is read
    assert isinstance(error, ReplaySourceUnavailable)
    assert (error.tier, error.symbol, error.stream, error.reason) == (
        "recording_gaps",
        ETH,
        None,
        "STORAGE_TIER_UNAVAILABLE",
    )
    assert "/var" not in str(error) and error.__cause__ is None and error.__context__ is None


async def test_a_postgres_outage_in_the_gap_read_reaches_the_replay_typed_without_its_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production gap adapter, not a double: its driver failure becomes the typed
    `ReplaySourceUnavailable` of an unreadable gap table, and no text of it travels."""
    adapter, _ = _repo([])

    async def outage(*_: object) -> list[dict[str, object]]:
        raise sa.exc.OperationalError("SELECT ...", {}, Exception("server at 10.0.0.5:5432 down"))

    monkeypatch.setattr(adapter, "_all", outage)
    harness = Harness(hot=[trade(SECOND)]).replace_ports(gaps=adapter)

    delivered, error = await drain(harness.merge(), batch=8)

    assert delivered == [] and harness.hot.reads == 0
    assert isinstance(error, ReplaySourceUnavailable)
    assert (error.tier, error.stream, error.reason) == (
        "recording_gaps",
        None,
        "STORAGE_QUERY_FAILED",
    )
    assert "10.0.0.5" not in str(error) and error.__cause__ is None and error.__context__ is None


async def test_a_gap_read_that_never_answers_times_out_as_a_typed_error() -> None:
    harness = Harness(hot=[trade(SECOND)]).replace_ports(gaps=_StuckGaps())

    async with asyncio.timeout(5):  # a merge without its own deadline fails here, not hangs
        delivered, error = await drain(harness.merge(timeout_s=0.001), batch=8)

    assert delivered == [] and harness.hot.reads == 0
    assert isinstance(error, ReplaySourceUnavailable)
    assert (error.tier, error.stream, error.reason) == ("recording_gaps", None, "timeout")


async def test_each_symbols_gap_read_asks_for_the_window_and_one_row_past_the_ceiling() -> None:
    req = request(start_us=START, end_us=END, symbols=(SYM, ETH))
    harness = Harness(req=req)

    await harness.read_all()

    window = TimeRange(start_us=req.start_us, end_us=req.end_us)
    assert harness.gaps.limits == [CEILING + 1, CEILING + 1]
    assert harness.gaps.windows == [window, window]


async def test_each_symbols_gap_read_asks_for_the_requested_streams_only() -> None:
    req = request(start_us=START, end_us=END, symbols=(SYM, ETH), streams=(TRADES, DELTAS))
    harness = Harness(req=req)

    await harness.read_all()

    assert harness.gaps.stream_sets == [frozenset({TRADES, DELTAS})] * 2


async def test_gap_rows_of_streams_the_replay_does_not_read_never_count_toward_the_ceiling() -> (
    None
):
    """The ceiling bounds what the replay reports: a busy unrequested stream cannot refuse it."""
    unread = [gap(START + i, START + i + 1, stream=TICKERS) for i in range(CEILING + 1)]
    read = gap(12 * SECOND, 13 * SECOND)
    harness = Harness(gaps=[*unread, read], req=request(start_us=START, end_us=END))

    got = markers(await harness.read_all())

    assert [(g.stream, g.gap_start_us) for g in got] == [(TRADES, read.start_us)]


def dense_gaps(count: int, *, symbol: str = SYM) -> list[RecordedGap]:
    """`count` distinct gap rows of one stream, all inside the window."""
    return [gap(START + i, START + i + 1, symbol=symbol) for i in range(count)]


async def test_a_symbol_with_exactly_the_ceiling_of_gap_rows_reports_them_all() -> None:
    harness = Harness(gaps=dense_gaps(CEILING), req=request(start_us=START, end_us=END))

    assert len(markers(await harness.read_all())) == CEILING


async def test_a_dense_gap_table_is_built_in_slices_that_yield_to_the_event_loop() -> None:
    """C-2.17: 8 192 rows take tens of milliseconds to turn into markers, so the loop is served
    every 1 024 rows (7 yields here); a build that never yields leaves the heartbeat at zero."""
    turns = 0

    async def heartbeat() -> None:
        nonlocal turns
        while True:
            await asyncio.sleep(0)
            turns += 1

    beat = asyncio.create_task(heartbeat())
    harness = Harness(gaps=dense_gaps(CEILING), req=request(start_us=START, end_us=END))

    got = markers(await harness.read_all())
    beat.cancel()

    assert len(got) == CEILING
    assert turns >= 6


async def test_the_ceiling_of_gap_rows_holds_per_symbol_not_across_symbols() -> None:
    rows = dense_gaps(CEILING) + dense_gaps(8, symbol=ETH)
    harness = Harness(gaps=rows, req=request(start_us=START, end_us=END, symbols=(SYM, ETH)))

    assert len(markers(await harness.read_all())) == CEILING + 8


@pytest.mark.parametrize("symbol", [SYM, ETH])
async def test_a_symbol_with_more_gap_rows_than_the_ceiling_is_refused_whole(symbol: str) -> None:
    """Never reported in part, and refused before any event is read or delivered."""
    rows = dense_gaps(CEILING + 1, symbol=symbol)
    req = request(start_us=START, end_us=END, symbols=(SYM, ETH))
    harness = Harness(hot=[trade(START, trade_id="x")], gaps=rows, req=req)

    delivered, error = await drain(harness.merge(), batch=8)

    assert delivered == [] and harness.hot.reads == 0
    assert isinstance(error, ReplayMemoryCeilingExceeded)
    assert (error.symbol, error.stream, error.max_rows) == (symbol, None, CEILING)
    assert "recording_gaps" in str(error) and str(CEILING) in str(error)


class _OverReturningGaps(StaticGapReader):
    """A reader that ignores `limit` and hands back every row it holds."""

    async def recording_gaps(
        self, symbol: str, rng: TimeRange, *, streams: Collection[StreamKind], limit: int
    ) -> list[RecordedGap]:
        self.limits.append(limit)
        return list(self._gaps)


async def test_a_reader_that_ignores_the_limit_is_still_refused_past_the_ceiling() -> None:
    harness = Harness(hot=[trade(START, trade_id="x")], req=request(start_us=START, end_us=END))
    harness.replace_ports(gaps=_OverReturningGaps(dense_gaps(CEILING + 50)))

    delivered, error = await drain(harness.merge(), batch=8)

    assert delivered == [] and harness.hot.reads == 0
    assert isinstance(error, ReplayMemoryCeilingExceeded) and error.max_rows == CEILING


@pytest.mark.parametrize(("extra_bytes", "want"), [(0, [2, 2, 1]), (1, [3, 2])])
async def test_a_marker_counts_as_one_event_toward_the_batch_byte_cut(
    extra_bytes: int, want: list[int]
) -> None:
    """Slice 6's read-ahead sizes its buffer from these estimates: two markers fill exactly the
    bytes of two events, and one byte more lets a third in."""
    rows = [gap(START + i, START + i + 1) for i in range(5)]
    merge = Harness(gaps=rows, req=request(start_us=START, end_us=END)).merge()
    limit = 2 * approx_bytes(trade(0)) + extra_bytes

    sizes = [len(batch) async for batch in merge.batches(max_events=100, max_bytes=limit)]

    assert sizes == want


async def test_a_straddling_session_is_refused_before_any_gap_is_read() -> None:
    harness = Harness(req=request(start_us=START, end_us=END)).archive(START, START + 5 * SECOND)

    with pytest.raises(ReplayTierStraddle):
        await harness.read_all()

    assert harness.gaps.limits == []
