from __future__ import annotations

import json
from typing import Any

import msgpack
import pytest

from candleviewer.ws.binary import encode_b64
from candleviewer.ws.codec import encode_server_frame
from candleviewer.ws.cvwb_vectors import vector_frames
from candleviewer.ws.metrics import cv_ws_overflow_total
from candleviewer.ws.outbound import (
    DRAIN_PCT,
    MAX_REDROPS,
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

RS = "bb000000-0000-4000-8000-000000000001"
BTC, ETH, TRADES = ("book.BTCUSDT.50", None), ("book.ETHUSDT.50", None), ("trades.BTCUSDT", None)


def _frame(t: str, ch: str | None = None, **p: Any) -> dict[str, Any]:
    frame: dict[str, Any] = {"t": t, "p": p}
    if ch is not None:
        frame["ch"] = ch
    return frame


def _setup(
    max_bytes: int = 6_000, max_frames: int = 40, max_frame_bytes: int | None = None
) -> tuple[Conn, Pacer, OutboundQueue, Source]:
    """A connection whose emitter writes into a small outbound queue (every frame validated)."""
    source = Source()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        source.books[symbol] = Book(symbol)
    source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    conn = Conn(source, ACC_A, max_frame_bytes=max_frame_bytes)
    conn.clock.now = 100.0
    queue = OutboundQueue(max_bytes=max_bytes, max_frames=max_frames)

    def push(frame: dict[str, Any]) -> None:
        validate(frame)
        queue.push(encode(frame))

    conn.emitter.push = push
    return conn, Pacer(conn.emitter), queue, source


def _oversized(
    max_frame_bytes: int | None = None,
) -> tuple[Conn, Pacer, OutboundQueue, Subscription, Backpressure]:
    """A 600 B budget and a `book.BTCUSDT.50` whose next snapshot (50 levels) never fits it."""
    conn, pacer, queue, source = _setup(max_bytes=600, max_frame_bytes=max_frame_bytes)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    source.books["BTCUSDT"].apply([[str(p), "1"] for p in range(100, 150)], [])
    source.gen += 1
    return conn, pacer, queue, book, Backpressure(queue, pacer)


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
        out.append(json.loads(frame.payload))
    return out


# -- the queue ------------------------------------------------------------------------------------


def test_outbound_encode_classifies_lanes_and_droppable_frames() -> None:
    assert encode(_frame("d", "book.BTCUSDT.50")) == Queued(
        '{"t":"d","p":{},"ch":"book.BTCUSDT.50"}', False, "book", BTC
    )
    assert encode(_frame("snap", "trades.BTCUSDT")).key == TRADES
    replay = encode(_frame("d", "book.BTCUSDT.50") | {"rs": RS})
    assert (replay.key, replay.droppable) == (("book.BTCUSDT.50", RS), True)  # D13
    orders = encode(_frame("d", "orders"))
    assert (orders.priority, orders.family, orders.key) == (True, "orders", ("orders", None))
    assert not orders.droppable  # a priority-lane data frame keeps its key, never dropped
    assert encode(_frame("d", "system")).priority
    assert encode(_frame("ping")).priority
    assert encode(_frame("pong")).priority
    sub_ok = encode(_frame("sub_ok", "book.BTCUSDT.50"))
    assert (sub_ok.priority, sub_ok.key) == (False, None)  # control frames are never dropped
    assert encode(_frame("err")).family is None


def test_outbound_encode_marks_only_backpressure_snapshots() -> None:
    meta = {"reason": "backpressure", "source": "live"}
    assert encode(_frame("snap", "book.BTCUSDT.50") | {"meta": meta}).resnap
    initial = _frame("snap", "book.BTCUSDT.50") | {"meta": {**meta, "reason": "initial"}}
    assert not encode(initial).resnap
    assert not encode(_frame("d", "book.BTCUSDT.50") | {"meta": meta}).resnap
    assert not encode(_frame("snap", "orders") | {"meta": meta}).resnap  # never dropped
    assert not encode(_frame("snap", "book.BTCUSDT.50") | {"meta": "backpressure"}).resnap


def test_outbound_resnap_stays_queued_until_its_last_chunk_leaves() -> None:
    queue = OutboundQueue()
    meta = {"meta": {"reason": "backpressure"}}
    chunks = [encode(_frame("snap", "book.BTCUSDT.50", n=i) | meta) for i in range(2)]
    for chunk in chunks:
        queue.push(chunk)
    queue.push(encode(_frame("snap", "book.ETHUSDT.50") | meta))
    assert queue.pop() == chunks[0]
    assert queue.resnap_queued(BTC)
    assert queue.pop() == chunks[1]
    assert not queue.resnap_queued(BTC)
    assert queue.resnap_queued(ETH)
    queue.drop({ETH})
    assert not queue.resnap_queued(ETH)


def test_outbound_priority_lane_drains_first_and_bytes_are_exact() -> None:
    queue = OutboundQueue()
    frames = [encode(_frame("d", "book.BTCUSDT.50")), encode(_frame("d", "orders"))]
    frames.append(encode(_frame("ping")))
    for frame in frames:
        queue.push(frame)
    assert queue.bytes == sum(f.size for f in frames)
    assert [queue.pop() for _ in range(3)] == [frames[1], frames[2], frames[0]]
    assert queue.pop() is None
    assert queue.bytes == 0


def test_outbound_key_bytes_count_only_droppable_frames() -> None:
    queue = OutboundQueue()
    book = encode(_frame("d", "book.BTCUSDT.50", pad="x" * 30))
    queue.push(book)
    queue.push(encode(_frame("sub_ok", "book.BTCUSDT.50")))
    queue.push(encode(_frame("d", "orders")))
    assert queue.key_bytes() == {BTC: book.size}


def test_outbound_encode_refuses_a_non_finite_number() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        encode(_frame("d", "heatmap.BTCUSDT", max_value=float("nan")))


def test_outbound_budget_counts_utf8_bytes_of_non_ascii_text() -> None:
    queue = OutboundQueue()
    frame = encode(_frame("d", "book.BTCUSDT.50", note="prix élevé €"))
    queue.push(frame)
    assert isinstance(frame.payload, str)
    assert queue.bytes == len(frame.payload.encode("utf-8"))  # what the writer actually sends


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
    assert queue.drop({BTC}) == 2
    assert queue.key_bytes().keys() == {TRADES}
    assert queue.bytes == sum(f.size for f in kept)
    assert [queue.pop(), queue.pop()] == kept


def test_outbound_encode_counts_the_msgpack_bytes_it_will_send() -> None:
    """#2887: on `cv.v1.msgpack` a frame is encoded once as MessagePack, its CVWB payload raw
    (`e: "b"`, §3.2), and counted at that length; it rides the lanes as on JSON."""
    part = dict(vector_frames())["trades"]
    frame = {"t": "d", "ch": "trades.BTCUSDT", "s": 1, "ts": 1, "e": "b64", "p": encode_b64(part)}
    packed = encode(frame, encode_server_frame)
    assert packed.payload == encode_server_frame(frame)
    assert msgpack.unpackb(packed.payload)["e"] == "b"
    assert packed.size == len(packed.payload) < encode(frame).size  # raw bytes, not base64 text
    assert (packed.priority, packed.family, packed.key) == (False, "trades", TRADES)
    queue = OutboundQueue()
    queue.push(packed)
    assert queue.bytes == len(packed.payload) and queue.key_bytes() == {TRADES: packed.size}


def test_outbound_encode_carries_the_fanout_stamp() -> None:
    assert encode(_frame("d", "book.BTCUSDT.50"), received=12.5).received == 12.5
    assert encode(_frame("d", "book.BTCUSDT.50")).received is None


def test_outbound_drop_keeps_a_replay_key_apart_from_its_live_key() -> None:
    """D13: dropping the live subscription's frames leaves the replay session's frames of the same
    `ch` queued (AC-28)."""
    queue = OutboundQueue()
    live = encode(_frame("d", "book.BTCUSDT.50"))
    replay = encode(_frame("d", "book.BTCUSDT.50") | {"rs": RS})
    queue.push(live)
    queue.push(replay)
    assert queue.drop({BTC}) == 1
    assert queue.key_bytes() == {("book.BTCUSDT.50", RS): replay.size}
    assert queue.pop() == replay


def test_outbound_drop_never_touches_the_priority_lane() -> None:
    queue = OutboundQueue()
    queue.push(encode(_frame("d", "orders")))
    assert queue.drop({("orders", None)}) == 0
    assert len(queue) == 1


def test_outbound_clear_discards_the_normal_lane_or_every_lane_exactly() -> None:
    queue = OutboundQueue()
    queue.push(encode(_frame("snap", "book.BTCUSDT.50") | {"meta": {"reason": "backpressure"}}))
    queue.push(encode(_frame("sub_ok")))
    kept = encode(_frame("d", "system", n=1))
    queue.push(kept)
    assert queue.clear(normal_only=True) == 2
    assert (len(queue), queue.bytes, queue.key_bytes()) == (1, kept.size, {})
    assert not queue.resnap_queued(BTC) and queue.ready.is_set()
    assert queue.clear() == 1
    assert (len(queue), queue.bytes, queue.ready.is_set()) == (0, 0, False)


def test_outbound_wake_sets_ready_with_nothing_queued() -> None:
    queue = OutboundQueue()
    queue.wake()
    assert queue.ready.is_set() and queue.pop() is None


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
        LadderEvent("close", ("book.BTCUSDT.50",), "budget"),
    ]
    assert all(json.loads(f.payload)["ch"] == "orders" for f in list(queue._priority))
    assert not orders.snapshot_pending  # never dropped


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
    """#412: a client that reads one frame in four updates; after every update the ladder keeps
    the queue and the pending state within budget, with no close while `orders` is not backed up.
    Every dropped topic recovers through the writer's `drain` after a send (#2998), never by hand,
    and once the client catches up both are live again."""
    conn, pacer, queue, _ = _setup(max_bytes=3_000, max_frames=20)
    subs = [_sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")]
    ladder = Backpressure(queue, pacer)
    events: list[LadderEvent] = []
    for i in range(400):
        conn.clock.now += 0.02
        sub = subs[i % 2]
        pacer.offer(sub, _bid(sub.ch.split(".")[1], str(100 + i % 37)))
        pacer.tick(conn.clock.now)
        events += ladder.check(subs)
        assert not ladder.over_budget()
        if i % 4 == 0:  # the writer's turn: it sends a frame if one is queued, then drains
            queue.pop()
            events += ladder.drain()
    for _ in range(100):  # the client catches up, the writer draining after each send
        if queue.pop() is None and not pacer.resnapshot_required:
            break
        events += ladder.drain()
    actions = {e.action for e in events}
    assert actions == {"drop", "resnapshot"}  # it was dropped and it recovered; it never closed
    assert not any(sub.snapshot_pending for sub in subs) and pacer.resnapshot_required == {}


def test_backpressure_drain_keeps_a_topic_whose_snapshot_is_not_ready() -> None:
    conn, pacer, queue, source = _setup()
    book = _sub(conn, queue, "book.BTCUSDT.50")
    pacer.drop(book)
    source.unavailable.add("BTCUSDT")
    source.gen += 1  # the cached render is stale: the snapshot must be rebuilt, and cannot be
    ladder = Backpressure(queue, pacer)
    assert ladder.drain() == []
    assert pacer.resnapshot_required == {book.sub_id: book}
    builds = source.builds
    assert ladder.drain() == [] and source.builds == builds  # parked: no retry per drain
    source.unavailable.clear()
    assert not ladder.unpark(["another"]) and ladder.unpark([book.sub_id])
    assert ladder.drain() == [LadderEvent("resnapshot", ("book.BTCUSDT.50",))]


def test_outbound_budget_allows_exactly_its_bytes_and_frames() -> None:
    queue = OutboundQueue(max_bytes=20, max_frames=2)
    queue.push(Queued("x" * 10))
    queue.push(Queued("x" * 10))
    assert not queue.over_budget()  # 20 bytes, 2 frames: at the bound, not over it
    assert queue.over_budget(pending_bytes=1)
    queue.push(Queued(""))
    assert queue.over_budget()  # a third frame, though it adds no bytes


def test_backpressure_control_frame_backlog_over_budget_closes() -> None:
    """S6: what the drop cannot shed (control frames here) still ends in the step-3 close."""
    conn, pacer, queue, _ = _setup(max_frames=2)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    for i in range(3):
        queue.push(encode(_frame("err", n=i)))
    pacer.offer(book, _bid("BTCUSDT", "100"))
    events = Backpressure(queue, pacer).check([book])
    assert [e.action for e in events] == ["drop", "close"]


def test_backpressure_nothing_droppable_over_budget_closes_without_a_drop() -> None:
    conn, pacer, queue, _ = _setup(max_frames=1)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    for _ in range(2):
        queue.push(encode(_frame("err")))
    closes = _overflow("close_budget")
    ladder = Backpressure(queue, pacer)
    assert ladder.check([book]) == [LadderEvent("close", (), "budget")]
    assert not book.snapshot_pending
    queue.push(encode(_frame("bye")))  # the wiring's `bye` push runs `check` again
    assert ladder.check([book]) == ladder.drain() == []
    assert _overflow("close_budget") == closes + 1  # one per close, whatever the hint names


def test_backpressure_drops_frames_of_pending_and_unsubscribed_topics() -> None:
    conn, pacer, queue, _ = _setup(max_frames=2)
    book, other = _sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")
    pacer.offer(book, _bid("BTCUSDT", "100"))
    pacer.offer(other, _bid("ETHUSDT", "100"))
    queue.push(encode(_frame("d", "trades.BTCUSDT")))  # no subscription left for it
    book.snapshot_pending = True  # e.g. a client resync is under way
    events = Backpressure(queue, pacer).check([book, other])
    assert events == [LadderEvent("drop", ("book.ETHUSDT.50",))]
    assert queue.key_bytes() == {}
    assert pacer.resnapshot_required == {other.sub_id: other}  # the pending one is not re-marked


def test_backpressure_close_hint_counts_pending_state() -> None:
    """ETH has the larger queued frame, but BTC's pending window makes it the most expensive."""
    conn, pacer, queue, _ = _setup(max_frames=2)
    book, other = _sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")
    levels = [[str(p), "1"] for p in range(1, 6)]
    pacer.offer(other, {"symbol": "ETHUSDT", "depth": 50, "bids": levels, "asks": []})
    pacer.offer(book, _bid("BTCUSDT", "90"))
    window = [[str(p), "1"] for p in range(100, 160)]
    pacer.offer(book, {"symbol": "BTCUSDT", "depth": 50, "bids": window, "asks": []})
    orders = _orders(conn)
    for _ in range(3):
        pacer.offer(orders, {"orders": []})
    events = Backpressure(queue, pacer).check([book, other, orders])
    assert events[-1] == LadderEvent("close", ("book.BTCUSDT.50", "book.ETHUSDT.50"), "budget")


def test_backpressure_close_hint_sums_a_topics_live_and_replay_frames_once() -> None:
    """D13: frames are keyed by (`ch`, replay session); the `bye` hint names topics, so a live and
    a replay subscription of one `ch` count together and the topic is named once."""
    conn, pacer, queue, _ = _setup(max_frames=3)
    orders = _orders(conn)
    live = encode(_frame("d", "trades.BTCUSDT", pad="x"))
    replay = encode(_frame("d", "trades.BTCUSDT", pad="x") | {"rs": RS})
    eth = encode(_frame("d", "trades.ETHUSDT", pad="x" * 60))
    assert max(live.size, replay.size) < eth.size < live.size + replay.size
    for frame in (live, replay, eth):
        queue.push(frame)
    for _ in range(4):
        pacer.offer(orders, {"orders": []})
    events = Backpressure(queue, pacer).check([orders])
    assert events == [LadderEvent("close", ("trades.BTCUSDT", "trades.ETHUSDT"), "budget")]


def test_backpressure_close_hint_names_at_most_five_topics_largest_first() -> None:
    conn, pacer, queue, _ = _setup(max_frames=7)
    orders = _orders(conn)
    for i in range(7):  # seven topics, each queued frame larger than the last
        queue.push(encode(_frame("d", f"trades.SYM{i}", pad="x" * (10 * i))))
    for _ in range(8):
        pacer.offer(orders, {"orders": []})
    events = Backpressure(queue, pacer).check([orders])
    assert events == [
        LadderEvent("close", tuple(f"trades.SYM{i}" for i in (6, 5, 4, 3, 2)), "budget")
    ]


def test_backpressure_snapshot_that_never_fits_ends_in_a_close() -> None:
    """A `backpressure` snap larger than the budget cannot loop forever."""
    _, pacer, _, book, ladder = _oversized()
    pacer.drop(book)
    events: list[LadderEvent] = []
    for _ in range(MAX_REDROPS):
        assert ladder.drain() == [LadderEvent("resnapshot", ("book.BTCUSDT.50",))]
        events = ladder.check([book])
    assert events == [
        LadderEvent("drop", ("book.BTCUSDT.50",)),
        LadderEvent("close", ("book.BTCUSDT.50",), "redrop"),
    ]


def test_backpressure_a_delivered_snapshot_resets_the_redrop_count() -> None:
    _, pacer, queue, book, ladder = _oversized()
    pacer.drop(book)
    for _ in range(MAX_REDROPS - 1):  # dropped again twice before it ever left
        ladder.drain()
        assert [e.action for e in ladder.check([book])] == ["drop"]
    ladder.drain()
    _drain(queue)  # this time the writer sent it: the topic recovered
    pacer.drop(book)
    ladder.drain()
    assert [e.action for e in ladder.check([book])] == ["drop"]  # a fresh count, not the third


@pytest.mark.parametrize("drained", [True, False], ids=["drain-after-send", "check-first"])
def test_backpressure_busy_topic_whose_snapshot_was_sent_never_closes(drained: bool) -> None:
    """#2503 review: deltas queued behind a sent `backpressure` snap must not make the topic's
    next drop count as a redrop, however often the cycle repeats; the check may also run while
    the writer is still sending, before its `drain`."""
    conn, pacer, queue, _ = _setup(max_frames=4)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    ladder = Backpressure(queue, pacer)
    pacer.drop(book)
    for i in range(MAX_REDROPS + 1):
        assert ladder.drain() == [LadderEvent("resnapshot", ("book.BTCUSDT.50",))]
        conn.clock.now += 1.0
        pacer.offer(book, _bid("BTCUSDT", str(100 + i)))  # queued behind the snap
        snap = queue.pop()
        assert snap is not None and json.loads(snap.payload)["t"] == "snap"  # the writer sends it
        if drained:
            assert ladder.drain() == []
        for j in range(4):  # the topic stays busy until the queue is over budget again
            conn.clock.now += 1.0
            pacer.offer(book, _bid("BTCUSDT", str(200 + j)))
        assert ladder.check([book]) == [LadderEvent("drop", ("book.BTCUSDT.50",))]


def test_backpressure_forgets_the_counts_of_ended_subscriptions() -> None:
    conn, pacer, queue, book, ladder = _oversized()
    other = _sub(conn, queue, "book.ETHUSDT.50")
    pacer.drop(book)
    ladder.drain()
    assert [e.action for e in ladder.check([book, other])] == ["drop"]
    assert ladder._redrops == {book.sub_id: 1}
    ladder.drain()  # a new snapshot of it is queued again; then the client unsubscribes
    pacer.forget(book.sub_id)
    queue.push(encode(_frame("d", "book.ETHUSDT.50", pad="x" * 700)))
    assert [e.action for e in ladder.check([other])] == ["drop"]
    assert (ladder._redrops, ladder._snapped) == ({}, {})


# -- #2503 fable review: a check run by the pushes of the snapshot `drain` is queuing ---------


def _checking_push(conn: Conn, ladder: Backpressure, subs: list[Subscription]) -> None:
    """The wiring the module asks for: `check` after every push, the snapshot's included."""
    pushed = conn.emitter.push

    def push(frame: dict[str, Any]) -> None:
        pushed(frame)
        ladder.check(subs)

    conn.emitter.push = push


def test_backpressure_check_from_the_snapshot_pushes_never_stalls_and_still_closes() -> None:
    conn, pacer, _, book, ladder = _oversized()
    _checking_push(conn, ladder, [book])
    pacer.drop(book)
    events: list[LadderEvent] = []
    for _ in range(MAX_REDROPS):
        assert book.snapshot_pending and book.sub_id in pacer.resnapshot_required  # not stuck
        events = ladder.drain()
    assert events == [
        LadderEvent("resnapshot", ("book.BTCUSDT.50",)),
        LadderEvent("drop", ("book.BTCUSDT.50",)),
        LadderEvent("close", ("book.BTCUSDT.50",), "redrop"),
    ]


def test_backpressure_held_check_drops_a_chunked_snapshot_whole() -> None:
    conn, pacer, queue, book, ladder = _oversized(max_frame_bytes=450)
    _checking_push(conn, ladder, [book])
    pacer.drop(book)
    assert [e.action for e in ladder.drain()] == ["resnapshot", "drop"]
    assert _drain(queue) == []  # no chunk of the dropped snapshot is left behind
    assert ladder._redrops == {book.sub_id: 1} and book.sub_id in pacer.resnapshot_required


def test_backpressure_drain_sends_each_snapshot_before_queuing_the_next() -> None:
    """Round 6: a client that reads everything recovers two snapshots that only fit one by one."""
    conn, pacer, queue, source = _setup(max_bytes=1_000)
    book, other = _sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")
    for symbol, sub, levels in (("BTCUSDT", book, 12), ("ETHUSDT", other, 48)):  # 377 B, 809 B
        source.books[symbol].apply([[str(p), "1"] for p in range(100, 100 + levels)], [])
        pacer.drop(sub)
    source.gen += 1
    ladder = Backpressure(queue, pacer)
    _checking_push(conn, ladder, [book, other])
    sent: list[str] = []
    for _ in range(MAX_REDROPS + 1):
        assert all(event.action == "resnapshot" for event in ladder.drain())
        sent += [frame["ch"] for frame in _drain(queue) if frame["t"] == "snap"]
    assert sent == ["book.BTCUSDT.50", "book.ETHUSDT.50"] and ladder._redrops == {}


def _overflow(reason: str) -> float:
    value: float = cv_ws_overflow_total.labels(reason=reason)._value.get()
    return value


def test_backpressure_sheds_the_window_of_a_topic_another_sender_pended() -> None:
    """The window predates that sender's pending `snap`: it is shed, never counted to a close."""
    conn, pacer, queue, _ = _setup(max_bytes=400)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    pacer.offer(book, _bid("BTCUSDT", "90"))
    _drain(queue)
    pacer.offer(book, {"bids": [[str(p), "1"] for p in range(100, 140)], "asks": []})
    book.snapshot_pending, book.pending_reason = True, "client_resync"
    assert Backpressure(queue, pacer).check([book]) == []
    assert pacer.pending_bytes == 0 and pacer.resnapshot_required == {}


def test_backpressure_records_each_step_with_the_close_trigger_as_its_reason() -> None:
    """#2504 §8.4 step 4: `cv_ws_overflow_total{reason}`, per topic for `drop` / `resnapshot`."""
    reasons = ("drop", "resnapshot", "close_budget", "close_redrop")
    before = [_overflow(r) for r in reasons]
    _, pacer, _, book, ladder = _oversized()
    pacer.drop(book)
    for _ in range(MAX_REDROPS):
        ladder.drain()
        ladder.check([book])
    assert ladder.drain() == ladder.check([book]) == []  # the close fired: nothing more
    assert [_overflow(r) - b for r, b in zip(reasons, before, strict=True)] == [3, 3, 0, 1]
    assert [LadderEvent("close", (), t).reason for t in ("budget", "redrop")] == list(reasons[2:])


def test_backpressure_sheds_a_paused_topic_without_marking_it() -> None:
    """D16 (§8.4 step 1): over budget, a paused topic's queued frames and throttle window are
    shed without the `backpressure` mark, uncounted: its resume re-snapshots it."""
    conn, pacer, queue, _ = _setup(max_frames=3)
    book = _sub(conn, queue, "book.BTCUSDT.50")
    for i in range(3):
        conn.clock.now += 1.0  # each update leaves at once: three queued frames
        pacer.offer(book, _bid("BTCUSDT", str(100 + i)))
    pacer.offer(book, _bid("BTCUSDT", "200"))  # and one in its window
    assert pacer.pending_bytes > 0
    book.effective["paused"] = True  # as `ctl {paused: true}` leaves it
    queue.push(encode(_frame("err")))  # one over the budget
    drops = _overflow("drop")
    assert Backpressure(queue, pacer).check([book]) == []
    assert (book.snapshot_pending, pacer.resnapshot_required) == (False, {})
    assert _overflow("drop") == drops
    assert queue.key_bytes() == {} and pacer.pending_bytes == 0 and len(queue) == 1


def test_backpressure_drain_deletes_an_entry_no_longer_pending_or_subscribed_unsent() -> None:
    """`drain` sends a `backpressure` snapshot only for a subscription still marked for it and,
    given the connection's subscriptions, still one of them: an entry another path resnapshotted,
    or one whose topic was unsubscribed (WS-E02), is deleted unsent."""
    conn, pacer, queue, _ = _setup()
    book, other = _sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")
    pacer.drop(book)
    pacer.drop(other)
    conn.emitter.snapshot(book, "reconfigure")  # another path sent the book its snapshot
    assert conn.authz.unsubscribe("book.ETHUSDT.50")
    _drain(queue)
    assert Backpressure(queue, pacer).drain(conn.authz.by_id) == []
    assert pacer.resnapshot_required == {} and _drain(queue) == []


def test_backpressure_drain_from_a_snapshot_push_is_a_no_op() -> None:
    """#2998: a `drain` run from a push of the snapshot `drain` is queuing returns nothing and
    queues nothing, so one call queues one snapshot and never nests."""
    conn, pacer, queue, _ = _setup()
    book, other = _sub(conn, queue, "book.BTCUSDT.50"), _sub(conn, queue, "book.ETHUSDT.50")
    ladder = Backpressure(queue, pacer)
    pushed, inner = conn.emitter.push, []

    def push(frame: dict[str, Any]) -> None:
        pushed(frame)
        inner.append(ladder.drain())

    conn.emitter.push = push
    pacer.drop(book)
    pacer.drop(other)
    assert ladder.drain() == [LadderEvent("resnapshot", ("book.BTCUSDT.50",))]
    assert inner == [[]] and [frame["ch"] for frame in _drain(queue)] == ["book.BTCUSDT.50"]
    assert list(pacer.resnapshot_required) == [other.sub_id]


def test_backpressure_a_snapshot_that_raises_leaves_no_held_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2998: a push that raises mid-snapshot ends `drain` without its held check and leaves
    none behind, so the next `drain` (its snapshot not ready) runs no stale check."""
    conn, pacer, queue, source = _setup()
    book = _sub(conn, queue, "book.BTCUSDT.50")
    ladder = Backpressure(queue, pacer)
    pushed = conn.emitter.push

    def push(frame: dict[str, Any]) -> None:
        pushed(frame)
        ladder.check([book])  # held: `drain` is queuing a snapshot
        raise RuntimeError("push failed")

    conn.emitter.push = push
    pacer.drop(book)
    with pytest.raises(RuntimeError):
        ladder.drain()
    assert ladder._deferred is None
    conn.emitter.push = pushed
    checks: list[object] = []
    monkeypatch.setattr(ladder, "check", checks.append)
    source.unavailable.add("BTCUSDT")
    source.gen += 1
    pacer.drop(book)
    assert ladder.drain() == [] and checks == []
