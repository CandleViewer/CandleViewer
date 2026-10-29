"""E21-T01 (#604): the `book` WS topic's publisher (`book/ws_topic.py`) against a fake hub, on a
fake clock: windows per (symbol, depth), the publisher's own cadence, the level that leaves the
window, the lifecycle edges (desync, resync, tier swap, going live) and the bounds."""

from __future__ import annotations

import asyncio
import itertools
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.book.models import BookDesyncEvent, BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.book.snapshot_source import BookSnapshotSource, Record
from candleviewer.book.ws_topic import WINDOW_S, BookSub, BookTopic
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import StreamInvalidated, Topic
from candleviewer.exchange.base.models import BookLevel

from ._builders import delta, lvl, snap

SYM = "BTCUSDT"
STEPS = (Decimal("0.1"), Decimal(1))


@dataclass(frozen=True)
class _T:
    symbol: str | None
    depth: int | None


@dataclass
class Sub:
    ch: str
    topic: _T
    replay_session_id: str | None = None
    snapshot_pending: bool = True
    ended: bool = False
    held: dict[str, dict[Decimal, Decimal]] = field(default_factory=dict)
    built: Any = None


def sub(depth: int, symbol: str = SYM, replay: str | None = None) -> Sub:
    return Sub(f"book.{symbol}.{depth}", _T(symbol, depth), replay)


@dataclass
class Hub:
    """The hub's four calls the topic makes; a `d` is applied to each subscription's `held`."""

    subs: list[Sub] = field(default_factory=list)
    frames: list[tuple[str, dict[str, Any], Any, int]] = field(default_factory=list)
    desyncs: list[str] = field(default_factory=list)
    flushes: int = 0

    def subscriptions(self, ch: str) -> Sequence[BookSub]:
        return [s for s in self.subs if s.ch == ch and s.replay_session_id is None]

    def publish(
        self,
        ch: str,
        body: Mapping[str, Any] | None = None,
        *,
        part: Any = None,
        coalesced_count: int = 1,
    ) -> int:
        assert body is not None
        self.frames.append((ch, dict(body), part, coalesced_count))
        n = 0
        for s in self.subscriptions(ch):
            if not s.snapshot_pending:
                for side in ("bids", "asks"):
                    for p, q in body[side]:
                        if Decimal(q) == 0:
                            s.held[side].pop(Decimal(p), None)
                        else:
                            s.held[side][Decimal(p)] = Decimal(q)
                n += 1
        return n

    def upstream_desync(self, symbol: str) -> int:
        self.desyncs.append(symbol)
        for s in self.subs:
            if s.topic.symbol == symbol:
                s.snapshot_pending = True
        return 0

    def flush_pending(self, match: Any = None) -> int:
        self.flushes += 1
        return 0


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def body(
    structured: Mapping[str, Any], records: tuple[Record, ...], trailer: Any, **kw: Any
) -> Any:
    return {"structured": dict(structured), "records": records, "trailer": trailer, **kw}


class World:
    def __init__(self, depth: int = 200) -> None:
        self.out: list[object] = []
        self.resubs = 0
        self.engines: dict[str, BookEngine] = {}
        self.hub = Hub()
        self.clock = Clock()
        self.latency: list[tuple[str, int, float]] = []
        self.active: dict[int, int] = {}
        source = BookSnapshotSource(self.engines.get, lambda _s: STEPS, body)
        self.topic = BookTopic(
            source, self.hub.subscriptions, self.hub.publish, self.hub.upstream_desync,
            self.hub.flush_pending, lambda r, ps, qs: (r, ps, qs), bus=Bus(), env="live",
            clock=self.clock, publish_latency=lambda s, d, ms: self.latency.append((s, d, ms)),
            active=lambda d, n: self.active.__setitem__(d, n),
        )  # fmt: skip
        self.depth = depth

    async def engine(self, symbol: str = SYM, depth: int | None = None) -> BookEngine:
        async def publish(ev: object) -> None:
            self.out.append(ev)

        async def resub() -> None:
            self.resubs += 1

        eng = BookEngine(
            symbol=symbol, depth=depth or self.depth, publish=publish, resubscribe=resub,
            now_us=lambda: 0, incidents=True,
        )  # fmt: skip
        self.engines[symbol] = eng
        await eng.start()
        return eng

    async def feed(self, eng: BookEngine, ev: Any) -> None:
        """One upstream event through the engine, and what it published to the topic."""
        start = len(self.out)
        await eng.on_event(ev)
        for item in self.out[start:]:
            self.topic.offer(item)

    def attach(self, s: Sub) -> Sub:
        """A subscription's `snap`: the built window becomes what it holds."""
        if s not in self.hub.subs:
            self.hub.subs.append(s)
        built = s.built = self.topic.build(s)
        if built is not None:
            st = built["structured"]
            s.held = {
                side: {Decimal(p): Decimal(q) for p, q in st[side]} for side in ("bids", "asks")
            }
            s.snapshot_pending = False
        return s


def top(eng: BookEngine, n: int) -> dict[str, dict[Decimal, Decimal]]:
    assert eng.book is not None
    bids, asks = eng.book.top(n)
    return {"bids": {b.price: b.qty for b in bids}, "asks": {a.price: a.qty for a in asks}}


def ladder(best_bid: int, best_ask: int, n: int) -> tuple[list[BookLevel], list[BookLevel]]:
    return [lvl(best_bid - i, 1) for i in range(n)], [lvl(best_ask + i, 1) for i in range(n)]


async def live(w: World, n: int = 60) -> BookEngine:
    eng = await w.engine()
    bids, asks = ladder(1000, 1001, n)
    await w.feed(eng, snap(10, bids, asks))
    assert eng.phase is BookPhase.LIVE
    return eng


async def test_independent_depth_subscriptions_each_get_their_own_depth() -> None:
    """Gherkin "Independent depth subscriptions": two topics of one symbol, two windows of the one
    tier, each snapshot and each `d` at exactly its own depth of levels per side."""
    w = World()
    eng = await live(w)
    s50, s200 = w.attach(sub(50)), w.attach(sub(200))
    b50, b200 = s50.built, s200.built
    assert len(b50["structured"]["bids"]) == len(b50["structured"]["asks"]) == 50
    assert len(b200["structured"]["bids"]) == len(b200["structured"]["asks"]) == 60
    assert (b50["structured"]["depth"], b200["structured"]["depth"]) == (50, 200)
    await w.feed(eng, delta(11, 10, [lvl(1000, 7)]))
    w.clock.now += 1
    assert w.topic.tick() == 2
    assert sorted(f[0] for f in w.hub.frames) == ["book.BTCUSDT.200", "book.BTCUSDT.50"]
    assert s50.held == top(eng, 50) and s200.held == top(eng, 200)


async def test_level_leaving_the_window_is_sent_once_with_size_zero() -> None:
    """Gherkin "Level leaving the window": a better bid pushes the 50th out of a depth-50 window;
    it goes out once with size "0" and never again, and the client keeps exactly 50 levels."""
    w = World()
    eng = await live(w)
    s50 = w.attach(sub(50))
    worst = Decimal(1000 - 49) / 10
    await w.feed(eng, delta(11, 10, [lvl(1000 + 0, 2)]))  # inside the window: no level leaves
    await w.feed(eng, delta(12, 11, [], [lvl(1001, 0)]))  # the best ask is deleted
    await w.feed(eng, delta(13, 12, [lvl(1000 + 1, 5)]))  # a better bid: the 50th bid leaves
    w.clock.now += 1
    assert w.topic.tick() == 1
    _, sent, _, merged = w.hub.frames[-1]
    assert [worst_p := Decimal(p) for p, q in sent["bids"] if q == "0"] == [worst]
    assert ["100.1", "0"] in sent["asks"] and merged == 3
    assert s50.held == top(eng, 50) and len(s50.held["bids"]) == len(s50.held["asks"]) == 50
    assert worst_p not in s50.held["bids"]
    await w.feed(eng, delta(14, 13, [lvl(1000 - 5, 3)]))
    w.clock.now += 1
    assert w.topic.tick() == 1
    _, again, _, _ = w.hub.frames[-1]
    assert all(Decimal(p) != worst for p, _ in again["bids"]) and again["bids"] == [["99.5", "3"]]
    assert s50.held == top(eng, 50)


async def test_conflation_cadence_one_frame_per_window_with_the_final_state() -> None:
    """Gherkin "Conflation cadence": upstream deltas every 20 ms on a depth-50 topic leave at most
    one `d` per 50 ms, each the merged final state: intermediate sizes are lost, never the final."""
    w = World()
    eng = await live(w)
    s50 = w.attach(sub(50))
    sent_at: list[float] = []
    u = 10
    for i in range(50):  # one second of upstream at 20 ms
        await w.feed(eng, delta(u + 1, u, [lvl(1000 - (i % 7), i + 2)]))
        u += 1
        if w.topic.tick():
            sent_at.append(w.clock.now)
        w.clock.now += 0.02
        if w.topic.tick():
            sent_at.append(w.clock.now)
    w.clock.now += 1
    if w.topic.tick():
        sent_at.append(w.clock.now)
    gaps = [b - a for a, b in itertools.pairwise(sent_at)]
    assert gaps and min(gaps) >= WINDOW_S[50] - 1e-9
    assert len(sent_at) <= 1 + (50 * 0.02) / WINDOW_S[50] + 1
    assert sum(f[3] for f in w.hub.frames) == 50  # every upstream delta merged into some frame
    assert any(f[3] > 1 for f in w.hub.frames)  # merged frames disclose it (§8.6)
    assert s50.held == top(eng, 50)  # the final state, never lost
    assert w.latency and all(d == 50 for _, d, _ in w.latency)


async def test_conflation_cadence_is_per_depth() -> None:
    w = World()
    eng = await live(w)
    w.attach(sub(1))
    w.attach(sub(200))
    await w.feed(eng, delta(11, 10, [lvl(1000, 3)]))
    assert w.topic.tick() == 2  # nothing sent in the last window: both go out at once
    await w.feed(eng, delta(12, 11, [lvl(1000, 4)]))
    w.clock.now += WINDOW_S[1]
    assert w.topic.tick() == 1 and w.hub.frames[-1][0] == "book.BTCUSDT.1"
    assert w.topic.next_due() == pytest.approx(100.0 + WINDOW_S[200])
    w.clock.now = 100.0 + WINDOW_S[200]
    assert w.topic.tick() == 1 and w.hub.frames[-1][0] == "book.BTCUSDT.200"


async def test_crossed_book_is_a_desync_not_a_clamp() -> None:
    """Gherkin "Crossed book is a desync, not a clamp": the engine drops the book, emits one
    `BookDesyncEvent` and resubscribes; the topic sends no `d` from the crossed state, re-snaps
    the symbol's subscriptions (`upstream_desync`) and serves the fresh snapshot once live."""
    w = World()
    eng = await live(w)
    s50 = w.attach(sub(50))
    resubs, frames = w.resubs, len(w.hub.frames)
    await w.feed(eng, delta(11, 10, [lvl(1002, 1)]))  # best bid 100.2 >= best ask 100.1
    desyncs = [o for o in w.out if isinstance(o, BookDesyncEvent)]
    assert [(d.reason, d.prev_update_id, d.got_update_id) for d in desyncs] == [
        ("crossed", 10, None)
    ]
    assert eng.book is None and eng.phase is BookPhase.SNAPSHOT_PENDING and w.resubs == resubs + 1
    w.clock.now += 1
    assert w.topic.tick() == 0 and len(w.hub.frames) == frames  # nothing from the crossed state
    assert w.hub.desyncs == [SYM] and s50.snapshot_pending
    assert w.topic.build(s50) is None  # pending until the book is live again
    bids, asks = ladder(990, 995, 60)
    await w.feed(eng, snap(20, bids, asks))
    w.clock.now += 1
    w.topic.tick()
    assert w.hub.flushes >= 1  # going live flushes the subscriptions awaiting their `snap`
    fresh = w.attach(s50).built
    assert fresh["structured"]["xu"] == 20 and s50.held == top(eng, 50)


async def test_a_tier_swap_or_resync_seen_first_by_a_build_re_snaps_the_holders() -> None:
    w = World()
    eng = await live(w)
    old = w.attach(sub(50))
    swapped = await w.engine()  # a new active engine (a tier swap), live before any status
    bids, asks = ladder(1000, 1001, 60)
    await swapped.on_event(snap(30, bids, asks))
    newer = sub(50)
    assert w.attach(newer).built is not None  # built over windows of the old book
    w.topic.tick()
    assert w.hub.desyncs == [SYM] and old.snapshot_pending  # the holders of the old book re-snap
    assert eng is not swapped


async def test_a_resync_seen_at_a_flush_re_snaps_instead_of_sending() -> None:
    w = World()
    eng = await live(w)
    s50 = w.attach(sub(50))
    eng.resync_count += 1  # a resync the topic has not been told of yet
    await w.feed(eng, delta(11, 10, [lvl(1000, 9)]))
    w.clock.now += 1
    assert w.topic.tick() == 0 and w.hub.desyncs == [SYM] and s50.snapshot_pending


async def test_a_level_finer_than_the_snapshot_scales_re_snaps_the_symbol() -> None:
    w = World()
    eng = await live(w)
    w.attach(sub(50))
    finer = BookLevel(price=Decimal("100.0"), qty=Decimal("1.5"), price_ticks=1000)
    await w.feed(eng, delta(11, 10, [finer]))
    w.clock.now += 1
    assert w.topic.tick() == 0 and w.hub.desyncs == [SYM]


async def test_a_window_without_subscribers_is_dropped_and_publishes_nothing() -> None:
    w = World()
    eng = await live(w)
    s = w.attach(sub(50))
    w.hub.subs.remove(s)
    await w.feed(eng, delta(11, 10, [lvl(1000, 9)]))
    w.clock.now += 1
    assert w.topic.tick() == 0 and w.hub.frames == []
    await w.feed(eng, delta(12, 11, [lvl(1000, 8)]))
    assert w.topic.next_due() is None


async def test_an_unchanged_book_sends_no_frame() -> None:
    w = World()
    eng = await live(w)
    w.attach(sub(50))
    await w.feed(eng, delta(11, 10, [lvl(1000, 1)]))  # the same size again
    w.clock.now += 1
    assert w.topic.tick() == 0 and w.hub.frames == []


async def test_a_snapshot_is_the_held_window_while_another_subscription_holds_it() -> None:
    w = World()
    eng = await live(w)
    first = w.attach(sub(50)).built
    await w.feed(eng, delta(11, 10, [lvl(1000, 9)]))  # not flushed yet
    second = w.topic.build(sub(50))
    assert second["structured"] == first["structured"]  # what the first one holds
    alone = Sub("book.BTCUSDT.50", _T(SYM, 50))
    w.hub.subs.clear()
    w.hub.subs.append(alone)
    assert w.topic.build(alone)["structured"]["xu"] == 11  # nobody holds it: seeded from live
    assert eng.last_u == 11


async def test_build_serves_no_replay_unknown_or_not_live_book() -> None:
    w = World()
    assert w.topic.build(sub(50)) is None and w.topic.generation(sub(50)) == 0  # no engine
    eng = await w.engine()
    assert w.topic.build(sub(50)) is None  # snapshot pending
    bids, asks = ladder(1000, 1001, 5)
    await w.feed(eng, snap(10, bids, asks))
    assert w.topic.build(sub(50, replay="r1")) is None
    assert w.topic.build(Sub("book.x", _T(None, None))) is None
    assert w.topic.continuity(sub(50), None) is False


async def test_generation_moves_with_the_book_and_then_with_the_window() -> None:
    w = World()
    eng = await live(w)
    s = sub(50)
    g0 = w.topic.generation(s)
    await w.feed(eng, delta(11, 10, [lvl(1000, 9)]))
    g1 = w.topic.generation(s)
    assert g1 > g0 and w.topic.generation(s) == g1  # stable while nothing changes
    w.attach(s)
    g2 = w.topic.generation(s)
    await w.feed(eng, delta(12, 11, [lvl(1000, 8)]))
    assert w.topic.generation(s) == g2  # a held window moves only with its frames
    w.clock.now += 1
    w.topic.tick()
    assert w.topic.generation(s) > g2


async def test_a_failing_symbol_is_re_snapped_alone() -> None:
    """Per-symbol isolation: a symbol whose turn raises is re-snapped; another still publishes."""
    w = World()
    eth = await w.engine("ETHUSDT")
    btc = await w.engine(SYM)
    for eng in (eth, btc):
        bids, asks = ladder(1000, 1001, 60)
        await w.feed(eng, snap(10, bids, asks).model_copy(update={"symbol": eng.symbol}))
    w.attach(sub(50, "ETHUSDT"))
    w.attach(sub(50))
    for eng in (eth, btc):
        await w.feed(eng, delta(11, 10, [lvl(1000, 9)]).model_copy(update={"symbol": eng.symbol}))
    real = w.hub.publish

    def flaky(ch: str, body: Any = None, **kw: Any) -> int:
        if ch.startswith("book.ETHUSDT"):
            raise RuntimeError("boom")
        return real(ch, body, **kw)

    w.topic._publish = flaky
    w.clock.now += 1
    assert w.topic.tick() == 1
    assert w.hub.desyncs == ["ETHUSDT"] and w.hub.frames[-1][0] == "book.BTCUSDT.50"


async def test_a_failing_resync_is_logged_not_raised() -> None:
    w = World()
    await live(w)
    w.attach(sub(50))

    def broken(_symbol: str) -> int:
        raise RuntimeError("down")

    w.topic._desync = broken
    w.engines[SYM].resync_count += 1
    w.topic.offer(live_status(SYM))
    w.topic.tick()  # does not raise


def live_status(symbol: str) -> BookStatus:
    return BookStatus(
        event_id=uuid.UUID(int=1), ts_event=0, ts_ingest=0, source="live",
        symbol=symbol, depth=200, state=BookPhase.LIVE, reason="resync", ts_us=0,
        last_good_ts_us=None, resync_count=1,
    )  # fmt: skip


async def test_going_live_without_windows_flushes_pending_subscriptions() -> None:
    w = World()
    eng = await w.engine()
    pending = sub(50)
    w.hub.subs.append(pending)
    bids, asks = ladder(1000, 1001, 5)
    await w.feed(eng, snap(10, bids, asks))  # its LIVE status reaches the topic
    w.topic.tick()
    assert w.hub.flushes == 1
    w.topic.offer(live_status("NOBOOK"))
    w.topic.tick()  # a status of a symbol with no live book: nothing to flush
    assert w.hub.flushes == 1


async def test_stream_invalidated_marks_every_window_dirty_and_loses_no_state() -> None:
    w = World()
    eng = await live(w)
    s50 = w.attach(sub(50))
    await eng.on_event(delta(11, 10, [lvl(1000, 9)]))  # its bus item was lost
    w.topic.offer(StreamInvalidated(topic="live.md.BTCUSDT.book", ts_event=0))
    w.clock.now += 1
    assert w.topic.tick() == 1 and s50.held == top(eng, 50)
    assert w.hub.flushes == 1  # the lost lifecycle edges are re-checked too


async def test_symbols_past_the_bound_stay_pending_and_are_logged_once() -> None:
    w = World()
    w.topic._max = 1
    for symbol in ("AAAUSDT", "BBBUSDT", "CCCUSDT"):
        eng = await w.engine(symbol)
        bids, asks = ladder(1000, 1001, 3)
        await w.feed(eng, snap(10, bids, asks))
    assert w.attach(sub(50, "AAAUSDT")).built is not None
    assert w.attach(sub(50, "BBBUSDT")).built is None
    assert w.attach(sub(50, "CCCUSDT")).built is None
    assert w.topic._full


async def test_active_subscriptions_are_counted_per_depth() -> None:
    w = World()
    await live(w)
    for depth in (1, 50, 50, 200):
        s = sub(depth)
        w.hub.subs.append(s)
        w.topic.generation(s)
    w.topic.tick()
    assert w.active == {1: 1, 50: 2, 200: 1}
    w.hub.subs.clear()
    w.clock.now += 2
    w.topic.tick()
    assert w.active == {1: 0, 50: 0, 200: 0}


async def test_start_and_stop_run_the_loop_on_the_bus() -> None:
    bus = Bus()
    w = World()
    eng = await live(w)
    w.attach(sub(50))
    topic = BookTopic(
        BookSnapshotSource(w.engines.get, lambda _s: STEPS, body), w.hub.subscriptions,
        w.hub.publish, w.hub.upstream_desync, w.hub.flush_pending, lambda r, ps, qs: r,
        bus=bus, env="live",
    )  # fmt: skip
    topic.start()
    topic.start()  # idempotent
    assert topic.build(w.hub.subs[-1]) is not None
    await eng.on_event(delta(11, 10, [lvl(1000, 9)]))
    await bus.publish(Topic(env="live", domain="md", symbol=SYM, detail="book"), w.out[-1])
    for _ in range(50):
        await asyncio.sleep(0.01)
        if w.hub.frames:
            break
    await topic.stop()
    await topic.stop()
    assert w.hub.frames and w.hub.frames[-1][0] == "book.BTCUSDT.50"
    assert topic.pump() == 0


async def test_a_500_subscription_at_tier_200_stays_pending_until_the_swap() -> None:
    """S1/F8: a `book.X.500` sub while the active tier is still 200 is never served a 200-level
    snapshot under the `.500` topic; it takes its snapshot, at 500 levels, after the swap."""
    w = World()
    await live(w)
    deep = w.attach(sub(500))
    assert deep.built is None and deep.snapshot_pending
    swapped = await w.engine(depth=500)  # the 500 tier, swapped in live
    bids, asks = ladder(1000, 1001, 500)
    await swapped.on_event(snap(30, bids, asks, depth=500))
    built = w.attach(deep).built
    assert built is not None and built["structured"]["depth"] == 500
    assert len(built["structured"]["bids"]) == len(built["structured"]["asks"]) == 500


async def test_a_window_version_and_a_live_u_never_name_the_same_generation() -> None:
    """F3: the generation's moving slot is tagged, so a held window whose version equals the live
    `u` the unheld topic last named is still a new state."""
    w = World()
    eng = await live(w)
    s = sub(50)
    before = w.topic.generation(s)
    w.topic._versions = itertools.count(eng.last_u)  # the window's version == the live `u`
    w.attach(s)
    assert w.topic.generation(s) > before


async def test_a_held_window_renders_the_cross_seq_it_was_seeded_with() -> None:
    """F5: `xseq` pairs with the window's `xu`, never with whatever the engine holds later."""
    w = World()
    eng = await live(w)
    first = w.attach(sub(50)).built
    seeded = first["structured"]["xseq"]
    template = eng._template
    assert template is not None
    eng._template = template.model_copy(update={"cross_seq": seeded + 1000})
    second = w.topic.build(sub(50))  # the first one holds the window
    assert second is not None
    assert second["structured"]["xseq"] == seeded and second["trailer"][1] == seeded
