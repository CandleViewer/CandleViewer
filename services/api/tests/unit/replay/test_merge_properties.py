"""Merge invariants over generated recordings (E26-T02 test plan: Hypothesis properties).

Recordings put several streams and symbols on few instants, so key ties are common. They carry
`recording_gaps` rows, including gaps of streams the replay did not ask for, and the cold tier
holds re-exported duplicate rows, all stored in any order.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.replay import ReplayGap, ReplayItem, ReplayTierStraddle
from candleviewer.replay.merge import STREAM_ORDINAL, row_bytes
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent, RecordedGap
from tests.unit.replay._events import T0, Harness, delta, gap, request, ticker, trade

SYMBOLS = ("BTCUSDT", "ETHUSDT")
STREAMS = (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA, StreamKind.TICKERS)
END_US = 60_000


@st.composite
def recordings(draw: st.DrawFn) -> tuple[list[RecordedEvent], list[RecordedGap]]:
    events: list[RecordedEvent] = []
    tickers: set[tuple[str, int]] = set()
    for i in range(draw(st.integers(0, 50))):
        symbol = draw(st.sampled_from(SYMBOLS))
        at_us = draw(st.integers(0, 40)) * 1_000
        kind = draw(st.sampled_from(("trade", "delta", "ticker")))
        if kind == "trade":
            events.append(
                trade(at_us, seq=draw(st.integers(0, 3)), trade_id=f"t{i}", symbol=symbol)
            )
        elif kind == "delta":
            events.append(
                delta(at_us, update_id=i, cross_seq=draw(st.integers(0, 3)), symbol=symbol)
            )
        elif (symbol, at_us) not in tickers:  # one ticker per (symbol, instant): its dedup key
            tickers.add((symbol, at_us))
            events.append(ticker(at_us, symbol=symbol))
    gaps = [
        gap(
            start,
            start + draw(st.integers(1, 30_000)),
            stream=draw(st.sampled_from((*STREAMS, StreamKind.LIQUIDATIONS))),
            symbol=draw(st.sampled_from(SYMBOLS)),
            cause=draw(st.sampled_from(("ws_disconnect", "book_resync"))),
        )
        for start in draw(st.lists(st.integers(-20_000, END_US + 10_000), max_size=4))
    ]
    return events, gaps


def _read(harness: Harness, *, window_us: int, batch: int, cap: int) -> list[ReplayItem]:
    budget = cap * row_bytes(StreamKind.TRADES, 200) * len(SYMBOLS) * len(STREAMS)
    return asyncio.run(harness.read_all(batch=batch, budget_bytes=budget, window_us=window_us))


def _key(item: ReplayItem) -> tuple[object, ...]:
    if isinstance(item, ReplayGap):
        tiebreak = (item.gap_start_us, item.gap_end_us, item.cause)
        return (item.ts_us, 0, 0, STREAM_ORDINAL[item.stream], SYMBOLS.index(item.symbol), tiebreak)
    stream_ord = STREAM_ORDINAL[item.stream]
    return (item.ts_us, 1, item.seq, stream_ord, SYMBOLS.index(item.symbol), item.tiebreak)


@given(
    recording=recordings(),
    data=st.data(),
    window=st.integers(1, 30_000),
    batch=st.integers(1, 9),
)
def test_merge_is_total_complete_deduplicated_and_independent_of_tier_and_storage_order(
    recording: tuple[list[RecordedEvent], list[RecordedGap]],
    data: st.DataObject,
    window: int,
    batch: int,
) -> None:
    events, gaps = recording
    copies = data.draw(st.lists(st.sampled_from(events), max_size=8)) if events else []
    stored = data.draw(st.permutations(events + copies))  # a re-export repeats rows (21 Sec.5.3)
    busiest = max(Counter((e.symbol, e.stream, e.ts_us) for e in stored).values(), default=1)
    cap = data.draw(st.integers(busiest, busiest + 20))  # small caps: dense windows hit them
    req = request(symbols=SYMBOLS, streams=STREAMS, end_us=END_US)
    archived = Harness(cold=stored, gaps=gaps, req=req, archived=True)
    one_tier = request(symbols=SYMBOLS, streams=STREAMS, end_us=END_US, tier="questdb")
    single = Harness(hot=events, gaps=gaps, req=one_tier)

    got = _read(archived, window_us=window, batch=batch, cap=cap)

    assert got == _read(single, window_us=30_000, batch=64, cap=cap)
    keys = [_key(item) for item in got]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    replayed = [item for item in got if isinstance(item, RecordedEvent)]
    assert Counter(map(repr, replayed)) == Counter(map(repr, events))
    marked = {
        (m.symbol, m.stream, m.gap_start_us, m.gap_end_us, m.cause)
        for m in got
        if isinstance(m, ReplayGap)
    }
    want = {
        (g.symbol, g.stream, g.start_us, g.end_us, g.cause)
        for g in gaps
        if g.stream in STREAMS and g.start_us < T0 + END_US and g.end_us > T0
    }
    assert marked == want


@given(
    spans=st.lists(
        st.tuples(
            st.sampled_from(SYMBOLS),
            st.sampled_from(STREAMS),
            st.integers(-5_000, END_US),
            st.integers(1, END_US),
        ),
        max_size=8,
    )
)
def test_auto_reads_exactly_one_tier_or_refuses_before_reading(
    spans: list[tuple[str, StreamKind, int, int]],
) -> None:
    """ADR-0035 decision 4 as a property: never both tiers, and never a guess on a straddle."""
    req = request(symbols=SYMBOLS, streams=STREAMS, end_us=END_US)
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
