"""E17-T03 (#412, S2b): the §8.4 overflow ladder in the budgeted pipeline, flag on
(`23-ws-protocol.md` §3.6, §4.3, §8.4). The router tests run the real `/ws` router behind `_Wire`
(`test_pipeline_outbound`); the unit tests drive a pipeline attached to a `_seq_support.Conn`. No
sleeps: every wait is on a frame or an event, bounded by `asyncio.timeout`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi import WebSocket
from structlog.testing import capture_logs

from candleviewer.audit.models import Severity
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.pipeline import ConnectionPipeline, slow_consumer_bye
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws._seq_support import ACC_A, Book, Conn, Source
from tests.unit.ws.test_coalescing import _apply_footprint, _state
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pacing import _refusals
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _DEADLINE_S,
    _MARK,
    _closes,
    _d,
    _overflow,
    _pipe,
    _queued,
    _Rig,
    _rows,
    _Wire,
)

_TRADES = "trades.BTCUSDT"
_STEPS = ("drop", "resnapshot", "close_budget", "close_redrop")
_SNAPSHOT_FAILED = "ws backpressure snapshot failed"
_UNENCODABLE = "ws frame unencodable"


def _counts(since: list[float] | None = None) -> list[float]:
    """`cv_ws_overflow_total` per ladder step, or what each grew by `since`."""
    now = [_overflow(reason) for reason in _STEPS]
    return now if since is None else [a - b for a, b in zip(now, since, strict=True)]


def _attached(
    levels: int = 2, max_frame_bytes: int | None = None, now: float = 0.0, **config: Any
) -> tuple[ConnectionPipeline, list[str], Conn]:
    """A pipeline attached to a `Conn` (a book of `levels` bids) whose emitter pushes into it,
    with a close that takes the terminal slot as `_Connection.close_with` does, and, as `run_auth`
    attaches it, `push_system` of a bare `_Connection` as its `notify`: a `connection_quality`
    notice (§8.3) is framed, cut for the principal's role and queued by production (SR-188,
    #3537), not by this module. It attaches at `now` on the conn's clock."""
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
    shell = _Connection(
        cast(WebSocket, None),  # `push_system` queues the frame: no socket, no writer
        encoding="cv.v1.json",
        clock=conn.clock,
        wall_ms=lambda: BASE_MS,
        auth_timeout_s=10.0,
    )
    # what `run_auth` and the handler give the connection: the principal and the pipeline
    shell.authz, shell.pipeline = conn.authz, pipe
    conn.clock.now = now
    pipe.attach(conn.authz, conn.emitter, shell.push_system)
    conn.emitter.push = pipe.push
    return pipe, asked, conn


def _bid(i: int) -> dict[str, Any]:
    return {"symbol": "BTCUSDT", "depth": 50, "bids": [[f"{90 - i}", "1"]], "asks": []}


def _structured(conn: Conn, ch: str) -> Subscription:
    _, sub = conn.sub({"ch": ch, "opts": {"encoding": "structured"}})
    return sub


def _suppressed(logs: Iterable[Mapping[str, Any]]) -> list[tuple[str, Any]]:
    """Each captured line's event and its `suppressed`: the lines held back before it."""
    return [(e["event"], e.get("suppressed")) for e in logs]


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


def test_footprint_bars_sharing_an_open_time_merge_in_every_window() -> None:
    """#3297, flag on: footprint bars are keyed by `(generation, index)` (§8.2, §14.4). A producer
    whose bars all open in one millisecond, each closing as the next opens, merges window after
    window: no update is refused `unmergeable`, no `backpressure` snapshot is queued, and a client
    keyed like the coalescer holds every source update applied."""
    ch = "footprint.BTCUSDT.tick.1000"
    series = {"symbol": "BTCUSDT", "bar_type": "tick", "param": "1000"}
    pipe, _, conn = _attached(classify_interval_ms=60_000)  # no probe frames in between
    source = conn.emitter.source
    assert isinstance(source, Source) and pipe.ladder is not None
    source.bodies["footprint"] = SnapshotBody({**series, "bars": []})
    sub = _structured(conn, ch)
    _queued(pipe)  # the initial snap
    before = _refusals("footprint")
    cell = {"price": "100", "bid_volume": "1", "ask_volume": "0.5", "trades": 1}
    sent: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    for n in range(40):  # 40 windows of 250 ms; the very first update leaves at once (D12)
        bar = {"generation": 0, "index": n, "t_ms": 7, "cells": [cell]}
        nxt = {**bar, "index": n + 1}
        for bars in ([bar], [{**bar, "confirm": True}, nxt], [nxt]):
            sent.append({**series, "bars": bars})
            assert pipe.delta(sub, sent[-1])
        conn.clock.now += 0.25
        pipe.service(conn.clock.now)
        frames += _queued(pipe)
    assert (_refusals("footprint"), pipe.ladder.pacer.resnapshot_required) == (before, {})
    assert {(f["t"], f["ch"]) for f in frames} == {("d", ch)} and len(frames) == 41
    assert sum(f["p"].get("coalesced_count", 1) for f in frames) == len(sent)
    assert _state(_apply_footprint, [f["p"] for f in frames]) == _state(_apply_footprint, sent)


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
                rig.clock.now += 1.0  # the timer is due at the writer's next turn
            (snap,) = await sock.next()
            handler.cancel()
            await asyncio.wait({handler})
    assert (snap["t"], snap["meta"]["reason"], attempts) == ("snap", "backpressure", [_BOOK] * 2)
    failed = [e for e in logs if e["event"] == _SNAPSHOT_FAILED]
    named = [(e["family"], e["error"], e["log_level"]) for e in failed]
    assert named == ([("book", "RuntimeError", "error")] if fault == "raises" else [])
    assert _MARK not in repr(logs)


async def test_the_timer_retries_one_parked_snapshot_per_tick_and_logs_once_per_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3102's review: each tick of the coarse timer opens one pass over the parked snapshots, in
    turn, ending at the first that does not queue: one failing build per tick, never all of them.
    A failure logs at most once per family per interval, the next line counting those held back."""
    pipe, _, conn = _attached(classify_interval_ms=1000)
    source = conn.emitter.source
    assert isinstance(source, Source) and pipe.ladder is not None
    source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    subs = [_structured(conn, ch) for ch in (_BOOK, "book.ETHUSDT.50", _TRADES)]
    _queued(pipe)
    attempts, failing, real = list[str](), {_BOOK, "book.ETHUSDT.50", _TRADES}, source.build

    def build(sub: Subscription) -> SnapshotBody | None:
        attempts.append(sub.ch)
        if sub.ch in failing:
            raise RuntimeError(_MARK)
        return real(sub)

    monkeypatch.setattr(source, "build", build)
    source.gen += 1  # every cached render is stale: each snapshot is built again
    for sub in subs:
        pipe.ladder.pacer.drop(sub)
    with capture_logs() as logs:
        pipe.service(0.0)
        assert attempts == [_BOOK]  # one snapshot per turn, though it failed
        for now in (0.0, 0.0, 0.0, 0.5):  # each mark tried once, one per turn, then parked
            pipe.service(now)
        assert attempts == [_BOOK, "book.ETHUSDT.50", _TRADES]
        for now in (1.0, 1.0, 1.5, 2.0, 2.0):  # ticks at 1.0 and 2.0: one attempt each
            pipe.service(now)
        assert attempts[3:] == [_BOOK, "book.ETHUSDT.50"]
        failing = {"book.ETHUSDT.50"}
        for _ in range(4):  # a tick: its pass goes on while the snapshots queue, to a failure
            pipe.service(3.0)
        assert attempts[5:] == [_TRADES, _BOOK, "book.ETHUSDT.50"]
        pipe.ladder.pacer.drop(subs[0])
        pipe.service(3.0)  # marked again, the book is tried at once: it was retried, not parked
    # The priority lane holds, ahead, the RTT probe of the 1.0 classification (§9.1), unanswered,
    # and the 2.0 one's `saturated` notice (§8.3); the 3.0 one changes nothing and sends no probe.
    frames = _queued(pipe)
    assert [(f["t"], f.get("ch")) for f in frames[:2]] == [("ping", None), ("d", "system")]
    assert [f["ch"] for f in frames[2:]] == [_TRADES, _BOOK, _BOOK]
    failed = [(e["family"], e["suppressed"]) for e in logs if e["event"] == _SNAPSHOT_FAILED]
    assert failed == [("book", 0), ("trades", 0), ("book", 1), ("book", 0), ("book", 0)]
    assert _MARK not in repr(logs)


def test_the_log_window_is_held_per_event_and_family() -> None:
    """#3194 round 2: an unencodable frame and a failed snapshot of one family each log in one
    window (`suppressed` 0); a second line of either is held back."""
    pipe, _ = _pipe()
    keys = [("snapshot", "book"), ("unencodable", "book")]
    assert [pipe._quiet(key) for key in keys] == [0, 0]
    assert [pipe._quiet(key) for key in keys] == [None, None]


async def test_an_unencodable_frame_and_its_failed_snapshot_each_log_once_per_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§10.1, §8.4 step 2 (#3194 round 2), through the pipeline's two log sites: an unencodable
    book delta and the `backpressure` snapshot it leads to, which fails, each log one line in the
    window (`suppressed` 0), neither spending the other's. A second of either is held back, and
    the next window's line counts it. No line names the payload (C-12.6)."""
    pipe, _, conn = _attached(classify_interval_ms=1000)
    source, rebuilt = conn.emitter.source, conn.emitter.on_rebuild
    assert isinstance(source, Source) and rebuilt is not None
    book = _structured(conn, _BOOK)
    _queued(pipe)  # the initial snapshot
    monkeypatch.setattr(source, "build", Mock(side_effect=RuntimeError(_MARK)))
    source.gen += 1  # the cached render is stale: the snapshot is built again, and fails
    refused = _d(_BOOK, x=float("nan"), note=_MARK)  # the JSON encoder refuses a NaN
    window = [(_UNENCODABLE, 0), (_SNAPSHOT_FAILED, 0)]
    with capture_logs() as logs:
        pipe.push(refused)  # dropped to a re-snapshot
        pipe.service(0.0)  # which fails to build, and is parked
        assert _suppressed(logs) == window
        pipe.push(refused)  # the same window: held back
        rebuilt([book])  # the source rebuilt: the parked snapshot is retried
        pipe.service(0.5)  # it fails again, in the same window: held back
        assert _suppressed(logs) == window
        rebuilt([book])
        pipe.service(1.0)  # the window ends at 1.0: this failure opens the next, counting one
        pipe.push(refused)
    assert _suppressed(logs) == [*window, (_SNAPSHOT_FAILED, 1), (_UNENCODABLE, 1)]
    assert _MARK not in repr(logs)
