"""Merge invariants over generated recordings (E26-T02 test plan: Hypothesis properties).

Each property sorts the recording by a key written out here, independently of `merge.py`'s
constants, and compares whole sequences: 3 symbols x 4 streams on a few instants, so equal
timestamps and equal `seq` across streams are the norm; gap markers on the same instants
(identical rows, rows of unrequested streams, rows open at either window edge); re-exported
duplicate rows in the cold tier; rows before and after the window; any storage order; read
windows of 1-64 µs; row caps of 1-8.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.replay import ReplayGap, ReplayItem, ReplayRequest, ReplayTierStraddle, SourceTier
from candleviewer.replay.merge import row_bytes
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent, RecordedGap, Tiebreak
from tests.unit.replay._events import T0, Harness, delta, digest, request, snapshot, ticker, trade

SYMBOLS = ("AAAUSDT", "BBBUSDT", "CCCUSDT")
TRADES, DELTAS = StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA
SNAPSHOTS, TICKERS = StreamKind.ORDERBOOK_SNAPSHOT, StreamKind.TICKERS
STREAMS = (TRADES, DELTAS, SNAPSHOTS, TICKERS)
CAUSES = ("ws_disconnect", "process_restart", "seq_jump")
#: The ruled order written out by hand: sequence domain (the book streams share one), then the
#: stream ordinal that splits it (snapshot first).
_DOMAIN = {TRADES: 0, DELTAS: 1, SNAPSHOTS: 1, TICKERS: 2}
_STREAM = {TRADES: 0, SNAPSHOTS: 1, DELTAS: 2, TICKERS: 3}

type Key = tuple[int, int, int, int, int, int, Tiebreak]


def ruled_key(item: ReplayItem) -> Key:
    symbol = SYMBOLS.index(item.symbol)
    if isinstance(item, ReplayGap):
        tiebreak = (item.gap_start_us, item.gap_end_us, item.cause)
        return item.ts_us, 0, symbol, _DOMAIN[item.stream], 0, _STREAM[item.stream], tiebreak
    stream = item.stream
    return item.ts_us, 1, symbol, _DOMAIN[stream], item.seq, _STREAM[stream], item.tiebreak


@dataclass(frozen=True)
class Recording:
    rows: list[RecordedEvent]
    copies: list[RecordedEvent]
    gaps: list[RecordedGap]
    cap: int
    start_us: int
    end_us: int

    def expected(self) -> list[ReplayItem]:
        """What a replay must emit: the in-window rows once each, and one marker per distinct
        gap row of a requested stream that intersects the window, clipped to its start."""
        lo, hi = T0 + self.start_us, T0 + self.end_us
        items: list[ReplayItem] = [e for e in self.rows if lo <= e.ts_us < hi]
        for symbol, stream, start, end, cause in {
            (g.symbol, g.stream, g.start_us, g.end_us, g.cause)
            for g in self.gaps
            if g.stream in STREAMS and g.start_us < hi and g.end_us > lo
        }:
            items.append(ReplayGap(max(start, lo), symbol, stream, start, end, cause))
        return sorted(items, key=ruled_key)


def _event(index: int, symbol: str, stream: StreamKind, at_us: int, seq: int) -> RecordedEvent:
    if stream is TRADES:
        return trade(at_us, seq=seq, trade_id=f"t{index}", symbol=symbol)
    if stream is DELTAS:
        return delta(at_us, update_id=index, cross_seq=seq, depth=1, symbol=symbol)
    if stream is SNAPSHOTS:
        return snapshot(at_us, update_id=index, cross_seq=seq, depth=1, symbol=symbol)
    return ticker(at_us, symbol=symbol)


@st.composite
def recordings(draw: st.DrawFn) -> Recording:
    cap = draw(st.integers(1, 8))
    cells = st.tuples(
        st.sampled_from(SYMBOLS), st.sampled_from(STREAMS), st.integers(0, 13), st.integers(0, 3)
    )
    held: Counter[tuple[str, StreamKind, int]] = Counter()
    rows: list[RecordedEvent] = []
    for i, (symbol, stream, at_us, seq) in enumerate(draw(st.lists(cells, max_size=60))):
        cell = (symbol, stream, at_us)
        if held[cell] < (1 if stream is TICKERS else cap):  # one ticker per (symbol, instant)
            held[cell] += 1
            rows.append(_event(i, symbol, stream, at_us, seq))
    copies: list[RecordedEvent] = []
    for row in draw(st.lists(st.sampled_from(rows), max_size=8)) if rows else []:
        cell = (row.symbol, row.stream, row.ts_us - T0)
        if held[cell] < cap:  # a copy is read too, so it counts against the per-read row cap
            held[cell] += 1
            copies.append(row)
    spans = st.tuples(
        st.sampled_from(SYMBOLS),
        st.sampled_from((*STREAMS, StreamKind.LIQUIDATIONS)),
        st.integers(-6, 16),
        st.integers(1, 12),
        st.sampled_from(CAUSES),
    )
    gaps = [
        RecordedGap(symbol, stream, T0 + start, T0 + start + length, cause)
        for symbol, stream, start, length, cause in draw(st.lists(spans, max_size=25))
    ]
    gaps += draw(st.lists(st.sampled_from(gaps), max_size=5)) if gaps else []
    return Recording(rows, copies, gaps, cap, draw(st.integers(0, 3)), draw(st.integers(8, 14)))


def read(harness: Harness, *, window_us: int, batch: int, cap: int) -> list[ReplayItem]:
    budget = cap * row_bytes(SNAPSHOTS, 1) * len(SYMBOLS) * len(STREAMS)
    return asyncio.run(
        harness.read_all(batch=batch, budget_bytes=budget, window_us=window_us, max_window_us=64)
    )


def window_of(rec: Recording, tier: SourceTier) -> ReplayRequest:
    return request(
        symbols=SYMBOLS,
        streams=STREAMS,
        depth=1,
        start_us=rec.start_us,
        end_us=rec.end_us,
        tier=tier,
    )


@given(
    recording=recordings(), data=st.data(), window_us=st.integers(1, 64), batch=st.integers(1, 8)
)
def test_any_storage_order_and_tier_replays_the_ruled_total_order_with_its_markers(
    recording: Recording, data: st.DataObject, window_us: int, batch: int
) -> None:
    """Ticket AC 1 and 3 as one property: events and gap markers together are emitted in the
    ruled order, each exactly once, whichever tier served them, in whatever order storage held
    them (the cold tier with re-exported copies) and whatever the window and batch sizes."""
    cold_rows = data.draw(st.permutations(recording.rows + recording.copies))
    hot_rows = data.draw(st.permutations(recording.rows))
    cold = Harness(
        cold=cold_rows, gaps=recording.gaps, req=window_of(recording, "auto"), archived=True
    )
    hot = Harness(hot=hot_rows, gaps=recording.gaps, req=window_of(recording, "questdb"))

    got_cold = read(cold, window_us=window_us, batch=batch, cap=recording.cap)
    got_hot = read(hot, window_us=64, batch=64, cap=recording.cap)

    assert got_cold == recording.expected()
    assert got_hot == recording.expected()
    assert digest(got_cold) == digest(got_hot)
    assert cold.hot.reads == 0 and hot.cold.reads == 0


@given(
    spans=st.lists(
        st.tuples(
            st.sampled_from(SYMBOLS),
            st.sampled_from(STREAMS),
            st.integers(-5_000, 60_000),
            st.integers(1, 60_000),
        ),
        max_size=8,
    )
)
def test_auto_reads_exactly_one_tier_or_refuses_before_reading(
    spans: list[tuple[str, StreamKind, int, int]],
) -> None:
    """ADR-0035 decision 4 as a property: never both tiers, and never a guess on a straddle."""
    req = request(symbols=SYMBOLS, streams=STREAMS, end_us=60_000)
    harness = Harness(hot=[trade(0)], cold=[trade(0)], req=req)
    for symbol, stream, lo, span in spans:
        harness.coverage.archive(symbol, stream, TimeRange(start_us=T0 + lo, end_us=T0 + lo + span))
    whole = TimeRange(start_us=req.start_us, end_us=req.end_us)
    parts = [
        asyncio.run(harness.coverage.archived(symbol, stream, whole))
        for symbol in SYMBOLS
        for stream in STREAMS
    ]

    try:
        asyncio.run(harness.read_all())
    except ReplayTierStraddle:
        assert any(p != [whole] for p in parts) and any(parts)
        assert harness.hot.reads == harness.cold.reads == 0
    else:
        archived = all(p == [whole] for p in parts)
        assert archived or not any(parts)
        assert (harness.cold.reads > 0, harness.hot.reads > 0) == (archived, not archived)
