"""E17-T03 (#412, S3), flag on: `publish` -> `ConnectionPipeline.delta` -> `Pacer.offer`, and the
writer's turn closes the windows (23 §5.4, §6.4, §8.1-§8.4, §9.5, §10.1). Unit tests use a pipeline
attached to a `Conn` and registered on a hub; router tests the real `/ws` router.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.coalescing import CoalescingQueue
from candleviewer.ws.metrics import cv_ws_malformed_updates_total
from candleviewer.ws.pacing import Pacer
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.pipeline import ConnectionPipeline
from candleviewer.ws.sequencing import PRIVATE_CAUSAL_ORDER, SequencingHub, SnapshotBody
from tests.unit.ws._seq_support import ACC_A, USER, Book, Conn, Source
from tests.unit.ws.test_pacing import _COLUMN, _bid, _private
from tests.unit.ws.test_pacing import _conn as _paced
from tests.unit.ws.test_pacing import _sub as _subscribed
from tests.unit.ws.test_pipeline_invalidation import _connected, _positions_rig, _row
from tests.unit.ws.test_pipeline_ladder import _attached, _structured
from tests.unit.ws.test_pipeline_outbound import _BOOK, _MARK, _counter, _queued, _Rig, _Wire

_TRADES, _BARS = "trades.BTCUSDT", "bars.BTCUSDT.time.1"
_SERIES = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1"}
_BAR = {"generation": 0, "index": 5, "t_ms": 1, "o": "1", "h": "2", "l": "1", "c": "2", "v": "3"}
_ORDERS = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}}
_STEPS = ("offer", "tick", "drop", "pause", "classify", "snapshot", "discard", "forget")


def _routed(hub: SequencingHub, **config: Any) -> tuple[ConnectionPipeline, list[str], Conn]:
    """`_attached`'s pipeline, registered on `hub` as its connection's sink."""
    pipe, asked, conn = _attached(**config)
    source = conn.emitter.source
    assert isinstance(source, Source)
    source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    source.bodies["bars"] = SnapshotBody({**_SERIES, "bars": []})
    hub.register(conn.authz, pipe)
    return pipe, asked, conn


def _pacer(pipe: ConnectionPipeline) -> Pacer:
    assert pipe.ladder is not None
    return pipe.ladder.pacer


def _print(i: int) -> dict[str, Any]:
    return {"id": f"t{i}", "ts_ms": 1, "price": "1", "size": "1", "side": "buy"}


def _raises(*_: Any, **__: Any) -> bool:
    raise RuntimeError(_MARK)


async def _turn(sock: _Wire) -> None:
    """A writer turn after the last clock change: the `pong` is sent after its `service`."""
    sock.feed({"t": "ping", "id": "p", "p": {"client_ms": 1}})
    assert [f["t"] for f in await sock.next()] == ["pong"]


# -- AC1 to AC4, end to end ----------------------------------------------------------------------


def test_500_book_updates_in_a_warm_window_leave_as_one_frame_count_500_one_seq() -> None:
    """AC1 with the leading edge kept (D12): after a warm-up update, 500 in one window leave at its
    close as one frame, `coalesced_count` 500, one `s`, equal to applying all 500. D7: the frame's
    fan-out stamp is its release from the window."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    book = _structured(conn, _BOOK)
    _queued(pipe)
    conn.emitter.push_data = pipe.push
    book.seq = 30  # the window's frame takes `s` 32, a sampled one
    assert hub.publish(_BOOK, _bid("90")) == 1
    [warm] = _queued(pipe)
    updates = [_bid(str(100 + i % 7), str(i % 3)) for i in range(500)]
    conn.clock.now = 0.04  # inside the window the warm update opened
    for update in updates:
        hub.publish(_BOOK, update)
    pipe.service(0.049)
    assert len(pipe.queue) == 0 and _pacer(pipe).pending_bytes > 0
    conn.clock.now = 0.05
    pipe.service(0.05)
    item = pipe.queue.pop()
    assert item is not None and (item.received, len(pipe.queue)) == (0.05, 0)
    frame = json.loads(item.payload)
    assert (frame["s"], frame["p"]["coalesced_count"]) == (warm["s"] + 1, 500)
    client, reference = Book("BTCUSDT"), Book("BTCUSDT")
    for body in (warm["p"], frame["p"]):
        client.apply(body["bids"], body["asks"])
    for body in (_bid("90"), *updates):
        reference.apply(body["bids"], body["asks"])
    assert client.bids == reference.bids and _pacer(pipe).pending_bytes == 0
    source = conn.emitter.source
    assert isinstance(source, Source)
    source.books["BTCUSDT"].apply([["99", "5"]], [])  # the hub's re-snapshot: built anew
    assert hub.upstream_desync("BTCUSDT") == 1
    [desync] = _queued(pipe)
    assert desync["meta"]["reason"] == "upstream_desync" and ["99", "5"] in desync["p"]["bids"]


def test_200_prints_leave_in_order_unmerged() -> None:
    """AC3: after the first print, the 200 of one window leave as one frame, in order, unmerged."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    _structured(conn, _TRADES)
    _queued(pipe)
    prints = [_print(i) for i in range(201)]
    for p in prints:
        hub.publish(_TRADES, {"symbol": "BTCUSDT", "trades": [p]})
    conn.clock.now = 0.1
    pipe.service(0.1)
    first, window = _queued(pipe)
    assert (first["p"]["trades"], window["p"]["trades"]) == (prints[:1], prints[1:])
    assert window["s"] == first["s"] + 1


@pytest.mark.parametrize("family", ["orders", "executions"])
def test_50_order_transitions_leave_as_50_frames_unthrottled(family: str) -> None:
    """AC4: 50 updates in one instant leave as 50 priority-lane frames, one `s` each, no window."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    _, sub = conn.authz.admit({"ch": family, "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert sub is not None
    sub.snapshot_pending = False
    for i in range(50):
        assert hub.publish(family, {family: [], "n": i}, account=ACC_A, meta={"i": i}) == 1
    assert len(pipe.queue._priority) == 50 and _pacer(pipe).lanes == {}
    frames = [(f["ch"], f["s"], f["p"]["n"], f["meta"]) for f in _queued(pipe)]
    assert frames == [(family, i + 1, i, {"i": i}) for i in range(50)]


def test_s5_private_windows_closing_together_leave_in_causal_order() -> None:
    """§16.1 S5, flag on: `executions` and `orders` leave at once, and windows that close together
    leave in causal order, `positions` before `trade_groups`, whatever the subscription order."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    for family in ("trade_groups", "positions", "orders", "executions"):  # in `sub_id` order
        _, sub = conn.authz.admit({"ch": family, "opts": {"exchange_account_ids": [str(ACC_A)]}})
        assert sub is not None
        sub.snapshot_pending = False
    group = {"id": "g", "status": "open", "updated_at_ms": 1}
    event = [("trade_groups", {"trade_groups": [group]}), ("orders", {"orders": []})]
    event += [("positions", {"positions": [_row(ACC_A)]}), ("executions", {"executions": []})]
    hub.publish_private(ACC_A, event)  # each leaves at once
    _queued(pipe)
    conn.clock.now = 0.01
    hub.publish_private(ACC_A, event)  # two windows, both closing at 0.1
    pipe.service(0.1)
    assert [f["ch"] for f in _queued(pipe)] == ["executions", "orders", "positions", "trade_groups"]


# -- §16.1 S5 between windows (D18, #3268) -------------------------------------------------------

_PRIVATE = ("trade_groups", "positions", "orders", "executions")  # scrambled, as `_event` sends


def _private_rig(
    hub: SequencingHub, positions_ms: int | None = None, **config: Any
) -> tuple[ConnectionPipeline, Conn]:
    """`_routed`'s pipeline on the four private families of `ACC_A`, `trade_groups` first in
    `sub_id` order; `positions` at `positions_ms` when given, else at its 100 ms default."""
    pipe, _, conn = _routed(hub, **config)
    for family in _PRIVATE:
        opts: dict[str, Any] = {"exchange_account_ids": [str(ACC_A)]}
        if family == "positions" and positions_ms is not None:
            opts["throttle_ms"] = positions_ms
        _, sub = conn.authz.admit({"ch": family, "opts": opts})
        assert sub is not None
        sub.snapshot_pending = False
    return pipe, conn


def _body(family: str, at: int) -> dict[str, Any]:
    """One update of a private family; a `positions` or `trade_groups` row carries `at`."""
    if family == "positions":
        return {"positions": [_row(ACC_A, at)]}
    if family == "trade_groups":
        return {"trade_groups": [{"id": "g", "status": "open", "updated_at_ms": at}]}
    return {family: []}


def _event(at: int, *families: str) -> list[tuple[str, dict[str, Any]]]:
    """One account event of `families`, all four private ones by default, scrambled:
    `publish_private` puts them in causal order."""
    return [(family, _body(family, at)) for family in families or _PRIVATE]


def _tags(frames: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Each `positions` or `trade_groups` frame's channel and the `at` of its row."""
    return [(f["ch"], f["p"][f["ch"]][0]["updated_at_ms"]) for f in frames]


_P, _T = ("positions",), ("trade_groups",)
_SETUPS: dict[str, tuple[list[tuple[float, tuple[str, ...]]], float, float, tuple[int, ...]]] = {
    # the updates before the event, its arrival, `positions`' own close, the `trade_groups` rows
    "cold_lane": ([(0.0, _P)], 0.05, 0.0 + 0.1, (2,)),  # `trade_groups` never emitted
    "throttle": ([(0.0, ())], 0.01, 0.0 + 0.5, (2,)),  # `positions` at 500 ms
    "last_emit": ([(0.0, _T), (0.05, _P)], 0.06, 0.05 + 0.1, (2,)),
    "open_window": ([(0.0, _T), (0.01, _T), (0.01, _P), (0.02, _P)], 0.02, 0.01 + 0.1, (1, 2)),
}


@pytest.mark.parametrize("cause", list(_SETUPS))
def test_s5_trade_groups_waits_for_the_open_positions_window(cause: str) -> None:
    """§16.1 S5 between windows (D18), flag on: an event's `trade_groups` update that finds the
    `positions` window it reached still open leaves after it, in the same writer's turn, whether
    its lane is cold (no leading edge then), its `throttle_ms` shorter, its last emit earlier, or
    its window open already, closing first (the update moves that close). `executions` and
    `orders` leave at once, and `positions` at its own close."""
    hub = SequencingHub()
    pipe, conn = _private_rig(hub, 500 if cause == "throttle" else None)
    setup, at, close, rows = _SETUPS[cause]
    for now, families in setup:
        conn.clock.now = now
        hub.publish_private(ACC_A, _event(1, *families))
    _queued(pipe)
    conn.clock.now = at
    hub.publish_private(ACC_A, _event(2))
    assert [f["ch"] for f in _queued(pipe)] == ["executions", "orders"]
    pipe.service(close - 0.001)
    assert _queued(pipe) == []
    pipe.service(close)
    assert _tags(_queued(pipe)) == [("positions", 2), *(("trade_groups", row) for row in rows)]


def test_s5_a_due_positions_window_leaves_before_an_inline_trade_groups_flush() -> None:
    """§16.1 S5 (D18), the writer's turn late: a `trade_groups` update that finds the event's
    `positions` window past its close never flushes its own window ahead of it, and the hold
    queues nothing. That `positions` window is not moved: the next `positions` update still flushes
    it at once, as without the hold, and `trade_groups` leaves after it at the writer's turn."""
    hub = SequencingHub()
    pipe, conn = _private_rig(hub)
    hub.publish_private(ACC_A, _event(1))  # everything leaves at once
    _queued(pipe)
    conn.clock.now = 0.05
    hub.publish_private(ACC_A, _event(2))  # both windows close at 0.1
    assert [f["ch"] for f in _queued(pipe)] == ["executions", "orders"]
    conn.clock.now = 0.11  # the writer's turn due at 0.1 has not run
    hub.publish_private(ACC_A, _event(3, "trade_groups"))
    assert _queued(pipe) == []
    conn.clock.now = 0.12
    hub.publish_private(ACC_A, _event(4, "positions"))
    assert _tags(_queued(pipe)) == [("positions", 4)]  # as without the hold: at once, merged
    pipe.service(0.13)
    assert _tags(_queued(pipe)) == [("trade_groups", 2), ("trade_groups", 3)]


def test_s5_a_class_change_keeps_positions_first() -> None:
    """§16.1 S5 (D18) across an §8.3 class change: re-timed, a `trade_groups` window that an
    update reached while a `positions` window was open still closes after that window, though its
    own `throttle_ms` would now close it first (`positions` at 200 ms, then `lagging`)."""
    hub = SequencingHub()
    pipe, conn = _private_rig(hub, 200)
    hub.publish_private(ACC_A, _event(1, "positions"))
    conn.clock.now = 0.1
    hub.publish_private(ACC_A, _event(2, "trade_groups"))
    _queued(pipe)
    conn.clock.now = 0.15
    hub.publish_private(ACC_A, _event(3))  # both windows close at 0.2
    assert [f["ch"] for f in _queued(pipe)] == ["executions", "orders"]
    _pacer(pipe).classify(30.0, list(conn.authz.by_id.values()), now=0.16)  # lagging
    pipe.service(0.1 + 0.2)  # `trade_groups`' own close now
    assert _queued(pipe) == []
    pipe.service(0.4)
    assert _tags(_queued(pipe)) == [("positions", 3), ("trade_groups", 3)]


def test_s5_a_class_change_holds_only_a_window_that_waited() -> None:
    """D18 holds a `trade_groups` window for the `positions` window open when one of its updates
    arrived, no other: re-timed, a window none of whose updates arrived while the open
    `positions` window was open closes by its own `throttle_ms`, though an earlier one waited."""
    hub = SequencingHub()
    pipe, conn = _private_rig(hub, 200)
    for now, at, families in ((0.0, 1, ("positions",)), (0.1, 2, ("trade_groups",)), (0.15, 3, ())):
        conn.clock.now = now
        hub.publish_private(ACC_A, _event(at, *families))
    pipe.service(0.2)  # event 3's windows, `trade_groups` held for `positions`
    _queued(pipe)
    conn.clock.now = 0.25
    hub.publish_private(ACC_A, _event(4, "trade_groups"))  # a window closing at 0.3
    conn.clock.now = 0.26
    hub.publish_private(ACC_A, _event(5, "positions"))  # a window closing at 0.4
    _pacer(pipe).classify(30.0, list(conn.authz.by_id.values()), now=0.27)  # lagging
    pipe.service(0.2 + 0.2)
    assert _tags(_queued(pipe)) == [("trade_groups", 4)]
    pipe.service(0.2 + 0.4)
    assert _tags(_queued(pipe)) == [("positions", 5)]


def test_s5_a_class_change_re_arms_no_dropped_trade_groups_window() -> None:
    """§8.1 across a class change: `apply` arms no `trade_groups` window that §8.4 step 1 dropped
    after one of its updates reached the open `positions` window. The next update opens a window
    at its own close (`lagging`: 100.05 + 0.2), after the `positions` one, never at it."""
    conn, pacer = _paced()
    positions, groups = _private(conn, "positions"), _private(conn, "trade_groups")
    out: list[dict[str, Any]] = []
    conn.emitter.push = out.append  # not schema-checked: these rows carry only the order
    pacer.offer(positions, _body("positions", 1))  # leaves at once
    conn.clock.now = 100.05
    pacer.offer(groups, _body("trade_groups", 1))  # leaves at once
    conn.clock.now = 100.06
    for family, sub in (("positions", positions), ("trade_groups", groups)):
        pacer.offer(sub, _body(family, 2))  # `positions` closes at 100.1, waited on
    pacer.drop(groups)
    groups.snapshot_pending, groups.seq = False, groups.seq + 1  # its `backpressure` snap left
    pacer.classify(30.0, [positions, groups], now=100.07)  # lagging: `positions` closes at 100.2
    conn.clock.now = 100.08
    pacer.offer(groups, _body("trade_groups", 3))
    del out[:]
    assert (pacer.tick(100.0 + 0.2), pacer.tick(100.05 + 0.2)) == (1, 1)
    assert _tags(out) == [("positions", 2), ("trade_groups", 3)]


def test_s5_an_ended_positions_window_holds_nothing_back() -> None:
    """D18 waits on the connection's live `positions` window: once that stream ends or resets
    (`ConnectionAuthz.on_drop`, which lets its window go), a `trade_groups` update on a cold lane
    leaves at once again, its leading edge."""
    hub = SequencingHub()
    pipe, conn = _private_rig(hub)
    hub.publish_private(ACC_A, _event(1, "positions"))
    conn.clock.now = 0.05
    hub.publish_private(ACC_A, _event(2, "positions"))  # a window closing at 0.1
    positions = conn.authz.find("positions")
    assert positions is not None and conn.authz.on_drop is not None
    conn.authz.on_drop([positions])
    _queued(pipe)
    hub.publish_private(ACC_A, _event(3, "trade_groups"))
    assert _tags(_queued(pipe)) == [("trade_groups", 3)]


def test_s5_a_late_discard_of_an_ended_positions_lane_keeps_the_gate() -> None:
    """The gate follows the live `positions` lane: a late `discard` of an ended subscription's
    lane, after the topic was subscribed again, leaves `trade_groups` held behind the new lane."""
    conn, pacer = _paced()
    ended, groups = _private(conn, "positions"), _private(conn, "trade_groups")
    live = replace(ended, sub_id="s_live")  # the same topic, subscribed again
    out: list[dict[str, Any]] = []
    conn.emitter.push = out.append  # not schema-checked: these rows carry only the order
    pacer.offer(ended, _body("positions", 1))
    for at in (2, 3):  # the first leaves at once, the second opens a window closing at 100.1
        pacer.offer(live, _body("positions", at))
    pacer.discard(ended.sub_id)
    del out[:]
    pacer.offer(groups, _body("trade_groups", 3))
    assert out == [] and pacer.tick(100.0 + 0.1) == 2
    assert _tags(out) == [("positions", 3), ("trade_groups", 3)]


def test_s5_positions_is_just_ahead_of_trade_groups_in_causal_order() -> None:
    """`Pacer._gate` waits on the family just ahead in causal order, and only `positions` and
    `trade_groups` of the four are paced (S4): they must stay adjacent, in that order."""
    assert PRIVATE_CAUSAL_ORDER[2:] == ("positions", "trade_groups")


def test_s5_a_held_trade_groups_window_counts_and_is_shed_like_any_other() -> None:
    """§8.4: a `trade_groups` window held behind a `positions` one counts against the budget from
    its first update and keeps one heap entry (C-2.18); step 1 drops it like any window, marked
    for its `backpressure` snapshot and with nothing left, though nothing was queued."""
    hub = SequencingHub()
    pipe, conn = _private_rig(hub, max_bytes=1_500)
    hub.publish_private(ACC_A, _event(1, "positions"))
    conn.clock.now = 0.01
    hub.publish_private(ACC_A, _event(2, "positions"))  # a window closing at 0.1
    _queued(pipe)
    for at in range(3, 60):  # a cold lane, held: every update waits in its window
        hub.publish_private(ACC_A, _event(at, "trade_groups"))
    groups = conn.authz.find("trade_groups")
    assert groups is not None and groups.pending_reason == "backpressure"
    assert (len(pipe.queue), _pacer(pipe).pending_bytes, len(_pacer(pipe)._dues)) == (0, 0, 2)


_S5_OPS = ("positions", "trade_groups", "event", _BOOK, "tick", "wait", "ctl", "classify")
_TWO_CLOSES = [("ctl", 2), ("positions", 0), ("wait", 44), ("trade_groups", 0), ("wait", 0)]
_OPEN = [("trade_groups", 0), ("wait", 0), ("trade_groups", 0), ("positions", 0), ("wait", 0)]
_REOPEN = [("ctl", 2), ("event", 0), ("wait", 0), ("trade_groups", 0), ("wait", 0)]
_OWN_LATER = [("ctl", 5), ("event", 0), ("wait", 0), ("event", 0)]
_ARGS = st.one_of(st.integers(0, 9), st.integers(0, 49))  # short waits overlap the windows
_LATE = [("event", 0), ("wait", 4), ("event", 0), ("wait", 5), ("trade_groups", 0), ("wait", 0)]


def _s5_run(
    ops: list[tuple[str, int]], groups: bool
) -> tuple[list[tuple[float, dict[str, Any]]], dict[int, int]]:
    """One run of the property below on a `Pacer`, `trade_groups` subscribed or not: the frames,
    each with its release time, and how many had left before each event of both families. Checks
    §8.1 on the way: two releases of a lane are at least the least `throttle_ms` it had between
    them apart (a `ctl` re-times no open window, so the least is the bound)."""
    conn, pacer = _paced()
    families = ("positions", "trade_groups")[: 2 if groups else 1]
    subs = {family: _private(conn, family) for family in families}
    subs[_BOOK] = _subscribed(conn, _BOOK)
    out: list[tuple[float, dict[str, Any]]] = []
    conn.emitter.push = lambda frame: out.append((conn.clock.now, frame))
    events: dict[int, int] = {}
    last: dict[str, float] = {}
    floor = {ch: pacer.throttle_ms(sub) for ch, sub in subs.items()}
    for n, (op, arg) in enumerate([*ops, ("tick", 999)]):  # the last turn sends what is left
        start = len(out)
        if op in ("tick", "wait"):  # a writer's turn, or time passing without one (a late turn)
            conn.clock.now += (arg + 1) / 100
            if op == "tick":
                pacer.tick()
        elif op == "ctl":  # a new `throttle_ms`: the next window takes it
            if (sub := subs.get(("positions", "trade_groups")[arg % 2])) is not None:
                sub.effective["throttle_ms"] = (50, 100, 500)[arg % 3]
        elif op == "classify":
            pacer.classify((0.0, 30.0, 70.0)[arg % 3], list(subs.values()))
        elif op == _BOOK:
            pacer.offer(subs[_BOOK], _bid(str(100 + arg % 7)))
        else:  # one family's update, or an event of both, in causal order
            if op == "event" and groups:
                events[n] = start
            for family in families if op == "event" else (op,):
                if family in subs:
                    pacer.offer(subs[family], _body(family, n))
        for ch, sub in subs.items():
            floor[ch] = min(floor[ch], pacer.throttle_ms(sub))
        for at, frame in out[start:]:
            ch = frame["ch"]
            if last.get(ch) != at:  # a new release: a window's frames leave together
                if ch in last:
                    assert at >= last[ch] + floor[ch] / 1000
                last[ch], floor[ch] = at, pacer.throttle_ms(subs[ch])
    return out, events


@settings(max_examples=200, deadline=None, derandomize=True, database=None)
@given(st.lists(st.tuples(st.sampled_from(_S5_OPS), _ARGS), max_size=40))
@example([("positions", 0), ("wait", 4), ("event", 0)])  # 1: a cold lane's leading edge
@example([("ctl", 2), ("event", 0), ("wait", 0), ("event", 0)])  # 2: `positions` at 500 ms
@example([("trade_groups", 0), ("wait", 4), ("positions", 0), ("wait", 0), ("event", 0)])  # 3
@example([("event", 0), ("wait", 4), ("event", 0), ("wait", 6), ("trade_groups", 0)])  # 4: late
@example([*_TWO_CLOSES, ("event", 0), ("classify", 1)])  # 5: a class change re-times both
@example([*_LATE, ("positions", 0), ("tick", 0)])  # no `positions` frame moves, late or not
@example([*_OWN_LATER, ("tick", 9)])  # `trade_groups`' own close later than `positions'`
@example([*_OWN_LATER, ("classify", 1), ("tick", 9), ("tick", 9)])  # and kept across a class change
@example([*_OPEN, ("positions", 0), ("event", 0)])  # an open `trade_groups` window moves later
@example([*_REOPEN, ("positions", 0), ("wait", 0), ("event", 0)])  # the same, `positions` 500 ms
def test_s5_holds_between_windows_for_any_interleaving(ops: list[tuple[str, int]]) -> None:
    """§16.1 S5 between windows (D18) over random interleavings of `positions`, `trade_groups`
    and `book` updates, `throttle_ms` changes, class changes and writer turns, late ones too: for
    every event of both families its `positions` frame leaves first; each lane leaves at most once
    per its `throttle_ms` (§8.1, in `_s5_run`); and `positions` and `book` leave exactly as in
    the same run without `trade_groups`, so the hold never moves them."""
    out, events = _s5_run(ops, groups=True)
    alone, _ = _s5_run(ops, groups=False)
    for ch in ("positions", _BOOK):
        assert [(at, f["s"], f["p"]) for at, f in out if f["ch"] == ch] == [
            (at, f["s"], f["p"]) for at, f in alone if f["ch"] == ch
        ]
    for n, start in events.items():  # the first `positions` frame after it carries its row
        p = next((i for i in range(start, len(out)) if out[i][1]["ch"] == "positions"), None)
        groups = [i for i, (_, f) in enumerate(out) if f["ch"] == "trade_groups"]
        t = next((i for i in groups if _tags([out[i][1]]) == [("trade_groups", n)]), None)
        assert p is not None and t is not None and p < t


def test_confirmed_bar_survives_a_later_unconfirmed_update_end_to_end() -> None:
    """AC2 end to end: a later unconfirmed update in the window never replaces a confirmed bar."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    _structured(conn, _BARS)
    _queued(pipe)
    for item in ({**_BAR, "index": 4}, {**_BAR, "confirm": True}, {**_BAR, "c": "9"}):
        hub.publish(_BARS, {**_SERIES, "bars": [{"confirm": False, **item}]})
    conn.clock.now = 0.25
    pipe.service(0.25)
    _, window = _queued(pipe)
    assert window["p"]["bars"] == [{**_BAR, "confirm": True}]


def test_delta_meta_survives_a_coalesced_window() -> None:
    """#2833's `meta` (#2849's `include_delta`): a merged window carries its last update's."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    _structured(conn, _BARS)
    _queued(pipe)
    for index, flow in ((1, False), (2, False), (3, True)):
        body = {**_SERIES, "bars": [{**_BAR, "index": index, "confirm": False}]}
        hub.publish(_BARS, body, meta={"include_delta": flow})
    conn.clock.now = 0.25
    pipe.service(0.25)
    first, window = _queued(pipe)
    assert (first["meta"], window["meta"]) == ({"include_delta": False}, {"include_delta": True})
    assert window["p"]["coalesced_count"] == 2


def test_frames_folded_when_coalescing_turns_on_keep_the_last_meta() -> None:
    """#2833, §8.3: whole frames folded into one merge (a lagging class forces coalescing) carry
    the last frame's `meta`, as a merged window does."""
    queue = CoalescingQueue("bars", coalesce=False)
    for c, flow in (("2", False), ("3", True)):
        bar = {**_BAR, "c": c, "confirm": False}
        assert queue.offer({**_SERIES, "bars": [bar]}, meta={"include_delta": flow})
    queue.set_coalesce(True)
    [emission] = queue.take()
    assert (emission.meta, emission.coalesced_count) == ({"include_delta": True}, 2)


@pytest.mark.parametrize("coalesce", [True, False])
def test_a_machines_window_carries_only_the_latest_state(coalesce: bool) -> None:
    """§6.4, §8.2: one pending payload, whole-object last-write-wins, whatever `coalesce` says."""
    queue = CoalescingQueue("machines", coalesce=coalesce)
    for body in ({"state": "a", "regions": {"x": "a"}}, {"state": "b"}, {"state": "c", "tags": []}):
        assert queue.offer(body)
    [emission] = queue.take()
    assert (emission.body, emission.coalesced_count) == ({"state": "c", "tags": []}, 3)


def test_the_window_heap_stays_bounded() -> None:
    """C-2.18: re-timed windows leave stale entries, never taken for the window; past 2 x lanes
    + 64 the heap is rebuilt."""
    conn, pacer = _paced()
    sub = _subscribed(conn, _BOOK)
    for price in ("1", "2"):  # the second opens a window
        pacer.offer(sub, _bid(price))
    for i in range(500):  # each re-timing is later, so the entry before it is stale and earlier
        conn.clock.now = 101 + i / 64
        pacer.apply([sub])
    assert len(pacer._dues) <= 2 * len(pacer.lanes) + 64
    assert pacer.tick(conn.clock.now - 1 / 64) == 0 and len(conn.take()) == 1  # the first only
    assert pacer.next_due() == conn.clock.now


def test_a_rebuilt_heap_still_closes_the_earliest_window_first() -> None:
    """C-2.18: the rebuild restores the heap order whatever the lanes' order (the earliest window
    is the middle lane's), so `next_due` and `tick` still find that window."""
    conn, pacer = _paced()
    subs = [_subscribed(conn, ch) for ch in (_TRADES, _BOOK, "heatmap.BTCUSDT")]  # 100, 50, 500 ms
    for n in range(2):  # the second update opens each window
        for sub in subs:
            _step("offer", conn, pacer, sub, n)
    for _ in range(64):  # re-timed in place until the heap is rebuilt
        size = len(pacer._dues)
        pacer.apply(subs)
        if len(pacer._dues) < size:
            break
    conn.take()
    assert pacer.next_due() == 100.05 and pacer.tick(100.05) == 1
    assert [f["ch"] for f in conn.take()] == [_BOOK]


# -- the writer's turn ---------------------------------------------------------------------------


async def test_window_closes_at_next_due_on_the_injected_clock() -> None:
    """§8.1, no new task: the idle writer's 30 s wait is cut to the window's close, sent on time."""
    rig, sock = _Rig(BackpressureConfig(), tick_s=30.0), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock)
        pipe = conn.pipeline
        assert pipe is not None
        for price in ("101", "102"):  # the first leaves at once, the second waits 50 ms
            rig.sequencing.publish(_BOOK, _bid(price))
        [first] = await sock.next()
        assert (pipe.wait_s(0.0, 1.0), pipe.wait_s(0.0, 0.01)) == (0.05, 0.01)
        rig.clock.now = 0.049
        await _turn(sock)
        rig.clock.now = 0.05
        [window] = await sock.next()
        assert pipe.wait_s(0.05, 1.0) == pytest.approx(0.95)  # no window: the classification
    assert (window["s"], window["p"]["bids"]) == (first["s"] + 1, [["102", "1"]])


async def test_a_window_opened_while_the_writer_idles_closes_on_time() -> None:
    """§8.1: a window opened after the writer went idle (its wait read the 10 s classification)
    wakes it, so it closes at its due time with no other frame to wake the writer."""
    rig, sock = _Rig(BackpressureConfig(classify_interval_ms=10_000), tick_s=30.0), _Wire()
    async with _connected(rig, sock):
        await rig.sub(sock)
        rig.sequencing.publish(_BOOK, _bid("101"))
        [first] = await sock.next()  # it left at once; then the writer waits its 10 s
        rig.clock.now = 0.01
        rig.sequencing.publish(_BOOK, _bid("102"))  # opens the window, closing at 0.05
        rig.clock.now = 0.05
        [window] = await sock.next()
    assert (window["s"], window["p"]["bids"]) == (first["s"] + 1, [["102", "1"]])


def test_only_a_window_closing_within_the_writers_wait_wakes_it() -> None:
    """§8.1: a window armed to close before the idle writer's wait ends wakes it; a window closing
    later, or an update into an open window, wakes nothing."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    bars = {**_SERIES, "bars": [{**_BAR, "confirm": False}]}
    for ch, body in ((_BARS, bars), (_BOOK, _bid("90"))):  # each leaves at once
        _structured(conn, ch)
        hub.publish(ch, body)
    _queued(pipe)
    conn.clock.now, woken = 0.01, list[bool]()
    for ch, body in ((_BARS, bars), (_BOOK, _bid("91")), (_BOOK, _bid("92"))):
        pipe.queue.ready.clear()
        pipe.wait_s(0.01, 0.05)  # the idle writer waits until 0.06 at the latest
        hub.publish(ch, body)  # opens the bars window (0.25), the book's (0.05), then merges
        woken.append(pipe.queue.ready.is_set())
    assert woken == [False, True, False]


async def test_paused_window_shed_then_resume_resnapshots_reconfigure() -> None:
    """§5.4 (#2517): a window open at the pause is shed at its close, never sent or counted; the
    resume answers `resnapshot` with a `reconfigure` snap on the next `s`, and deltas go on."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock)
        assert conn.pipeline is not None
        pacer = _pacer(conn.pipeline)
        for price in ("101", "102"):
            rig.sequencing.publish(_BOOK, _bid(price))
        [first] = await sock.next()
        sock.feed({"t": "ctl", "id": "c1", "ch": _BOOK, "p": {"paused": True}})
        assert [f["t"] for f in await sock.next()] == ["ctl_ok"] and pacer.pending_bytes > 0
        rig.clock.now = 0.05
        await _turn(sock)
        assert pacer.pending_bytes == 0
        sock.feed({"t": "ctl", "id": "c2", "ch": _BOOK, "p": {"paused": False}})
        ok, snap = await sock.next(2)
        rig.clock.now = 1.0
        rig.sequencing.publish(_BOOK, _bid("103"))
        [after] = await sock.next()
    assert ok["p"]["resnapshot"] is True and snap["meta"]["reason"] == "reconfigure"
    assert (snap["s"], after["s"]) == (first["s"] + 1, first["s"] + 2)


# -- nothing after the frame that ends a stream --------------------------------------------------


async def test_unsub_forgets_the_window_no_d_after_unsub_ok() -> None:
    """§8.4 Lanes (`forget` before the ack): no `d` of the window after `unsub_ok`, ever; and the
    emitter refuses an ended subscription whatever still holds it (defence in depth, WS-E02)."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock)
        assert conn.pipeline is not None
        pacer = _pacer(conn.pipeline)
        for price in ("101", "102"):
            rig.sequencing.publish(_BOOK, _bid(price))
        assert [f["t"] for f in await sock.next()] == ["d"] and pacer.pending_bytes > 0
        (sub,), emitter = [lane.sub for lane in pacer.lanes.values()], pacer.emitter
        sock.feed({"t": "unsub", "id": "u", "p": {"topics": [_BOOK]}})
        assert [f["t"] for f in await sock.next()] == ["unsub_ok"]
        assert (pacer.lanes, pacer.pending_bytes) == ({}, 0)
        assert sub.ended  # defence in depth: the emitter sends no `d` or `snap` of it
        assert not emitter.delta(sub, _bid("1")) and not emitter.snapshot(sub, "client_resync")
        rig.clock.now = 1.0
        await _turn(sock)
        assert sock.sent.empty()


async def test_revoked_private_topic_window_never_emits_after_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WS-E02, AC-13, §9.5: a window holding a withdrawn account's row never follows `revoked`."""
    rig, sock = _positions_rig(monkeypatch, ACC_A), _Wire()
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, "positions", exchange_account_ids=[str(ACC_A)])
        assert conn.pipeline is not None
        pacer = _pacer(conn.pipeline)
        for at in (1, 2):  # the first leaves at once, the second waits in the window
            rig.sequencing.publish("positions", {"positions": [_row(ACC_A, at)]}, account=ACC_A)
        assert [f["t"] for f in await sock.next()] == ["d"] and pacer.pending_bytes > 0
        rig.grants = ()
        await rig.registry.grants_changed(USER)
        assert [f["t"] for f in await sock.next(2)] == ["permission_change", "revoked"]
        assert (pacer.lanes, pacer.pending_bytes) == ({}, 0)
        rig.clock.now = 1.0
        await _turn(sock)
        assert sock.sent.empty()


def test_the_drop_hook_keeps_a_held_subscriptions_mark() -> None:
    """§8.4 Lanes: the hook (a narrowing's, say) lets the window go but keeps the `backpressure`
    mark of a subscription that stays, which would otherwise stay held for good."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    book = _structured(conn, _BOOK)
    _pacer(pipe).drop(book)
    assert conn.authz.on_drop is not None
    conn.authz.on_drop([book])
    assert book.sub_id in _pacer(pipe).resnapshot_required


# -- containment and the budget's total ----------------------------------------------------------


async def test_one_subscriptions_emit_failure_does_not_stop_the_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§10.1 (D9), #2552: a window whose emit raises drops its own topic to a `backpressure`
    re-snapshot (counted, logged by family and error class); the fan-out reaches the next
    connection. An `orders` update that raises closes its own connection, `internal_error`."""
    hub = SequencingHub()
    (bad, asked, bad_conn), (good, _, good_conn) = _routed(hub), _routed(hub)
    book = _structured(bad_conn, _BOOK)
    _structured(good_conn, _BOOK)
    for conn in (bad_conn, good_conn):
        _, orders = conn.authz.admit(_ORDERS)
        assert orders is not None
        orders.snapshot_pending = False
    for pipe in (bad, good):
        _queued(pipe)

    monkeypatch.setattr(bad_conn.emitter, "delta", _raises)
    before = _counter(cv_ws_malformed_updates_total, topic="book")
    with capture_logs() as logs:
        hub.publish(_BOOK, _bid("90"))
        assert bad.queue.ready.is_set() and asked == []  # woken: its `drain` sends the snapshot
        for _ in range(2):  # the second finds `bad` closed: it takes nothing (WS-D01)
            hub.publish("orders", {"orders": []}, account=ACC_A)
    assert sorted(f["ch"] for f in _queued(good)) == [_BOOK, "orders", "orders"]
    assert book.sub_id in _pacer(bad).resnapshot_required and book.pending_reason == "backpressure"
    assert asked == ["internal_error"]
    assert _counter(cv_ws_malformed_updates_total, topic="book") == before + 1
    failed = [
        (e["family"], e["error"], e["log_level"]) for e in logs if e["event"] == "ws update failed"
    ]
    assert failed == [("book", "RuntimeError", "warning"), ("orders", "RuntimeError", "error")]
    assert _MARK not in repr(logs)


async def test_a_failing_logger_skips_no_close_or_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    """§10.1: when its log line raises too, a failing build still drops its topic and a failing
    `orders` update still closes the connection; nothing reaches the caller."""
    hub = SequencingHub()
    pipe, asked, conn = _routed(hub)
    _, orders = conn.authz.admit(_ORDERS)
    _, book = conn.authz.admit({"ch": _BOOK, "opts": {"encoding": "structured"}})
    assert orders is not None and book is not None
    orders.snapshot_pending = False
    for name in ("delta", "flush_pending"):
        monkeypatch.setattr(conn.emitter, name, _raises)
    monkeypatch.setattr("candleviewer.ws.pipeline._log", _raises)
    assert pipe.flush_pending([book]) == 0 and book.pending_reason == "backpressure"
    hub.publish("orders", {"orders": []}, account=ACC_A)
    assert asked == ["internal_error"]


def test_a_window_that_raises_at_its_close_is_contained_in_the_writers_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Pacer.on_error`: a window raising at the writer's turn drops its topic, queued frame too."""
    hub = SequencingHub()
    pipe, asked, conn = _routed(hub)
    book = _structured(conn, _BOOK)
    _queued(pipe)
    for price in ("90", "91"):  # the first is queued, the second waits in the window
        hub.publish(_BOOK, _bid(price))
    monkeypatch.setattr(conn.emitter, "delta", _raises)
    pipe.service(0.05)
    assert [(f["t"], f["meta"]["reason"]) for f in _queued(pipe)] == [("snap", "backpressure")]
    assert (book.snapshot_pending, asked) == (False, [])


async def test_a_snapshot_that_raises_after_a_sub_drops_its_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§10.1 after a `sub` or `ctl` (the gateway's flush): a droppable topic's snapshot build that
    raises is retried as its `backpressure` snapshot; the connection stays open."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    build, malformed = rig.source.build, _counter(cv_ws_malformed_updates_total, topic="book")
    async with _connected(rig, sock):
        monkeypatch.setattr(rig.source, "build", _raises)
        sock.feed({"t": "sub", "id": "s", "p": {"topics": [{"ch": _BOOK, "opts": {}}]}})
        assert [f["t"] for f in await sock.next()] == ["sub_ok"]
        monkeypatch.setattr(rig.source, "build", build)
        rig.clock.now += 1.0  # the drain's retry pass is due, if it had parked the snapshot
        [snap] = await sock.next()
    assert (snap["t"], snap["meta"]["reason"]) == ("snap", "backpressure")
    assert _counter(cv_ws_malformed_updates_total, topic="book") == malformed  # a build, no update


def test_flush_pending_goes_on_past_a_build_that_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """§10.1, per subscription: a build that raises in one flush leaves the next its snapshot."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    opts = {"encoding": "structured"}
    book, trades = (conn.authz.admit({"ch": ch, "opts": opts})[1] for ch in (_BOOK, _TRADES))
    assert book is not None and trades is not None
    book.announced = trades.announced = True
    source = conn.emitter.source
    assert isinstance(source, Source)
    build = source.build
    monkeypatch.setattr(source, "build", lambda sub: _raises() if sub is book else build(sub))
    assert pipe.flush_pending([book, trades]) == 1
    assert [(f["t"], f["ch"]) for f in _queued(pipe)] == [("snap", _TRADES)]


def test_a_window_counts_against_the_budget_before_any_push() -> None:
    """#2552: pending window state counts; the check after each update drops the topic."""
    hub = SequencingHub()
    pipe, _, conn = _routed(hub, max_bytes=1_500)
    book = _structured(conn, _BOOK)
    _queued(pipe)
    for i in range(200):  # the first leaves at once; the rest wait in its window
        hub.publish(_BOOK, _bid(str(1000 + i)))
    assert (book.pending_reason, len(pipe.queue), _pacer(pipe).pending_bytes) == (
        "backpressure",
        0,
        0,
    )


def _step(step: str, conn: Conn, pacer: Pacer, sub: Subscription, n: int) -> None:
    """One operation of the property below on `sub`; `n` varies it."""
    family = sub.topic.family.family
    if step == "offer" and family == "book":
        pacer.offer(sub, _bid(str(100 + n), str(n % 3)))
    elif step == "offer" and family == "trades":
        pacer.offer(sub, {"symbol": "BTCUSDT", "trades": [_print(n)]})
    elif step == "offer":
        column = {**_COLUMN, "t_ms": 500 * n, "complete": n % 2 == 0}
        pacer.offer(sub, {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": [column]})
    elif step == "tick":
        conn.clock.now += n / 10
        pacer.tick()
    elif step == "drop":
        pacer.drop(sub)
    elif step == "pause":  # paused or resumed; a held window is shed
        sub.effective["paused"] = sub.effective.get("paused") is not True
        pacer.shed(sub)
    elif step == "classify":  # re-paces every window, folding or refusing some
        pacer.classify(25.0 * n, list(conn.authz.by_id.values()))
    elif step == "snapshot":  # a pending window goes stale
        conn.emitter.snapshot(sub, "client_resync")
    else:  # `discard` (the drop hook's) or `forget`
        getattr(pacer, step)(sub.sub_id)


@given(st.lists(st.tuples(st.sampled_from(_STEPS), st.integers(0, 2), st.integers(0, 4))))
@example([("offer", 0, 1), ("offer", 0, 2), ("classify", 0, 1)])  # lagging folds the frames
def test_pending_total_is_maintained_incrementally(ops: list[tuple[str, int, int]]) -> None:
    """Plan §6, #2552: after any run of steps the kept total equals the sum over the lanes."""
    conn, pacer = _paced()
    subs = [_subscribed(conn, _BOOK, coalesce=False)]  # whole frames, folded when it lags
    subs += [_subscribed(conn, ch) for ch in (_TRADES, "heatmap.BTCUSDT")]
    for step, i, n in ops:
        _step(step, conn, pacer, subs[i], n)
        assert pacer.pending_bytes == sum(lane.queue.pending_bytes for lane in pacer.lanes.values())
