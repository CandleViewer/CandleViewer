from __future__ import annotations

import json
from typing import Any

from candleviewer.ws.outbound import (
    DRAIN_PCT,
    Backpressure,
    LadderEvent,
    OutboundQueue,
    Queued,
    encode,
)
from candleviewer.ws.pacing import Pacer
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws._seq_support import ACC_A, Book, Conn, Source, validate


def _frame(t: str, ch: str | None = None, **p: Any) -> dict[str, Any]:
    frame: dict[str, Any] = {"t": t, "p": p}
    if ch is not None:
        frame["ch"] = ch
    return frame


def _setup(
    max_bytes: int = 6_000, max_frames: int = 40
) -> tuple[Conn, Pacer, OutboundQueue, Source]:
    """A connection whose emitter writes into a small outbound queue (every frame validated)."""
    source = Source()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        source.books[symbol] = Book(symbol)
    source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    conn = Conn(source, ACC_A)
    conn.clock.now = 100.0
    queue = OutboundQueue(max_bytes=max_bytes, max_frames=max_frames)

    def push(frame: dict[str, Any]) -> None:
        validate(frame)
        queue.push(encode(frame))

    conn.emitter.push = push
    return conn, Pacer(conn.emitter), queue, source


def _sub(conn: Conn, queue: OutboundQueue, ch: str) -> Subscription:
    _, sub = conn.sub({"ch": ch, "opts": {"encoding": "structured"}})
    _drain(queue)  # the initial snap
    return sub


def _orders(conn: Conn) -> Subscription:
    _, sub = conn.authz.admit({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert sub is not None
    sub.snapshot_pending = False
    return sub


def _bid(symbol: str, price: str) -> dict[str, Any]:
    return {"symbol": symbol, "depth": 50, "bids": [[price, "1"]], "asks": []}


def _drain(queue: OutboundQueue) -> list[dict[str, Any]]:
    out = []
    while (frame := queue.pop()) is not None:
        out.append(json.loads(frame.text))
    return out


# -- the queue ------------------------------------------------------------------------------------


def test_outbound_encode_classifies_lanes_and_droppable_frames() -> None:
    assert encode(_frame("d", "book.BTCUSDT.50")) == Queued(
        '{"t":"d","p":{},"ch":"book.BTCUSDT.50"}', False, "book", "book.BTCUSDT.50"
    )
    assert encode(_frame("snap", "trades.BTCUSDT")).topic == "trades.BTCUSDT"
    orders = encode(_frame("d", "orders"))
    assert (orders.priority, orders.family, orders.topic) == (True, "orders", None)
    assert encode(_frame("d", "system")).priority
    assert encode(_frame("ping")).priority
    assert encode(_frame("pong")).priority
    sub_ok = encode(_frame("sub_ok", "book.BTCUSDT.50"))
    assert (sub_ok.priority, sub_ok.topic) == (False, None)  # control frames are never dropped
    assert encode(_frame("err")).family is None


def test_outbound_priority_lane_drains_first_and_bytes_are_exact() -> None:
    queue = OutboundQueue()
    frames = [encode(_frame("d", "book.BTCUSDT.50")), encode(_frame("d", "orders"))]
    frames.append(encode(_frame("ping")))
    for frame in frames:
        queue.push(frame)
    assert queue.bytes == sum(len(f.text) for f in frames)
    assert [queue.pop() for _ in range(3)] == [frames[1], frames[2], frames[0]]
    assert queue.pop() is None
    assert queue.bytes == 0


def test_outbound_ready_event_tracks_emptiness() -> None:
    queue = OutboundQueue()
    assert not queue.ready.is_set()
    queue.push(encode(_frame("ping")))
    assert queue.ready.is_set()
    queue.pop()
    assert not queue.ready.is_set()


def test_outbound_pct_is_the_larger_of_the_byte_and_frame_shares() -> None:
    queue = OutboundQueue(max_bytes=1_000, max_frames=10)
    for _ in range(5):
        queue.push(Queued("x" * 10))
    assert queue.pct() == 50.0  # frames bind: 5 of 10, bytes only 50 of 1 000
    assert queue.pct(pending_bytes=890) == 94.0
    assert not queue.over_budget()
    assert queue.over_budget(pending_bytes=951)


def test_outbound_drop_removes_only_droppable_frames_of_the_topics() -> None:
    queue = OutboundQueue()
    kept = [encode(_frame("sub_ok", "book.BTCUSDT.50")), encode(_frame("d", "trades.BTCUSDT"))]
    queue.push(kept[0])
    queue.push(encode(_frame("d", "book.BTCUSDT.50", n=1)))
    queue.push(kept[1])
    queue.push(encode(_frame("d", "book.BTCUSDT.50", n=2)))
    assert queue.drop({"book.BTCUSDT.50"}) == 2
    assert queue.topics() == {"trades.BTCUSDT"}
    assert queue.bytes == sum(len(f.text) for f in kept)
    assert [queue.pop(), queue.pop()] == kept


def test_outbound_most_expensive_ranks_topics_by_queued_bytes() -> None:
    queue = OutboundQueue()
    for ch, size in (("a.X", 30), ("b.X", 300), ("c.X", 30), ("d.X", 3_000)):
        queue.push(encode(_frame("d", ch, pad="x" * size)))
    assert queue.most_expensive(3) == ["d.X", "b.X", "a.X"]


def test_outbound_holds_undroppable_only_for_orders_and_executions() -> None:
    queue = OutboundQueue()
    queue.push(encode(_frame("d", "system")))
    assert not queue.holds_undroppable()
    queue.push(encode(_frame("d", "executions")))
    assert queue.holds_undroppable()


# -- the ladder (§8.4) ----------------------------------------------------------------------------


def test_backpressure_under_budget_does_nothing() -> None:
    conn, pacer, queue, _ = _setup()
    book = _sub(conn, queue, "book.BTCUSDT.50")
    pacer.offer(book, _bid("BTCUSDT", "100"))
    assert Backpressure(queue, pacer).check([book]) == []


def test_backpressure_drops_the_offending_topics_and_marks_them_for_a_snapshot() -> None:
    conn, pacer, queue, _ = _setup(max_frames=3)
    book, other = _sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")
    for i in range(4):
        conn.clock.now += 1.0  # each update leaves at once: four queued frames
        pacer.offer(book, _bid("BTCUSDT", str(100 + i)))
    events = Backpressure(queue, pacer).check([book, other])
    assert events == [LadderEvent("drop", ("book.BTCUSDT.50",))]
    assert (book.snapshot_pending, book.pending_reason) == (True, "backpressure")
    assert pacer.resnapshot_required == {book.sub_id: book}
    assert not other.snapshot_pending  # it had nothing queued
    assert len(queue) == 0


def test_backpressure_counts_pending_state_against_the_budget() -> None:
    conn, pacer, queue, _ = _setup(max_bytes=400)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    pacer.offer(book, _bid("BTCUSDT", "90"))
    _drain(queue)
    pacer.offer(book, {"bids": [[str(p), "1"] for p in range(100, 140)], "asks": []})
    assert queue.bytes == 0 and pacer.pending_bytes > 400
    events = Backpressure(queue, pacer).check([book])
    assert events == [LadderEvent("drop", ("book.BTCUSDT.50",))]
    assert pacer.pending_bytes == 0


def test_backpressure_undroppable_backlog_closes_after_the_drop_naming_costs() -> None:
    """#412: the ladder drops first; only then may `orders` force a close, and the `bye` hint
    names the topics that were the most expensive when the overflow began."""
    conn, pacer, queue, _ = _setup(max_frames=30)
    book, orders = _sub(conn, queue, "book.BTCUSDT.50"), _orders(conn)
    for i in range(5):
        conn.clock.now += 1.0
        pacer.offer(book, _bid("BTCUSDT", str(100 + i)))
    for _ in range(31):
        pacer.offer(orders, {"orders": []})
    events = Backpressure(queue, pacer).check([book, orders])
    assert events == [
        LadderEvent("drop", ("book.BTCUSDT.50",)),
        LadderEvent("close", ("book.BTCUSDT.50",)),
    ]
    assert all(json.loads(f.text)["ch"] == "orders" for f in list(queue._priority))
    assert not orders.snapshot_pending  # never dropped


def test_backpressure_over_budget_without_orders_never_closes() -> None:
    conn, pacer, queue, _ = _setup(max_frames=2)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    for i in range(3):
        queue.push(encode(_frame("err", n=i)))  # control frames: never dropped
    pacer.offer(book, _bid("BTCUSDT", "100"))
    events = Backpressure(queue, pacer).check([book])
    assert [e.action for e in events] == ["drop"]


def test_backpressure_recovery_re_snapshots_instead_of_replaying() -> None:
    """#412: below 50 % a `snap` with reason `backpressure` goes out per dropped topic, and no
    stale queued delta is ever delivered."""
    conn, pacer, queue, source = _setup(max_frames=4)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    source.books["BTCUSDT"].apply([["100", "1"]], [])
    last = 0
    for i in range(5):
        conn.clock.now += 1.0
        pacer.offer(book, _bid("BTCUSDT", str(100 + i)))
        last = book.seq
    ladder = Backpressure(queue, pacer)
    assert [e.action for e in ladder.check([book])] == ["drop"]
    assert ladder.drain() == [LadderEvent("resnapshot", ("book.BTCUSDT.50",))]
    [snap] = _drain(queue)
    assert snap["t"] == "snap"
    assert snap["meta"] == {"reason": "backpressure", "source": "live", "previous_seq": last}
    assert snap["s"] == last + 1
    assert pacer.resnapshot_required == {}


def test_backpressure_drain_waits_until_the_queue_is_below_half() -> None:
    conn, pacer, queue, _ = _setup(max_frames=4)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    pacer.drop(book)
    for _ in range(2):
        queue.push(encode(_frame("err")))
    assert queue.pct() >= DRAIN_PCT
    ladder = Backpressure(queue, pacer)
    assert ladder.drain() == []
    _drain(queue)
    assert ladder.drain() == [LadderEvent("resnapshot", ("book.BTCUSDT.50",))]


def test_backpressure_slow_consumer_stays_within_the_budget() -> None:
    """#412: a client that never reads; after every update the ladder keeps the queue and the
    pending state within budget, with no close while `orders` is not backed up."""
    conn, pacer, queue, _ = _setup(max_bytes=3_000, max_frames=20)
    subs = [_sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")]
    ladder = Backpressure(queue, pacer)
    for i in range(400):
        conn.clock.now += 0.02
        sub = subs[i % 2]
        if sub.snapshot_pending:
            sub.snapshot_pending = False  # as if the backpressure snap had gone out
        pacer.offer(sub, _bid(sub.ch.split(".")[1], str(100 + i % 37)))
        pacer.tick(conn.clock.now)
        assert all(e.action != "close" for e in ladder.check(subs))
        assert not ladder.over_budget()


def test_backpressure_over_budget_with_nothing_droppable_drops_nothing() -> None:
    conn, pacer, queue, _ = _setup(max_frames=1)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    for _ in range(2):
        queue.push(encode(_frame("err")))
    assert Backpressure(queue, pacer).check([book]) == []
    assert not book.snapshot_pending


def test_backpressure_drain_keeps_a_topic_whose_snapshot_is_not_ready() -> None:
    conn, pacer, queue, source = _setup()
    book = _sub(conn, queue, "book.BTCUSDT.50")
    pacer.drop(book)
    source.unavailable.add("BTCUSDT")
    source.gen += 1  # the cached render is stale: the snapshot must be rebuilt, and cannot be
    assert Backpressure(queue, pacer).drain() == []
    assert pacer.resnapshot_required == {book.sub_id: book}


def test_outbound_budget_allows_exactly_its_bytes_and_frames() -> None:
    queue = OutboundQueue(max_bytes=20, max_frames=2)
    queue.push(Queued("x" * 10))
    queue.push(Queued("x" * 10))
    assert not queue.over_budget()  # 20 bytes, 2 frames: at the bound, not over it
    assert queue.over_budget(pending_bytes=1)
    queue.push(Queued(""))
    assert queue.over_budget()  # a third frame, though it adds no bytes
