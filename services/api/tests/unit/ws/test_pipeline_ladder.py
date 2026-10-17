"""E17-T03 (#412, S2b): the §8.4 overflow ladder in the budgeted pipeline, flag on
(`23-ws-protocol.md` §3.6, §4.3, §8.4). The router tests run the real `/ws` router behind `_Wire`
(`test_pipeline_outbound`); the unit tests drive a pipeline attached to a `_seq_support.Conn`. No
sleeps: every wait is on a frame or an event, bounded by `asyncio.timeout`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.audit.models import Severity
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.pipeline import ConnectionPipeline, slow_consumer_bye
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws._seq_support import ACC_A, Book, Conn, Source
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _DEADLINE_S,
    _MARK,
    _closes,
    _overflow,
    _pipe,
    _queued,
    _Rig,
    _rows,
    _Wire,
)

_TRADES = "trades.BTCUSDT"
_STEPS = ("drop", "resnapshot", "close_budget", "close_redrop")


def _counts(since: list[float] | None = None) -> list[float]:
    """`cv_ws_overflow_total` per ladder step, or what each grew by `since`."""
    now = [_overflow(reason) for reason in _STEPS]
    return now if since is None else [a - b for a, b in zip(now, since, strict=True)]


def _attached(
    levels: int = 2, max_frame_bytes: int | None = None, **config: Any
) -> tuple[ConnectionPipeline, list[str], Conn]:
    """A pipeline attached to a `Conn` (a book of `levels` bids) whose emitter pushes into it,
    with a close that takes the terminal slot as `_Connection.close_with` does."""
    source = Source()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        source.books[symbol] = Book(symbol)
        source.books[symbol].apply([[str(100 + i), "1"] for i in range(levels)], [])
    conn = Conn(source, ACC_A, max_frame_bytes=max_frame_bytes)
    asked: list[str] = []

    def close(reason: str, *, bye: dict[str, Any] | None = None) -> None:
        asked.append(reason)
        frame = bye or bye_frame(reason, now_ms=BASE_MS)
        pipe.close(frame, int(frame["p"]["code"]), flush=reason != "slow_consumer")

    pipe = ConnectionPipeline(
        encoding="cv.v1.json",
        config=BackpressureConfig(**config),
        close=close,
        wall_ms=lambda: BASE_MS,
        connection_id="ws_test",
    )
    pipe.attach(conn.authz, conn.emitter)
    conn.emitter.push = pipe.push
    return pipe, asked, conn


def _bid(i: int) -> dict[str, Any]:
    return {"symbol": "BTCUSDT", "depth": 50, "bids": [[f"{90 - i}", "1"]], "asks": []}


def _structured(conn: Conn, ch: str) -> Subscription:
    _, sub = conn.sub({"ch": ch, "opts": {"encoding": "structured"}})
    return sub


# -- the pipeline alone --------------------------------------------------------------------------


async def test_check_never_splits_a_chunked_snapshot() -> None:
    """§3.6: no ladder check runs between the chunks of a snapshot being queued. With six book
    deltas queued (the budget, exactly), a client-resync snapshot of several chunks is checked
    after its last chunk, so the drop takes the whole set with the deltas: never its head, with
    its tail left queued. The `backpressure` re-snapshot after it is a new set, under a new `id`
    (§7.2, D17)."""
    pipe, asked, conn = _attached(50, max_frame_bytes=450, max_frames=6)
    book = _structured(conn, _BOOK)
    initial = _queued(pipe)
    assert len(initial) > 1 and initial[-1]["s"] == 1  # a chunk set, sent
    for i in range(6):
        conn.emitter.delta(book, _bid(i))
    seen: list[dict[str, Any]] = []
    push = pipe.push

    def recording(frame: dict[str, Any]) -> None:
        seen.append(frame)
        push(frame)

    conn.emitter.push = recording
    conn.emitter.snapshot(book, "client_resync")
    assert len(seen) > 1 and [f["s"] is None for f in seen] == [True] * (len(seen) - 1) + [False]
    assert (len(pipe.queue), book.pending_reason, asked) == (0, "backpressure", [])
    cut = {f["id"] for f in seen}
    seen.clear()
    pipe.service(0.0)
    again = _queued(pipe)
    assert again == seen and len(again) > 1 and again[-1]["meta"]["reason"] == "backpressure"
    assert len({f["id"] for f in again}) == 1 and again[0]["id"] not in cut


async def test_a_dropping_check_wakes_the_writer_and_never_drains_itself() -> None:
    """§8.4 step 2's cadence, push side: a check that drops queues no snapshot from inside the
    push (no recursion into `drain`); it wakes the writer, whose turn (`service`) drains, and
    only the connection's own subscriptions: an unsubscribed topic gets no snapshot (WS-E02)."""
    pipe, asked, conn = _attached(max_frames=4)
    book, eth = _structured(conn, _BOOK), _structured(conn, "book.ETHUSDT.50")
    _queued(pipe)
    for i in range(5):
        conn.emitter.delta(book, _bid(i))  # the fifth is one over: the book is dropped
        conn.emitter.delta(eth, _bid(i) | {"symbol": "ETHUSDT"})
    assert pipe.ladder is not None and book.sub_id in pipe.ladder.pacer.resnapshot_required
    assert (len(pipe.queue), pipe.queue.ready.is_set(), asked) == (0, True, [])
    assert conn.authz.unsubscribe("book.ETHUSDT.50")
    pipe.service(0.0)
    assert [(f["ch"], f["meta"]["reason"]) for f in _queued(pipe)] == [(_BOOK, "backpressure")]
    pipe.service(0.0)
    assert _queued(pipe) == [] and pipe.ladder.pacer.resnapshot_required == {}
    pipe.ladder._parked.add(book.sub_id)  # a hub `flush_pending` naming a parked topic wakes too
    pipe.queue.ready.clear()
    assert conn.emitter.on_rebuild is not None
    conn.emitter.on_rebuild([book])
    assert pipe.queue.ready.is_set() and not pipe.ladder._parked


async def test_overflow_steps_are_counted_once() -> None:
    """§8.4 step 4: the ladder counts each step once (a drop and a re-snapshot per topic, one
    close) and the pipeline never counts them again, nor anything pushed after the close; before
    `auth_ok` the pipeline's own step 3 counts `close_budget` once."""
    before = _counts()
    pipe, asked, conn = _attached(max_frames=4)
    book = _structured(conn, _BOOK)
    for i in range(4):
        conn.emitter.delta(book, _bid(i))  # with the snapshot, one over
    pipe.service(0.0)
    _queued(pipe)
    _, orders = conn.authz.admit({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert orders is not None
    orders.snapshot_pending = False
    for _ in range(7):
        conn.emitter.delta(orders, {"orders": []})  # undroppable: the fifth closes, then nothing
    assert asked == ["slow_consumer"] and _counts(before) == [1, 1, 1, 0]
    early, early_asked = _pipe(max_frames=1)
    for _ in range(2):  # the second is one over
        early.push({"t": "pong", "ts": 1, "p": {}})
    assert [reason for reason, _ in early_asked] == ["slow_consumer"]
    assert _counts(before) == [1, 1, 2, 0]


# -- through the router --------------------------------------------------------------------------


async def test_ladder_order_drop_then_backpressure_snap_below_half_then_no_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.4 steps 1 and 2 through the router: over budget the book's queued deltas are dropped at
    once (counted, the topic marked). The writer drains after each send, and queues the
    `backpressure` snapshot at the first drain that finds the queue below half; the `system`
    frames ahead of it are delivered, and nothing closes."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire()
    before = _counts()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        pipe, emitter = conn.pipeline, conn.emitter
        assert pipe is not None and pipe.ladder is not None and emitter is not None
        drains: list[int] = []
        depths: list[float] = []
        drain, snapshot = pipe.ladder.drain, emitter.snapshot

        def drain_spy(live: Any = None) -> Any:
            drains.append(len(sock.raw))  # how many frames the socket had then
            return drain(live)

        def snapshot_spy(sub: Subscription, reason: Any) -> bool:
            depths.append(pipe.queue.pct())
            return snapshot(sub, reason)

        monkeypatch.setattr(pipe.ladder, "drain", drain_spy)
        monkeypatch.setattr(emitter, "snapshot", snapshot_spy)
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()  # the writer holds it: what follows queues behind it
        start = len(sock.raw)
        for _ in range(4):
            rig.hub.broadcast_system({"kind": "tick"})
        for i in range(5):
            rig.book_delta(i)  # in one turn: the fifth makes nine, one over
        assert conn.authz is not None
        (book,) = conn.authz.by_id.values()
        assert (book.pending_reason, len(pipe.queue), drains) == ("backpressure", 4, [])
        sock.release()
        frames = await sock.next(6)
        assert not conn.closing
        handler.cancel()
        await asyncio.wait({handler})
    assert [f["p"].get("kind") for f in frames[:5]] == ["held"] + ["tick"] * 4
    assert (frames[5]["t"], frames[5]["meta"]["reason"]) == ("snap", "backpressure")
    assert drains == [start + 1, start + 2] and depths == [37.5]  # 4 of 8 waited; 3 of 8 went
    assert _counts(before) == [1, 1, 0, 0]


async def test_orders_backlog_over_budget_closes_4429_with_hint_and_warning_audit() -> None:
    """§8.4 steps 1, 3 and 4: over budget the ladder drops the book first; the `orders` frame it
    cannot drop keeps the queue over, so the connection closes `slow_consumer` 4429 in the same
    check, both lanes freed at once. The `bye` is step 3's, its hint naming the book (the most
    expensive topic when the overflow began); each step counts once; the close is audited at
    `warning` with `after_state` `{"trigger": "budget"}` (§4.3)."""
    rig, sock = _Rig(BackpressureConfig(max_bytes=4096)), _Wire()
    before, closes = _counts(), _closes("slow_consumer")
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        await rig.sub(sock, "orders")
        assert conn.pipeline is not None
        for i in range(3):
            rig.book_delta(i)
        rig.sequencing.publish("orders", {"orders": [], "pad": "x" * 5000}, account=ACC_A)
        queue = conn.pipeline.queue
        assert conn.closing and (len(queue), queue.bytes) == (0, 0)  # freed at once
        (bye,) = await sock.next()
        await handler
    assert bye["p"] == slow_consumer_bye(BASE_MS, [_BOOK])["p"]
    assert sock.closed_with == 4429 and sock.sent.empty()
    assert _counts(before) == [1, 0, 1, 0]
    assert _closes("slow_consumer") == closes + 1
    assert _rows(rig) == [("ws.connection.closed", "slow_consumer", Severity.WARNING)]
    assert rig.audit.records[0]["after_state"] == {"trigger": "budget"}


async def test_three_redrops_close_with_close_redrop() -> None:
    """§8.4 step 3's second trigger: a `backpressure` snapshot larger than the budget is dropped
    again before it was sent, three times in a row, and the third drop closes `slow_consumer`
    under budget: `close_redrop`, not `close_budget`, the topic in the hint and the trigger in the
    audit row. No frame of that snapshot reaches the socket."""
    rig, sock = _Rig(BackpressureConfig(max_bytes=8192)), _Wire()
    rig.source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    before = _counts()
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        await rig.sub(sock, _TRADES)
        big = {"symbol": "BTCUSDT", "trades": [], "pad": "x" * 9000}
        rig.source.bodies["trades"] = SnapshotBody(big)
        rig.source.gen += 1  # from now on a snapshot never fits the budget
        rig.sequencing.publish(_TRADES, big)  # one delta over the budget: dropped
        (bye,) = await sock.next()
        await handler
    assert bye["p"] == slow_consumer_bye(BASE_MS, [_TRADES])["p"] and sock.closed_with == 4429
    assert _counts(before) == [4, 3, 0, 1]
    assert rig.audit.records[0]["after_state"] == {"trigger": "redrop"}


@pytest.mark.parametrize(
    ("fault", "trigger"), [("not_ready", "rebuild"), ("not_ready", "timer"), ("raises", "timer")]
)
async def test_a_backpressure_snapshot_that_does_not_queue_is_parked_until_rebuild_or_timer(
    fault: str, trigger: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `backpressure` snapshot that is not ready, or raises (D9: logged once by family and
    error class, C-12.6), is parked: the sends after it never retry it and the connection stays
    open. A hub `flush_pending` naming the topic (the source rebuilt), or the coarse timer
    (`classify_interval_ms` on the gateway's clock), retries it, and it goes out."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8, classify_interval_ms=1000)), _Wire()
    tried, attempts = asyncio.Event(), list[str]()
    build = rig.source.build

    def build_spy(sub: Subscription) -> SnapshotBody | None:
        attempts.append(sub.ch)
        tried.set()
        if fault == "raises" and len(attempts) == 1:
            raise RuntimeError(_MARK)
        return build(sub)

    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, conn = await rig.open(sock)
            await rig.sub(sock)
            monkeypatch.setattr(rig.source, "build", build_spy)
            if fault == "not_ready":
                rig.source.unavailable.add("BTCUSDT")
            rig.source.gen += 1  # the cached snapshot is stale: it must be rebuilt
            for i in range(9):
                rig.book_delta(i)  # in one turn, nine against eight: the book is dropped
            await tried.wait()  # the writer's drain tried it, and parked it
            for i in range(3):
                rig.hub.broadcast_system({"kind": "tick", "n": i})
            await sock.next(3)  # three sends, and none of their drains retried it
            assert attempts == [_BOOK] and not conn.closing
            rig.source.unavailable.clear()
            if trigger == "rebuild":
                rig.sequencing.flush_pending()
            else:
                rig.clock.now = 1.0  # the timer is due at the writer's next turn
            (snap,) = await sock.next()
            handler.cancel()
            await asyncio.wait({handler})
    assert (snap["t"], snap["meta"]["reason"], attempts) == ("snap", "backpressure", [_BOOK] * 2)
    failed = [e for e in logs if e["event"] == "ws backpressure snapshot failed"]
    named = [(e["family"], e["error"], e["log_level"]) for e in failed]
    assert named == ([("book", "RuntimeError", "error")] if fault == "raises" else [])
    assert _MARK not in repr(logs)
