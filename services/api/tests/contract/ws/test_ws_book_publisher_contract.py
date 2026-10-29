"""E21-T01 (#604): the book publisher through the real `/ws` router and `SequencingHub`, where the
client validates every frame against `ws-schema.json` (`_harness`), over the recorded BTCUSDT
corpus replayed through the production `BookStream` and wiring (`ws_wiring.book_topic`'s parts).

- Gherkin "Independent depth subscriptions": `book.BTCUSDT.50` and `book.BTCUSDT.200` on one
  connection are two subscriptions with their own `snap` and `s` counter, each carrying exactly
  its own depth of levels per side, frame after frame.
- Kind 1 / kind 2 round-trip: in binary mode every `snap` (kind 1) and `d` (kind 2) decodes to a
  §14.1 body that validates, and applying the decoded deltas to the decoded snapshot gives the
  independent reference book's top `depth`, as the structured mode does.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.book.ws_topic import BookTopic
from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.orderbook_wiring import BookStream
from candleviewer.ws.binary import BOOK_DELTA, BOOK_SNAPSHOT
from candleviewer.ws_wiring import SnapshotRouter, book_delta_part, book_snapshot_source
from tests._corpus import TICKS, frames
from tests.contract.ws import _harness as h
from tests.unit.ws._seq_support import Book

RAW = frames("ws/orderbook_BTCUSDT.jsonl")
INSTRUMENT = SimpleNamespace(tick_size=TICKS[h.SYM], qty_step=Decimal("0.001"))
DEPTHS = (50, 200)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def _noop(_: object = None) -> None:
    return None


def _world() -> tuple[h.World, BookStream, BookTopic[Any], _Clock]:
    bus = Bus()
    stream = BookStream(
        bus=bus, env="live", set_desired=lambda _t: None, topic_for=book_topic,
        parse_frame=lambda f: parse_book_frame(f, TICKS.get), resubscribe=_noop,
        is_listed=lambda _s: True, touch=lambda _t: None, clock=lambda: 0.0,
        now_us=lambda: 0, rand=lambda: 0.0,
    )  # fmt: skip
    stream.acquire("contract", h.SYM)
    catalogue = SimpleNamespace(snapshot=lambda: {h.SYM: INSTRUMENT})
    ctx = SimpleNamespace(ingestion=SimpleNamespace(books=stream, instruments=catalogue))
    w = h.World()
    clock = _Clock()
    topic: BookTopic[Any] = BookTopic(
        book_snapshot_source(ctx),  # type: ignore[arg-type]  # the duck-typed app context
        w.hub.subscriptions, w.hub.publish, w.hub.upstream_desync, w.hub.flush_pending,
        book_delta_part, bus=bus, env="live", clock=clock,
    )  # fmt: skip
    w.registry.services.snapshots = SnapshotRouter({"book": topic})
    topic.open()
    return w, stream, topic, clock


def _levels(body: dict[str, Any], side: str) -> dict[Decimal, Decimal]:
    return {Decimal(p): Decimal(q) for p, q in body[side]}


@pytest.mark.parametrize("mode", h.MODES)
def test_independent_depth_subscriptions_and_kind_1_2_round_trip(mode: str) -> None:
    w, stream, topic, clock = _world()
    ref = Book(h.SYM)
    data = json.loads(RAW[0])["data"]
    ref.apply(data["b"], data["a"], reset=True)
    with h.connect(w) as c:
        w.call(stream.handle_frame, RAW[0])
        res = c.sub(*(h.entry("book", (), mode) | {"ch": f"book.{h.SYM}.{d}"} for d in DEPTHS))
        assert [r["ok"] for r in res["p"]["results"]] == [True, True]
        held: dict[str, dict[str, dict[Decimal, Decimal]]] = {}
        seqs: dict[str, list[int]] = {}
        for _ in DEPTHS:
            snap = c.next_of("snap")  # validated against book.schema.json by the harness
            if mode == "binary":
                assert h.cvwb_part(snap).body_kind == BOOK_SNAPSHOT
            body = h.structured_of(snap)
            depth = int(snap["ch"].rsplit(".", 1)[1])
            assert body.get("depth", depth) == depth  # tier 200: each served at its own depth
            assert len(body["bids"]) == len(body["asks"]) == depth
            held[snap["ch"]] = {s: _levels(body, s) for s in ("bids", "asks")}
            seqs[snap["ch"]] = [snap["s"]]
        sent = 0
        for line in RAW[1:120]:
            w.call(stream.handle_frame, line)
            data = json.loads(line)["data"]
            ref.apply(data["b"], data["a"])
            w.call(topic.pump)
            clock.now += 1.0  # every window due
            n = w.call(topic.tick)  # one `d` per subscription that got the window
            sent += n
            for d in (c.next_of("d") for _ in range(n)):
                if mode == "binary":
                    assert h.cvwb_part(d).body_kind == BOOK_DELTA
                body = h.structured_of(d)
                ch = d["ch"]
                for side in ("bids", "asks"):
                    for p, q in _levels(body, side).items():
                        if q == 0:
                            held[ch][side].pop(p, None)
                        else:
                            held[ch][side][p] = q
                seqs[ch].append(d["s"])
                depth = int(ch.rsplit(".", 1)[1])
                bids, asks = ref.top(depth)
                want = {"bids": bids, "asks": asks}
                for side in ("bids", "asks"):
                    assert held[ch][side] == {Decimal(p): Decimal(q) for p, q in want[side].items()}
                    # its own depth per side: the 200 window is the whole tier (fewer while
                    # the venue's book holds fewer), the 50 window always exactly 50
                    assert len(held[ch][side]) == min(depth, len(ref.top(200)[side == "asks"]))
    assert sent > 0
    for ch, s in seqs.items():
        assert len(s) > 1, ch
        assert s == list(range(s[0], s[0] + len(s))), ch  # its own counter, no gap
