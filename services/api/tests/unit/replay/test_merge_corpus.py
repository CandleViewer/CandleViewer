"""A recorded corpus replays identically from either tier (E26-T02 ACs 1-2, C-13.5).

Recorded trade and order-book frames go through the production parsers and the E16 recorder's
own row builders, the shape both tiers store, and then `event_from_row`, as the tier readers
will. Archived whole, `auto` serves it from Parquet; archived only up to the middle of the book
data, the session is refused rather than stitched across tiers (ADR-0035 decision 4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.recorder.writer import delta_records, snapshot_records, trade_records
from candleviewer.replay import ReplayRequest, ReplayTierStraddle
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import RecordedEvent, Tiebreak, event_from_row
from tests._corpus import frames, normalize
from tests.unit.replay._events import T0, Harness, digest

STREAMS = (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA, StreamKind.ORDERBOOK_SNAPSHOT)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
#: The ruled order written out by hand (one symbol): the book streams share one sequence domain
#: and a snapshot precedes a delta of the same `cross_seq`; `seq` is only compared inside one.
_BOOK = (StreamKind.ORDERBOOK_DELTA, StreamKind.ORDERBOOK_SNAPSHOT)
_STREAM_ORDINAL = {
    StreamKind.TRADES: 0,
    StreamKind.ORDERBOOK_SNAPSHOT: 1,
    StreamKind.ORDERBOOK_DELTA: 2,
}


def _domain(event: RecordedEvent) -> str:
    return "book" if event.stream in _BOOK else event.stream.value


def ruled_key(event: RecordedEvent) -> tuple[int, int, int, int, Tiebreak]:
    domain = 1 if event.stream in _BOOK else 0
    return event.ts_us, domain, event.seq, _STREAM_ORDINAL[event.stream], event.tiebreak


def _recorded() -> list[RecordedEvent]:
    """BTCUSDT trades and 200 depth-200 book frames, stored as the recorder writes them."""
    out: list[RecordedEvent] = []
    prints = [
        ev
        for frame in frames("ws/clean_publicTrade_BTCUSDT.jsonl")
        for ev in normalize(frame)
        if isinstance(ev, TradePrint)
    ]
    for seq, tp in enumerate(prints, start=1):
        bus_event = SimpleNamespace(
            symbol=tp.symbol,
            ts_event=tp.ts_event_us,
            side=tp.side,
            price=tp.price,
            qty=tp.qty,
            notional=tp.price * tp.qty,
            trade_id=tp.trade_id,
            is_block_trade=tp.is_block_trade,
            seq=seq,
        )
        out += [event_from_row(StreamKind.TRADES, r.row) for r in trade_records(bus_event)]
    for ev in (e for frame in frames("ws/orderbook_BTCUSDT.jsonl")[:200] for e in normalize(frame)):
        if isinstance(ev, BookSnapshot):
            rows = snapshot_records(ev)
            out += [event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, r.row) for r in rows]
        elif isinstance(ev, BookDelta):
            out += [event_from_row(StreamKind.ORDERBOOK_DELTA, r.row) for r in delta_records(ev)]
    return out


def _request(events: list[RecordedEvent], tier: str) -> ReplayRequest:
    lo = min(e.ts_us for e in events)
    hi = max(e.ts_us for e in events) + 1
    return ReplayRequest.model_validate(
        {
            "symbols": ("BTCUSDT",),
            "streams": STREAMS,
            "start": EPOCH + timedelta(microseconds=lo),
            "end": EPOCH + timedelta(microseconds=hi),
            "source_tier": tier,
        }
    )


async def test_an_archived_recorded_window_equals_the_questdb_read_of_it() -> None:
    recorded = _recorded()
    archived = Harness(cold=recorded, req=_request(recorded, "auto"), archived=True)
    single = Harness(hot=recorded[::-1], req=_request(recorded, "questdb"))

    got = await archived.read_all(window_us=20_000_000)
    again = await single.read_all(batch=5)

    assert digest(got) == digest(again)
    assert len(got) == len(recorded) and archived.hot.reads == 0
    assert got == sorted(recorded, key=ruled_key)
    assert {e.stream for e in got if isinstance(e, RecordedEvent)} == set(STREAMS)


async def test_a_recorded_window_replays_in_seq_order_within_each_sequence_domain() -> None:
    """`seq` is the recorder's ingest counter for trades and the exchange `cross_seq` for the
    book: only comparable inside its own domain (24 Sec.13.7), so `(ts, seq)` never decreases
    per `(symbol, domain)` but may across them."""
    recorded = _recorded()

    got = await Harness(hot=recorded, req=_request(recorded, "questdb")).read_all()

    per_domain: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for event in got:
        assert isinstance(event, RecordedEvent)
        per_domain.setdefault((event.symbol, _domain(event)), []).append((event.ts_us, event.seq))
    assert set(per_domain) == {("BTCUSDT", "trades"), ("BTCUSDT", "book")}
    for pairs in per_domain.values():
        assert pairs == sorted(pairs)


async def test_a_recorded_window_straddling_the_archive_edge_is_refused_unread() -> None:
    recorded = _recorded()
    book = sorted(e.ts_us for e in recorded if e.stream is not StreamKind.TRADES)
    edge = book[len(book) // 2]  # inside the book's busiest part
    req = _request(recorded, "auto")
    split = Harness(
        cold=[e for e in recorded if e.ts_us < edge],
        hot=[e for e in recorded if e.ts_us >= edge],
        req=req,
    ).archive(req.start_us - T0, edge - T0)

    with pytest.raises(ReplayTierStraddle):
        await split.read_all(window_us=20_000_000)

    assert split.hot.reads == split.cold.reads == 0
