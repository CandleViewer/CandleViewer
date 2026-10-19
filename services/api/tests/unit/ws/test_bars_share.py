"""#399 (E12-T06) D8, SR-E12-07 part 1, flag on: queued `bars` frames hold at most 50 % of each
limit of the outbound budget (`23-ws-protocol.md` §8.4), so a slow reader's `bars` backlog never
re-snapshots its `book` or `trades`: over the share alone step 1 sheds `bars` only (`drop_share`).
Unit tests on a `_seq_support.Conn`; router rows behind `_Wire`, `cv.v1.json` and `cv.v1.msgpack`.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from inspect import signature
from itertools import product
from typing import Any, get_args

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.bars.models import Bar
from candleviewer.bars.spec import WireBarType
from candleviewer.ws import bars_wire, limits, outbound
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.bars_wire import ITEM_MAX_BYTES, TIME_KINDS, bar_item
from candleviewer.ws.codec import encode_server_frame
from candleviewer.ws.outbound import Backpressure, LadderEvent, OutboundQueue, Queued, encode
from candleviewer.ws.pacing import Pacer
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import OWNER_META_MAX_BYTES, SnapshotBody, _dumps
from candleviewer.ws.topics import FAMILIES
from tests.unit.test_settings_ws_backpressure import FLOOR_BYTES, FLOOR_FRAMES
from tests.unit.ws._seq_support import Conn, Source
from tests.unit.ws.test_outbound import RS, _bid, _checking_push, _drain, _frame, _setup, _sub
from tests.unit.ws.test_pipeline_outbound import _DEADLINE_S, _ENCODINGS, _overflow, _Rig, _Wire

_BARS, _BOOK, _TRADES = "bars.BTCUSDT.time.1", "book.BTCUSDT.50", "trades.BTCUSDT"
_SERIES = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1"}
_OHLCV = {"o": "1", "h": "2", "l": "1", "c": "2", "v": "3", "confirm": False}
_TRADE = {"id": "t", "ts_ms": 1, "price": "1", "size": "1", "side": "buy"}
_PRINT = {"symbol": "BTCUSDT", "trades": [_TRADE]}
_REASONS = ("drop", "drop_share", "resnapshot", "close_budget", "close_redrop")


def _bars(*indexes: int) -> dict[str, Any]:
    items = [{"generation": 0, "index": i, "t_ms": 60_000 * i, **_OHLCV} for i in indexes]
    return {**_SERIES, "bars": items}


def _counts() -> list[float]:
    return [_overflow(reason) for reason in _REASONS]


def _grew(before: list[float]) -> dict[str, float]:
    """`cv_ws_overflow_total` by reason: what grew since `before`."""
    return {r: n - b for r, n, b in zip(_REASONS, _counts(), before, strict=True) if n != b}


def _checked(conn: Conn, ladder: Backpressure, events: list[LadderEvent]) -> None:
    """A check after every push, on the connection's live subscriptions, as the pipeline runs it;
    its events go to `events`."""
    pushed = conn.emitter.push

    def push(frame: dict[str, Any]) -> None:
        pushed(frame)
        events.extend(ladder.check(conn.authz.by_id.values()))

    conn.emitter.push = push


def _rig(
    max_bytes: int = 6_000, max_frames: int = 40
) -> tuple[Conn, Pacer, OutboundQueue, Backpressure, list[Subscription], Source]:
    """`_setup`'s connection with a `bars`, a `book` and a `trades` subscription past their
    initial snapshots, and the ladder over its queue."""
    conn, pacer, queue, source = _setup(max_bytes, max_frames)
    source.bodies["bars"] = SnapshotBody(_bars())
    subs = [_sub(conn, queue, ch) for ch in (_BARS, _BOOK, _TRADES)]
    return conn, pacer, queue, Backpressure(queue, pacer), subs, source


def test_bars_share_is_half_of_each_limit_rounded_down_and_never_zero() -> None:
    assert limits.BARS_SHARE_PCT == 50
    for budget, share in (
        ((), (4 * 2**20, 1_000)),  # the contract budget
        ((FLOOR_BYTES, FLOOR_FRAMES), (2 * 2**20, 128)),  # the `Settings` floors
        ((201, 3), (100, 1)),
        ((1, 1), (1, 1)),  # a harness budget of one: `share_pct` never divides by zero
    ):
        queue = OutboundQueue(*budget)
        assert (queue.share_max_bytes, queue.share_max_frames) == share


_POOL = (
    _frame("d", _BARS),
    _frame("snap", _BARS) | {"meta": {"reason": "backpressure"}},
    _frame("d", _BARS) | {"rs": RS},
    _frame("err", _BARS),
    _frame("d", _BOOK),
    _frame("d", "orders"),
)
_OPS = st.lists(st.tuples(st.integers(0, 3), st.integers(0, 5), st.integers(0, 300)), max_size=50)


@settings(max_examples=150, deadline=None, derandomize=True, database=None)
@given(st.booleans(), _OPS)
def test_bars_share_counters_equal_a_recount(packed: bool, ops: list[tuple[int, int, int]]) -> None:
    """Push, pop, drop and clear in any order, on either codec: the counters are the sums of the
    queued `bars` `d` and `snap` frames, live and replay, at wire length; a control frame naming
    a `bars` topic, and every other family, never count."""
    queue = OutboundQueue()
    dumps: outbound.FrameEncoder = encode_server_frame if packed else outbound.json_payload
    for op, i, pad in ops:
        if op == 0:
            queue.push(encode(_POOL[i] | {"p": {"pad": "x" * pad}}, dumps))
        elif op == 1:
            queue.pop()
        elif op == 2:
            queue.drop({((_BARS, None), (_BARS, RS), (_BOOK, None))[i % 3]})
        else:
            queue.clear(normal_only=i % 2 == 0)
        bars = [f for f in queue._normal if f.family == "bars" and f.droppable]
        assert (queue.share_bytes, queue.share_frames) == (sum(f.size for f in bars), len(bars))


@pytest.mark.parametrize("limb", ["bytes", "frames"])
def test_bars_share_is_over_strictly_past_either_limit(limb: str) -> None:
    """As `over_budget`: at exactly half a limit the share is full, not over; one byte or one
    frame more is over, the budget still not."""
    queue = OutboundQueue(max_bytes=200, max_frames=10)  # a share of 100 B or 5 frames

    def bars(size: int) -> Queued:
        return Queued("x" * size, family="bars", key=(_BARS, None))

    for frame in [bars(100)] if limb == "bytes" else [bars(0)] * 5:
        queue.push(frame)
    assert (queue.share_over(), queue.share_pct()) == (False, 100.0)
    queue.push(bars(1 if limb == "bytes" else 0))
    assert queue.share_over() and not queue.over_budget()


def test_over_the_share_alone_step_1_sheds_bars_and_nothing_else() -> None:
    """Every `bars` subscription holding queued frames or a window is dropped and marked, once in
    `drop_share`, and the frames of a `bars` stream no longer subscribed go too. `book` and
    `trades` keep their frames, windows and `s`, live or awaiting another `snap`, and so does
    another family's stream no longer subscribed."""
    conn, pacer, queue, ladder, subs, _ = _rig(max_bytes=60_000)  # a share of 20 frames
    bars, book, trades = subs
    for sub, body in ((bars, _bars(1)), (book, _bid("BTCUSDT", "90"))):
        pacer.offer(sub, body)  # the leading edge leaves at once...
        pacer.offer(sub, body)  # ...and the next one waits in the window
    conn.emitter.delta(trades, _PRINT)
    for i in range(20):  # the 21st queued `bars` frame
        conn.emitter.delta(bars, _bars(i))
    queue.push(encode(_frame("d", _BARS) | {"rs": RS}))
    queue.push(encode(_frame("d", "trades.ETHUSDT")))
    book.snapshot_pending, book.pending_reason = True, "client_resync"
    kept, window = [f for f in queue._normal if f.family != "bars"], pacer.lanes[book.sub_id].bytes
    assert queue.share_over() and not ladder.over_budget() and window > 0
    before = _counts()
    assert ladder.check(subs) == [LadderEvent("drop", (_BARS,), "share")]
    assert list(queue._normal) == kept and (queue.share_bytes, queue.share_frames) == (0, 0)
    assert (pacer.lanes[book.sub_id].bytes, pacer.lanes[bars.sub_id].bytes) == (window, 0)
    assert pacer.resnapshot_required == {bars.sub_id: bars}
    assert (bars.pending_reason, book.pending_reason) == ("backpressure", "client_resync")
    assert not trades.snapshot_pending and _grew(before) == {"drop_share": 1}


@pytest.mark.parametrize(("n_bars", "n_book"), [(2, 7), (5, 4)], ids=["share_under", "share_over"])
def test_over_the_whole_budget_every_family_drops_as_before(n_bars: int, n_book: int) -> None:
    """Nine frames against eight, the share (4 frames) under or over too: step 1 as before,
    every throttled topic holding frames dropped and counted `drop`."""
    conn, _, queue, ladder, subs, _ = _rig(max_frames=8)
    for i in range(n_bars):
        conn.emitter.delta(subs[0], _bars(i))
    for i in range(n_book):
        conn.emitter.delta(subs[1], _bid("BTCUSDT", str(90 + i)))
    assert ladder.over_budget() and queue.share_over() == (n_bars > 4)
    before = _counts()
    assert ladder.check(subs) == [LadderEvent("drop", (_BARS, _BOOK))]
    assert len(queue) == 0 and _grew(before) == {"drop": 2}


def test_over_the_share_a_paused_bars_subscription_is_shed_without_the_mark() -> None:
    """D16 under the share: its queued frames and window go, uncounted; its resume re-snapshots."""
    conn, pacer, queue, ladder, subs, _ = _rig(max_frames=10)  # a share of 5 frames
    for i in range(6):
        conn.emitter.delta(subs[0], _bars(i))
    pacer.offer(subs[0], _bars(9))
    pacer.offer(subs[0], _bars(9))  # in the window
    subs[0].effective["paused"] = True
    before = _counts()
    assert ladder.check(subs) == [] and _grew(before) == {}
    assert (subs[0].snapshot_pending, pacer.resnapshot_required) == (False, {})
    assert (queue.share_frames, pacer.pending_bytes) == (0, 0)


@settings(max_examples=100, deadline=None, derandomize=True, database=None)
@given(st.lists(st.tuples(st.integers(0, 4), st.integers(0, 400)), max_size=40))
@example([(0, 400)] * 9)  # nine `bars` frames: past the 3 000 B share, under the budget
def test_a_check_drops_another_familys_frame_only_over_the_whole_budget(
    pushes: list[tuple[int, int]],
) -> None:
    """A check after every push, as the pipeline runs it: until the budget is first over, no
    other family loses a frame or is marked, and no `bars` frame outlives a check."""
    _, _, queue, ladder, subs, _ = _rig()  # a share of 3 000 B or 20 frames
    pool = ((_BARS, None), (_BARS, RS), (_BOOK, None), (_TRADES, None), ("trades.ETHUSDT", None))
    for i, pad in pushes:
        ch, rs = pool[i]
        queue.push(encode(_frame("d", ch, pad="x" * pad) | ({"rs": rs} if rs else {})))
        if ladder.over_budget():
            return
        kept = [f for f in queue._normal if f.family != "bars"]
        assert set(ladder.check(subs)) <= {LadderEvent("drop", (_BARS,), "share")}
        assert [f for f in queue._normal if f.family != "bars"] == kept and not queue.share_over()
        assert not any(sub.snapshot_pending for sub in subs[1:])


def test_drain_holds_a_bars_snapshot_from_half_its_share_and_sends_the_next_one() -> None:
    """A `bars` snapshot waits while the queued `bars` frames hold half the share or more; `drain`
    passes over it, so the `book` snapshot behind it goes out; it follows below half."""
    _, pacer, queue, ladder, subs, _ = _rig(max_frames=40)  # a share of 20 frames
    for sub in subs[:2]:
        pacer.drop(sub)
    for _ in range(10):
        queue.push(encode(_frame("d", "bars.BTCUSDT.time.5")))
    assert queue.share_pct() == outbound.DRAIN_PCT > queue.pct()
    assert ladder.drain() == [LadderEvent("resnapshot", (_BOOK,))]
    assert list(pacer.resnapshot_required) == [subs[0].sub_id]
    queue.pop()  # 9 of 20
    assert ladder.drain() == [LadderEvent("resnapshot", (_BARS,))]


def test_a_bars_snapshot_over_the_share_closes_redrop_at_its_third_drop() -> None:
    """Step 3's second trigger: a `bars` snapshot larger than the share, though under the budget,
    is dropped unsent by the check after its pushes; the third drop in a row closes
    `slow_consumer` (`close_redrop`), the topic in the hint."""
    conn, pacer, _, ladder, subs, source = _rig(max_bytes=8_000)  # a share of 4 000 B
    source.bodies["bars"] = SnapshotBody(_bars(*range(50)))  # about 5 KB
    source.gen += 1
    _checking_push(conn, ladder, subs)
    pacer.drop(subs[0])
    before, events = _counts(), list[LadderEvent]()
    for _ in range(outbound.MAX_REDROPS):
        events = ladder.drain()
    assert events == [
        LadderEvent("resnapshot", (_BARS,)),
        LadderEvent("drop", (_BARS,), "share"),
        LadderEvent("close", (_BARS,), "redrop"),
    ]
    assert _grew(before) == {"drop_share": 3, "resnapshot": 3, "close_redrop": 1}


def test_a_share_check_keeps_another_familys_redrop_count() -> None:
    """A `book` snapshot dropped unsent once, then queued again: a check over the share alone
    forgets no record of a subscription that has not ended, so a third drop still closes."""
    _, pacer, queue, ladder, subs, _ = _rig()  # 40 frames, a share of 20
    bars, book, trades = subs
    pacer.drop(book)
    assert ladder.drain() == [LadderEvent("resnapshot", (_BOOK,))]
    for _ in range(40):
        queue.push(encode(_frame("d", _TRADES)))
    assert ladder.check(subs) == [LadderEvent("drop", (_BOOK, _TRADES))]
    assert ladder.drain() == [LadderEvent("resnapshot", (_BOOK,))]  # its second try, queued
    for _ in range(21):
        queue.push(encode(_frame("d", _BARS)))
    assert ladder.check(subs) == [LadderEvent("drop", (_BARS,), "share")]
    assert ladder._redrops == {book.sub_id: 1} and book.sub_id in ladder._snapped
    assert trades.sub_id in pacer.resnapshot_required and bars.sub_id not in ladder._redrops


def test_a_bars_snapshot_sent_before_the_next_share_drop_starts_no_redrop_run() -> None:
    """Step 3: a run ends when the snapshot is sent. Four times over: the 21st `bars` frame passes
    the share, `drain` queues the snapshot and the reader takes everything. The share check settles
    it, so no drop is a redrop and nothing closes."""
    conn, _, queue, ladder, subs, _ = _rig(max_bytes=60_000)  # a share of 20 frames
    events: list[LadderEvent] = []
    _checked(conn, ladder, events)
    before = _counts()
    for _ in range(outbound.MAX_REDROPS + 1):
        for i in range(21):
            conn.emitter.delta(subs[0], _bars(i))
        events += ladder.drain()
        while queue.pop() is not None:
            pass
    assert [e.reason for e in events] == ["drop_share", "resnapshot"] * 4
    assert ladder._redrops == {} and _grew(before) == {"drop_share": 4, "resnapshot": 4}


def test_an_attach_burst_past_the_share_recovers_one_snapshot_at_a_time_without_a_close() -> None:
    """§8.4: two `bars` topics attached at once whose snapshots pass the share before the reader
    reads anything are shed and come back as `backpressure` snaps, one queued at a time while
    each holds half the share or more, to a reader that takes every frame; nothing closes."""
    conn, pacer, queue, ladder, _, source = _rig(max_bytes=12_000)  # a share of 6 000 B
    source.bodies["bars"] = SnapshotBody(_bars(*range(32)))  # about 3.3 KB
    events: list[LadderEvent] = []
    _checked(conn, ladder, events)
    before = _counts()
    for ch in ("bars.BTCUSDT.time.5", "bars.BTCUSDT.time.15"):
        conn.sub({"ch": ch, "opts": {"encoding": "structured"}})
    assert [(e.action, len(e.topics)) for e in events] == [("drop", 2)]
    sent: list[bool] = []
    while True:
        for _ in range(2):  # a drain after the send and after a wake: never a second snapshot
            events += ladder.drain(conn.authz.by_id)
            assert queue.share_frames <= 1
        frame = queue.pop()
        if frame is None:
            break
        sent.append(frame.resnap)
    assert sent == [True, True] and pacer.resnapshot_required == {}
    assert "close" not in {e.action for e in events}
    assert _grew(before) == {"drop_share": 2, "resnapshot": 2}


def test_the_largest_bars_snapshot_fits_half_the_share_at_the_default_and_floor_budgets() -> None:
    """§8.4: a `bars` snapshot queued while the client drains has as little as half the share. The
    largest by the declared bounds (`history`, `ITEM_MAX_BYTES`, the owner `meta`) fits that at the
    default budget; the widest one a snapshot can carry (no `amended`) fits it at the floors too."""
    conn, _, queue, _, subs, _ = _rig()
    conn.emitter.snapshot(subs[0], "backpressure")  # an empty `bars` snapshot: its envelope
    hi = FAMILIES["bars"].options["history"].hi
    assert hi is not None
    largest = queue.share_bytes + OWNER_META_MAX_BYTES + int(hi) * (ITEM_MAX_BYTES + 1)
    assert largest <= OutboundQueue().share_max_bytes // 2
    reachable = queue.share_bytes + OWNER_META_MAX_BYTES + int(hi) * (_widest_item_bytes() + 1)
    assert reachable <= OutboundQueue(FLOOR_BYTES, FLOOR_FRAMES).share_max_bytes // 2


def test_a_close_after_share_drops_names_only_the_bars_topics() -> None:
    """`bye.hint` of a redrop close fired by a share check ranks the `bars` topics alone, though
    a larger `book` backlog and a `book` window sit beside them."""
    _, pacer, queue, ladder, subs, source = _rig(max_bytes=12_000)  # a share of 6 000 B
    bars, book, _ = subs
    source.bodies["bars"] = SnapshotBody(_bars(*range(32)))  # about 3.3 KB
    source.gen += 1
    for price in ("90", "91"):
        pacer.offer(book, _bid("BTCUSDT", price))  # the second waits in the window
    queue.push(encode(_frame("d", _BOOK, pad="x" * 4_500)))
    pacer.drop(bars)
    events: list[LadderEvent] = []
    for _ in range(outbound.MAX_REDROPS):
        events = ladder.drain()  # the `bars` snapshot, then a stream no longer subscribed
        queue.push(encode(_frame("d", "bars.BTCUSDT.time.5", pad="x" * 2_900)))
        events += ladder.check(subs)
    assert events[-1] == LadderEvent("close", (_BARS, "bars.BTCUSDT.time.5"), "redrop")


def test_a_share_overflow_that_goes_over_the_budget_ranks_every_topic_there() -> None:
    """#3365: the episode's first check found the share exceeded and ranked the `bars` topics. When
    the budget is exceeded the ladder runs for every family alike, so the close names the topics
    ranked at the first check over the budget: the book and the tape, not the `bars` topic."""
    conn, _, queue, ladder, subs, _ = _rig()  # 40 frames, a share of 20
    bars, book, trades = subs
    for i in range(21):
        conn.emitter.delta(bars, _bars(i))
    assert ladder.check(subs) == [LadderEvent("drop", (_BARS,), "share")]
    for i in range(12):
        conn.emitter.delta(book, _bid("BTCUSDT", str(90 + i)))
    for _ in range(6):
        conn.emitter.delta(trades, _PRINT)
    for _ in range(41):  # more than the budget, and nothing step 1 can shed
        queue.push(encode(_frame("err")))
    assert ladder.check(subs) == [
        LadderEvent("drop", (_BOOK, _TRADES)),
        LadderEvent("close", (_BOOK, _TRADES), "budget"),
    ]


def test_a_share_check_after_a_budget_overflow_names_the_bars_topics_it_ranked() -> None:
    """#3365: the episode began over the whole budget, which ranked the book. The close that a
    later check over the share alone fires, the third redrop of a `bars` snapshot, names `bars`
    topics only, in the order of the first check over the share: the stream no longer subscribed
    has outgrown the snapshot by the close, and is still named second."""
    _, pacer, queue, ladder, subs, source = _rig(max_bytes=12_000)  # a share of 6 000 B
    source.bodies["bars"] = SnapshotBody(_bars(*range(32)))  # about 3.3 KB
    source.gen += 1
    pacer.drop(subs[0])  # `bars` is marked first: each drain tries it before the book
    queue.push(encode(_frame("d", _BOOK, pad="x" * 12_000)))  # over the budget: the book is shed
    assert ladder.check(subs) == [LadderEvent("drop", (_BOOK,))]
    for ch in (_BOOK, "orders"):  # a book and an `orders` frame beside the `bars` ones
        queue.push(encode(_frame("d", ch, pad="x" * 900)))
    events: list[LadderEvent] = []
    for pad in (2_900, 2_900, 2_900, 4_000):  # the second drain is the book's snapshot
        events = ladder.drain()
        queue.push(encode(_frame("d", "bars.BTCUSDT.time.5", pad="x" * pad)))
        events += ladder.check(subs)
    assert events[-1] == LadderEvent("close", (_BARS, "bars.BTCUSDT.time.5"), "redrop")


def test_a_second_share_overflow_ranks_its_own_bars_topic_and_a_budget_close_names_it() -> None:
    """#3365: two overflows of the share alone, by two `bars` topics, the first recovered between
    them: the second ranks its own topic. Control frames then take the budget over with no topic
    left to rank, so the close names the share's ranking: never empty when a topic held bytes."""
    conn, _, queue, ladder, subs, _ = _rig()  # 40 frames, a share of 20
    five = _sub(conn, queue, "bars.BTCUSDT.time.5")
    subs.append(five)
    for _ in range(21):
        queue.push(encode(_frame("d", _BARS)))
    assert ladder.check(subs) == [LadderEvent("drop", (_BARS,), "share")]
    assert ladder.drain() == [LadderEvent("resnapshot", (_BARS,))]
    _drain(queue)  # the writer sends the snapshot
    assert ladder.check(subs) == []  # both limits met, nothing awaited: that overflow is over
    for _ in range(21):
        queue.push(encode(_frame("d", five.ch)))
    assert ladder.check(subs) == [LadderEvent("drop", (five.ch,), "share")]
    for _ in range(41):  # over the budget, with nothing step 1 can shed
        queue.push(encode(_frame("err")))
    assert ladder.check(subs) == [LadderEvent("close", (five.ch,), "budget")]


def test_a_budget_close_after_a_share_check_names_the_budget_ranking() -> None:
    """#3365: one ranking per limit. The episode's first check, over the budget, ranks the book and
    the tape; a later check over the share alone ranks `bars`; control frames then take the budget
    over again, and the close names the budget's ranking, which the share's left as it was."""
    _, _, queue, ladder, subs, _ = _rig()  # 40 frames, a share of 20
    for ch, pad in ((_BOOK, 900), (_TRADES, 600)):
        queue.push(encode(_frame("d", ch, pad="x" * pad)))
    for _ in range(39):
        queue.push(encode(_frame("err")))
    assert ladder.check(subs) == [LadderEvent("drop", (_BOOK, _TRADES))]
    for _ in range(20):
        queue.pop()  # the reader takes 20 of the control frames: 19 are left
    for _ in range(21):
        queue.push(encode(_frame("d", _BARS)))
    assert ladder.check(subs) == [LadderEvent("drop", (_BARS,), "share")]
    for _ in range(22):
        queue.push(encode(_frame("err")))
    assert ladder.check(subs) == [LadderEvent("close", (_BOOK, _TRADES), "budget")]


@_ENCODINGS
async def test_a_slow_reader_mostly_bars_keeps_book_and_trades_and_resnapshots_bars(
    encoding: str,
) -> None:
    """AC-06: the writer is held while `bars`, `book` and `trades` deltas queue, each leaving its
    window at once; the 21st `bars` frame passes the share of a 40-frame budget, 35 queued.
    Step 1 sheds `bars` alone: once the reader drains, `book` and `trades` arrive whole, `s`
    contiguous and no `snap`, and `bars` gets one `backpressure` snapshot."""
    config = BackpressureConfig(max_frames=40, classify_interval_ms=60_000)  # no probe
    rig, sock = _Rig(config), _Wire(encoding)
    rig.source.bodies["bars"] = SnapshotBody(_bars())
    rig.source.bodies["trades"] = SnapshotBody({**_PRINT, "trades": []})
    before = _counts()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        first = {ch: (await rig.sub(sock, ch, throttle_ms=50))[1]["s"] for ch in (_BOOK, _TRADES)}
        await rig.sub(sock, _BARS, throttle_ms=50)
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()  # the writer holds it: what follows queues behind it
        for i in range(27):
            rig.clock.now += 0.05
            if i < 21:
                rig.sequencing.publish(_BARS, _bars(i))
            if i % 3 == 0:
                rig.sequencing.publish(_BOOK, _bid("BTCUSDT", str(90 + i)))
            elif i % 3 == 1:
                rig.sequencing.publish(_TRADES, _PRINT)
        sock.release()
        held, *frames, snap = await sock.next(20)
        assert conn.pipeline is not None and len(conn.pipeline.queue) == 0
        handler.cancel()
        await asyncio.wait({handler})
    assert (held["p"]["kind"], snap["t"], snap["ch"]) == ("held", "snap", _BARS)
    assert snap["meta"]["reason"] == "backpressure"
    for ch in (_BOOK, _TRADES):
        mine = [(f["t"], f["s"]) for f in frames if f["ch"] == ch]
        assert mine == [("d", s) for s in range(first[ch] + 1, first[ch] + 10)]
    assert _grew(before) == {"drop_share": 1, "resnapshot": 1}


@_ENCODINGS
async def test_flag_off_has_no_share_its_push_bound_is_the_control(encoding: str) -> None:
    """Ruling Q1: 600 `bars` deltas held, past half the 1 024-frame push bound, all arrive."""
    rig, sock, before = _Rig(backpressure=None), _Wire(encoding), _counts()
    rig.source.bodies["bars"] = SnapshotBody(_bars())
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        first = (await rig.sub(sock, _BARS))[1]["s"]
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()
        for i in range(600):
            rig.sequencing.publish(_BARS, _bars(i))
        sock.release()
        _, *frames = await sock.next(601)
        handler.cancel()
        await asyncio.wait({handler})
    assert getattr(conn, "pipeline", None) is None and _grew(before) == {}
    assert [(f["t"], f["s"]) for f in frames] == [("d", s) for s in range(first + 1, first + 601)]


#: What `bar_item` emits for a snapshot item of a non-time kind (no `amended`): the keys of every
#: item, `close_t_ms` and `_DELTA_KEYS`. A time kind has no `close_t_ms`, and the delta keys are
#: there only with `include_delta`.
_DELTA_KEYS = {*"delta min_delta max_delta".split()}
_ITEM_KEYS = {
    *"generation index t_ms o h l c v turnover trades confirm close_t_ms".split(),
    *_DELTA_KEYS,
}
_KEYS_MSG = (
    "bar_item's keys changed: widen a new key above (a Bar decimal already is) and list it in "
    "_ITEM_KEYS; a key only some items carry needs a rule where `keys` is set, as close_t_ms and "
    "the delta keys have; if only some values emit it, the rule must also build the widest item "
    "that carries it, every other field at its widest"
)
_UNSET_MSG = (
    "a Bar field is None in _bar() (test_bars_wire.py): set it there, so that it is widened and "
    "measured"
)
#: Every parameter of `bar_item`: one added later may open a path that no item below takes.
_ITEM_PARAMS = {"bar", "generation", "bar_kind", "include_delta", "amended"}
_PARAMS_MSG = "bar_item has a new parameter: exercise it below, then list it in _ITEM_PARAMS"


def _widest_item_bytes() -> int:
    """The JSON size of the widest `bars[]` item a snapshot can carry: a `Bar` in every state of
    its flags (each `bool` field but `synthetic`, which `bar_item` refuses) and of every bar kind,
    with `include_delta` on and off, every `Bar` decimal at the widest `bar_item` sends (the model
    names them, the module's bounds give the width) and every integer at its `_INTS` bound. A
    second value set, a positive decimal and zero in every integer, shows a key that only some
    values emit. `amended` is left out: `BarsSnapshotSource` never sets it. The widest item is a
    forming bar's: its `confirm` is a byte longer.

    The string and integer equality asserts in the loop prove the widening (every string is the
    set's decimal, every integer is one of its integers); the comparison that ends the helper only
    backs them up. Not seen: a key gated on what two uniform value sets cannot show (a decimal of
    zero; a relation between fields, such as `high > low` or `close_time > open_time`; a mix of the
    two sets' values, such as `index > 0` with `delta > 0`). A rule for a key only some values emit
    must also build the widest item that carries it, every other field at its widest: the second
    set measures that key beside narrower values."""
    # Imported here: renaming a name `test_bars_wire.py` imports fails this pin, not the collection.
    from tests.unit.ws.test_bars_wire import _bar

    assert set(signature(bar_item).parameters) == _ITEM_PARAMS, _PARAMS_MSG
    sample = _bar()
    # a field the sample leaves `None` is neither widened nor emitted in any item measured below
    unset = [name for name in Bar.model_fields if getattr(sample, name) is None]
    assert not unset, f"{_UNSET_MSG}: {unset}"
    adjusted, places = bars_wire._MAX_DEC_ADJUSTED, bars_wire._MAX_DEC_PLACES
    # sign, `adjusted + 1` integer digits, a point, `places` places: 79 at 38
    nines = Decimal("-" + "9" * (adjusted + 1) + "." + "9" * places)
    # `Px`, `Qty` and `Notional` are type aliases, so the sample's values name the decimal fields
    decimals = [name for name in Bar.model_fields if isinstance(getattr(sample, name), Decimal)]
    # a flag is a field whose sample value is a `bool`, as a decimal is found; `synthetic` is the
    # one `bar_item` refuses (a `densify()` filler)
    flags = [
        n for n in Bar.model_fields if isinstance(getattr(sample, n), bool) and n != "synthetic"
    ]
    states = [dict(zip(flags, on, strict=True)) for on in product((False, True), repeat=len(flags))]
    ints = dict(bars_wire._INTS)  # `generation` is an argument of `bar_item`, not a `Bar` field
    generation = ints.pop("generation")
    # (decimal, generation, the rest of the integers): every field at its widest; then a positive
    # decimal and zero in every integer, which shows a key gated on `bar.delta > 0` or `index == 0`
    value_sets = [(nines, generation, ints), (nines.copy_abs(), 0, dict.fromkeys(ints, 0))]
    sizes = []
    for decimal, gen, rest in value_sets:
        # `t_ms` and `close_t_ms` are the microsecond times floored to the millisecond
        integers = {gen, *rest.values(), rest["open_time"] // 1000, rest["close_time"] // 1000}
        wide = {**dict.fromkeys(decimals, decimal), **rest}
        for state, kind, flow in product(states, get_args(WireBarType), (True, False)):
            bar = _bar(**state).model_copy(update=wide)
            item = bar_item(bar, generation=gen, bar_kind=kind, include_delta=flow)
            keys = _ITEM_KEYS - {"close_t_ms"} if kind in TIME_KINDS else _ITEM_KEYS
            assert set(item) == (keys if flow else keys - _DELTA_KEYS), _KEYS_MSG
            # a listed key is not a widened one: every decimal and integer takes the set's value
            assert {v for v in item.values() if isinstance(v, str)} == {format(decimal, "f")}
            assert {v for v in item.values() if type(v) is int} <= integers  # not `confirm`
            sizes.append(len(_dumps(item)))
    # a backstop for the equality asserts: the widest item against the same forming non-time bar
    # unwidened, at the same `generation`. With the widening off the two are one item, so this
    # fails; against a closed bar at `generation=0` it would not (`confirm`, `generation`)
    plain = bar_item(_bar(closed=False), generation=generation, bar_kind="tick", include_delta=True)
    assert max(sizes) > len(_dumps(plain)), "the widening changed no item"
    return max(sizes)
