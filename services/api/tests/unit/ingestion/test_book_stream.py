"""E08-S05: fixture-corpus invariants + BookStream wiring (no network, recorded-shape fixtures)."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import corpus_path

FIX = corpus_path("ws/orderbook_BTCUSDT.jsonl")
FRAMES = FIX.read_text(encoding="utf-8").splitlines()
TICK = Decimal("0.1")


def _tick(_s: str) -> Decimal:
    return TICK


def test_parser_maps_snapshot_delta_and_ignores_other_topics() -> None:
    first = parse_book_frame(FRAMES[0], _tick)
    assert isinstance(first, BookSnapshot) and first.depth == 200 and first.update_id == 1
    second = parse_book_frame(FRAMES[1], _tick)
    assert isinstance(second, BookDelta) and second.prev_update_id == second.update_id - 1
    assert parse_book_frame('{"topic":"tickers.BTCUSDT"}', _tick) is None
    assert parse_book_frame("not json", _tick) is None


@pytest.mark.parametrize(
    "frame",
    [
        '{"topic":"orderbook.7.BTCUSDT","ts":1,"data":{}}',
        '{"topic":"orderbook.200.BTCUSDT","type":"delta","ts":1,"data":{"s":"BTCUSDT","u":2,'
        '"b":[["1","-1"]],"a":[]}}',
        '{"topic":"orderbook.200.BTCUSDT","type":"delta","ts":1,"data":{"s":"BTCUSDT","u":2,'
        '"b":[["NaN","1"]],"a":[]}}',
        '{"topic":"orderbook.200.BTCUSDT","type":"delta","ts":1,"data":{"s":"ETHUSDT","u":2}}',
    ],
)
def test_parser_rejects_hostile_frames(frame: str) -> None:
    with pytest.raises(ValueError):
        parse_book_frame(frame, _tick)


async def test_corpus_replay_keeps_book_invariants_and_resyncs_on_hole() -> None:
    """Never crossed, ordered, no zero/negative published size, seq strictly increasing
    while LIVE; the deliberate hole is invalidated, never patched."""
    published: list[object] = []
    resubs = 0

    async def pub(ev: object) -> None:
        published.append(ev)

    async def resub() -> None:
        nonlocal resubs
        resubs += 1

    eng = BookEngine(symbol="BTCUSDT", depth=200, publish=pub, resubscribe=resub, now_us=lambda: 0)
    await eng.start()
    live_checks = 0
    for raw in FRAMES:
        ev = parse_book_frame(raw, _tick)
        assert ev is not None
        await eng.on_event(ev)
        if eng.phase is BookPhase.DESYNCED:  # test harness plays the exchange: re-snapshot
            eng.phase = BookPhase.SNAPSHOT_PENDING
        if eng.phase is BookPhase.LIVE and eng.book is not None:
            bids, asks = eng.book.snapshot()
            assert not bids or not asks or bids[0].price_ticks < asks[0].price_ticks
            live_checks += 1
    assert live_checks > 1000
    for obj in published:
        if isinstance(obj, (BookSnapshot, BookDelta)):
            for lv in (*obj.bids, *obj.asks):
                assert lv.qty >= 0 and lv.price > 0
            if isinstance(obj, BookSnapshot):
                assert all(lv.qty > 0 for lv in (*obj.bids, *obj.asks))
                assert [b.price_ticks for b in obj.bids] == sorted(
                    (b.price_ticks for b in obj.bids), reverse=True
                )
                assert [a.price_ticks for a in obj.asks] == sorted(a.price_ticks for a in obj.asks)
    deltas = [o.update_id for o in published if isinstance(o, BookDelta)]
    assert resubs >= 1 and deltas  # the hole forced at least one resync
    assert any(isinstance(o, BookStatus) and o.state is BookPhase.DESYNCED for o in published)


class FakeSupervisor:
    """Stands in for `B14BookSupervisor`: records attach/detach and edges."""

    def __init__(self) -> None:
        self.edges: list[tuple[str, str]] = []
        self.detached: list[str] = []

    async def attach(self, key: str, symbol: str) -> Any:
        async def sink(event: str) -> None:
            self.edges.append((key, event))

        return sink

    def detach(self, key: str) -> None:
        self.detached.append(key)


class Harness:
    def __init__(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.bus = Bus()
        self.sub = self.bus.subscribe(
            "b", "live.md.*.book", QueuePolicy.NEVER_DROP, maxsize=100_000
        )
        self.sup = FakeSupervisor()
        self.desired: set[str] = set()
        self.resubs: list[str] = []
        self.writes: list[Any] = []
        outer = self

        class W:
            async def write_book_deltas(self, rows: Any) -> None:
                outer.writes.extend(rows)

            async def write_book_snapshot(self, row: Any) -> None:
                outer.writes.append(row)

        async def resub(topic: str) -> None:
            self.resubs.append(topic)

        self.stream = BookStream(
            bus=self.bus,
            env="live",
            set_desired=lambda t: setattr(self, "desired", set(t)),
            parse_frame=lambda f: parse_book_frame(f, _tick),
            topic_for=book_topic,
            resubscribe=resub,
            is_listed=lambda s: s == "BTCUSDT",
            touch=lambda _t: None,
            writer=W(),
            now_us=lambda: 0,
            supervisor=self.sup,
            sleep=sleep,
        )

    def drain(self) -> list[Any]:
        out = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out


async def test_stream_serves_consumers_only_after_live_and_writes_behind() -> None:
    h = Harness()
    h.stream.acquire("c", "BTCUSDT")
    assert h.desired == {"orderbook.200.BTCUSDT"}
    # a delta before any snapshot is never published
    await h.stream.handle_frame(FRAMES[1])
    assert [o for o in h.drain() if isinstance(o, BookDelta)] == []
    assert h.stream.view("BTCUSDT", 50) is None  # not LIVE: no book served
    await h.stream.handle_frame(FRAMES[0])
    first = h.drain()
    assert isinstance(first[0], BookSnapshot) and first[0].reason == "subscribe"
    assert h.stream.phase("BTCUSDT") is BookPhase.LIVE
    for f in FRAMES[2:20]:
        await h.stream.handle_frame(f)
    assert all(isinstance(o, BookDelta) for o in h.drain() if not isinstance(o, BookStatus))
    view = h.stream.view("BTCUSDT", 50)
    assert view is not None and view.snapshot.depth == 50 and len(view.snapshot.bids) <= 50
    await h.stream.drain_writes()
    assert h.writes


async def test_stream_gap_goes_through_budgeted_resubscribe_and_timeout() -> None:
    h = Harness()
    h.stream.acquire("c", "BTCUSDT")
    for f in FRAMES[:5]:
        await h.stream.handle_frame(f)
    await h.stream.handle_frame(FRAMES[2700])  # far-ahead delta: sequence gap
    assert h.stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING
    assert h.resubs == ["orderbook.200.BTCUSDT"]
    assert h.stream.view("BTCUSDT", 50) is None  # resyncing: no patched book
    # snapshot never arrives -> SNAPSHOT_TIMEOUT re-requests
    eng = h.stream._books["BTCUSDT"].active
    eng._pending_since = -10_000_000
    h.stream._timeout_us = 1
    h.stream._clock = lambda: time.monotonic() + 1_000.0  # past the resync cooldown (fake clock)
    assert await h.stream.check_timeouts() == 1
    assert len(h.resubs) == 2
    await h.stream.stop()


async def test_stream_forwards_lifecycle_edges_to_injected_supervisor() -> None:
    h = Harness()
    h.stream.acquire("c", "BTCUSDT")
    for f in FRAMES[:20]:
        await h.stream.handle_frame(f)
    events = [e for _, e in h.sup.edges]
    assert events == ["SUBSCRIBE", "SNAPSHOT"]  # never one per delta (INV-B14-a)
    await h.stream.handle_frame(FRAMES[2700])
    assert [e for _, e in h.sup.edges][-1] == "SEQUENCE_GAP"
    await h.stream.stop()
    assert h.sup.detached == ["live:BTCUSDT:200"]


#: The SNAPSHOT_TIMEOUT check cadence (`orderbook_wiring._TICK_S`).
SNAPSHOT_TICK_S = 0.25


def test_stream_timeout_tick_defaults_to_the_loop_clock() -> None:
    """#1975: the seam's default keeps today's `asyncio.sleep` tick."""
    assert inspect.signature(BookStream).parameters["sleep"].default is asyncio.sleep


async def test_stream_timeout_tick_runs_on_the_injected_sleep() -> None:
    """#1975: the SNAPSHOT_TIMEOUT tick sleeps on the injected `sleep` (the chaos rig's
    virtual clock), and a tick re-requests a snapshot pending past the timeout."""
    delays: list[float] = []
    parked = asyncio.Event()

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) > 1:  # one tick done: park until stop()
            parked.set()
            await asyncio.Event().wait()

    h = Harness(sleep=sleep)
    h.stream.acquire("c", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[1])  # a delta and no snapshot: pending
    h.stream._books["BTCUSDT"].active._pending_since = -10_000_000  # past the 10 s timeout
    await h.stream.start()
    async with asyncio.timeout(5):  # hang guard only
        await parked.wait()
    assert delays == [SNAPSHOT_TICK_S, SNAPSHOT_TICK_S]
    assert h.resubs == ["orderbook.200.BTCUSDT"]  # the tick re-requested the snapshot
    assert h.sup.edges[-1] == ("live:BTCUSDT:200", "SNAPSHOT_TIMEOUT")
    await h.stream.stop()
