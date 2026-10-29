"""E21-T01 (#604) test plan "Integration": the recorded depth-200 (BTCUSDT) and depth-50 (ETHUSDT)
captures replayed through the production `BookStream` and parser, no network (C-13.5). Each
replay holds exactly one resync incident, so exactly one `BookDesyncEvent` reaches
`{env}.health.{symbol}.book_desync`, and the book after the resync is the independent reference.

- BTCUSDT `orderbook.200`: the seeded `u` hole at frame 2700 is a `sequence_gap`; while the
  snapshot is pending an out-of-order (older) delta arrives and is never applied; the fresh
  snapshot (the corpus's reset levels, re-stamped at the last good `u`, the REST oracle) and the
  next delta rebuild the book, which equals an independent dict model.
- ETHUSDT `orderbook.50`: its book crosses at `u = 3` (`test_contract_orderbook.py` names that
  window parse-level evidence only), a `crossed` desync, never clamped; the frames after it,
  the seeded `u` gap among them, wait in the pending buffer and cause no second incident.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from candleviewer.book.models import BookDesyncEvent, BookPhase
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, TopicPattern
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import frames

BTC = frames("ws/orderbook_BTCUSDT.jsonl")
ETH = frames("ws/gap_orderbook_ETHUSDT.jsonl")
HOLE_AT, RESET_AT = 2700, 4000  # the corpus manifest's documented events
TICK = {"BTCUSDT": Decimal("0.1"), "ETHUSDT": Decimal("0.01")}


async def _noop(_: object = None) -> None:
    return None


def _rig(symbol: str, depth: int = 200) -> tuple[BookStream, Any]:
    bus = Bus()
    desyncs = bus.subscribe(
        "t-desync", TopicPattern(env="live", domain="health", symbol=symbol, detail="book_desync"),
        QueuePolicy.NEVER_DROP, maxsize=1024,
    )  # fmt: skip
    stream = BookStream(
        bus=bus, env="live", set_desired=lambda _t: None, topic_for=book_topic,
        parse_frame=lambda f: parse_book_frame(f, TICK.get), resubscribe=_noop,
        is_listed=lambda _s: True, touch=lambda _t: None, clock=lambda: 0.0,
        now_us=lambda: 0, rand=lambda: 0.0, default_depth=depth,
    )  # fmt: skip
    stream.acquire("replay", symbol)
    return stream, desyncs


def _drain(q: Any) -> list[Any]:
    out = []
    while q.qsize():
        out.append(q.get_nowait())
    return out


def _model(levels: Any, side: dict[int, Decimal]) -> None:
    for p, q in levels:
        ticks = int(Decimal(p) / TICK["BTCUSDT"])
        if Decimal(q) == 0:
            side.pop(ticks, None)
        else:
            side[ticks] = Decimal(q)


async def test_btc_200_replay_has_one_desync_and_a_correct_book_after_resync() -> None:
    stream, desyncs = _rig("BTCUSDT")
    for line in BTC[: HOLE_AT + 1]:
        await stream.handle_frame(line)
    assert stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING
    await stream.handle_frame(BTC[HOLE_AT - 10])  # out of order: older than any snapshot to come
    hole = parse_book_frame(BTC[HOLE_AT], TICK.get)
    assert isinstance(hole, BookDelta)
    reset: dict[str, Any] = json.loads(BTC[RESET_AT])
    reset["data"]["u"] = hole.prev_update_id  # the fresh snapshot at the last good `u`
    await stream.handle_frame(json.dumps(reset))
    nxt: dict[str, Any] = json.loads(BTC[HOLE_AT + 1])
    nxt["data"]["u"] = hole.prev_update_id + 1  # the next delta chains onto it
    await stream.handle_frame(json.dumps(nxt))
    assert stream.phase("BTCUSDT") is BookPhase.LIVE
    events = _drain(desyncs)
    assert [type(e) for e in events] == [BookDesyncEvent]
    assert (events[0].reason, events[0].got_update_id) == ("sequence_gap", hole.update_id)
    bids: dict[int, Decimal] = {}
    asks: dict[int, Decimal] = {}
    for side, key in ((bids, "b"), (asks, "a")):
        _model(reset["data"][key], side)
        _model(nxt["data"][key], side)
    engine = stream.engine("BTCUSDT")
    assert engine is not None and engine.book is not None
    assert engine.book.as_dicts() == (bids, asks)


async def test_eth_50_replay_crosses_once_and_rebuilds_from_the_fresh_snapshot() -> None:
    stream, desyncs = _rig("ETHUSDT", 50)  # the capture's tier
    for line in ETH:
        await stream.handle_frame(line)
    events = _drain(desyncs)
    assert [(e.reason, e.depth, e.prev_update_id) for e in events] == [("crossed", 50, 2)]
    assert stream.phase("ETHUSDT") is BookPhase.SNAPSHOT_PENDING  # never clamped, never patched
    fresh: dict[str, Any] = json.loads(ETH[0])
    last_u = json.loads(ETH[-1])["data"]["u"]
    fresh["data"]["u"] = last_u  # the venue's re-snapshot after the buffered tail
    await stream.handle_frame(json.dumps(fresh))
    assert stream.phase("ETHUSDT") is BookPhase.LIVE and _drain(desyncs) == []
    view = stream.view("ETHUSDT", 50)
    assert view is not None and isinstance(view.snapshot, BookSnapshot)
    want = [[format(lv.price, "f"), format(lv.qty, "f")] for lv in view.snapshot.bids]
    assert want == fresh["data"]["b"] and view.snapshot.update_id == last_u
