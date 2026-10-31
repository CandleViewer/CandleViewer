"""E24-T03 (#667): the liquidation stream: demand, publication, bounded write-behind, reconnect.

Fake clocks, no network, no sleeps; the burst fixture is the docs-shaped cascade (README).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence

import pytest
from structlog.testing import capture_logs

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.exchange.base.models import LiquidationEvent
from candleviewer.exchange.bybit.liquidations import liquidation_topic, parse_liquidation_frame
from candleviewer.ingestion.liquidation_stream import LiquidationStream
from candleviewer.ingestion.rejection import EventWindow
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.watchdog import feed_health
from tests._corpus import corpus_path

BURST = corpus_path("ws/allLiquidation_BTCUSDT_burst.jsonl").read_text("utf-8").splitlines()
NOW_US = 1_700_000_700_000_000


class Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


class Store:
    """The dedup key of 21 §4.6: a replayed print lands on its own row again."""

    def __init__(self, fail: int = 0) -> None:
        self.rows: dict[tuple[object, ...], LiquidationEvent] = {}
        self.writes = 0
        self.fail = fail

    async def write_liquidations(self, events: Sequence[LiquidationEvent]) -> None:
        if self.fail:
            self.fail -= 1
            raise OSError("ilp down")
        self.writes += 1
        for e in events:
            key = (e.ts_event, e.symbol, e.liquidated_side, e.price, e.qty, e.batch_index)
            self.rows[key] = e


class Observer:
    def __init__(self) -> None:
        self.n_prints = self.reconnects = self.rejects = 0

    def prints(self, events: Sequence[LiquidationEvent], now_us: int) -> None:
        self.n_prints += len(events)

    def reconnect(self) -> None:
        self.reconnects += 1

    def rejected(self) -> None:
        self.rejects += 1


class Rig:
    def __init__(
        self,
        *,
        recorded: frozenset[str] = frozenset(),
        queue_max: int = 64,
        queue_max_prints: int = 100_000,
        event_window: Callable[[str, int], None] | None = None,
        stop_drain_s: float = 5.0,
    ) -> None:
        self.clock = Clock()
        self.bus = Bus()
        self.desired: set[str] = set()
        self.store = Store()
        self.obs = Observer()
        self.sleeps: list[float] = []
        self.sub = self.bus.subscribe("t", "live.md.*.liquidation", QueuePolicy.NEVER_DROP)
        self.stream = LiquidationStream(
            bus=self.bus,
            env="live",
            set_desired=self._set,
            parse_frame=parse_liquidation_frame,
            topic_for=liquidation_topic,
            is_listed=lambda s: s in ("BTCUSDT", "ETHUSDT"),
            recorded=lambda: recorded,
            writer=self.store,
            observer=self.obs,
            clock=self.clock,
            now_us=lambda: NOW_US,
            sleep=self._sleep,
            queue_max=queue_max,
            queue_max_prints=queue_max_prints,
            event_window=event_window,
            stop_drain_s=stop_drain_s,
        )

    def _set(self, desired: set[str]) -> None:
        self.desired = set(desired)

    async def _sleep(self, s: float) -> None:
        self.sleeps.append(s)


async def test_stream_demand_from_consumers_and_recorded_symbols() -> None:
    rig = Rig(recorded=frozenset({"ETHUSDT", "DELISTEDUSDT"}))
    rig.stream.sync()
    assert rig.desired == {"allLiquidation.ETHUSDT"}  # an unlisted recorded symbol never subscribes
    rig.stream.acquire("ws:liquidations:", "BTCUSDT")
    assert rig.desired == {"allLiquidation.ETHUSDT", "allLiquidation.BTCUSDT"}
    with pytest.raises(ValueError):
        rig.stream.acquire("ws:liquidations:", "FAKEUSDT")


async def test_stream_prints_publish_and_reach_the_store_in_one_batch() -> None:
    rig = Rig()
    rig.stream.acquire("c", "BTCUSDT")
    for frame in BURST[:8]:
        await rig.stream.handle_frame(frame)
    assert rig.sub.qsize() == 19 == rig.obs.n_prints  # every print of the 8 pushes, the twins too
    assert await rig.stream.write_once() == 19
    assert rig.store.writes == 1 and len(rig.store.rows) == 19


async def test_stream_ignores_a_symbol_without_demand() -> None:
    rig = Rig()
    await rig.stream.handle_frame(BURST[0])
    assert rig.sub.qsize() == 0 and rig.stream.queued == 0


async def test_stream_refuses_a_malformed_push_whole_and_counts_it() -> None:
    rig = Rig()
    rig.stream.acquire("c", "BTCUSDT")
    bad = json.loads(BURST[1])
    bad["data"][2]["p"] = "-5"
    await rig.stream.handle_frame(json.dumps(bad))
    assert rig.obs.rejects == 1 and rig.sub.qsize() == 0 and rig.stream.queued == 0


async def test_stream_full_queue_backpressures_the_reader_and_drops_nothing() -> None:
    rig = Rig(queue_max=2)
    rig.stream.acquire("c", "BTCUSDT")
    await rig.stream.handle_frame(BURST[0])
    await rig.stream.handle_frame(BURST[1])
    blocked = asyncio.ensure_future(rig.stream.handle_frame(BURST[2]))
    await asyncio.sleep(0)
    assert not blocked.done()  # the reader waits; nothing is shed
    assert await rig.stream.write_once() == 4
    await blocked
    assert await rig.stream.write_once() == 2
    assert len(rig.store.rows) == 6


async def test_stream_failed_write_is_retried_until_the_store_takes_it() -> None:
    rig = Rig()
    rig.store.fail = 2
    rig.stream.acquire("c", "BTCUSDT")
    await rig.stream.handle_frame(BURST[3])
    assert await rig.stream.write_once() == 5
    assert rig.sleeps == [1.0, 1.0] and len(rig.store.rows) == 5


async def test_stream_drop_logs_gap_and_replayed_prints_dedup() -> None:
    rig = Rig()
    rig.stream.acquire("c", "BTCUSDT")
    for frame in BURST[:8]:
        await rig.stream.handle_frame(frame)
    rig.clock.t = 5.0
    drop = feed_health("*", "resubscribing", 0.0, now_us=NOW_US)
    with capture_logs() as logs:
        await rig.stream.process_health(drop)
        await rig.stream.process_health(drop)  # one drop, counted once
        rig.clock.t = 9.0
        await rig.stream.handle_frame(BURST[8])  # push 2 replayed by the exchange
    await rig.stream.write_once()
    assert rig.obs.reconnects == 1
    assert len(rig.store.rows) == 19  # the replay landed on the rows it already had
    events = {e["event"]: e for e in logs}
    assert events["liquidation_socket_dropped"]["since_last_push_s"] == 5.0
    assert events["liquidation_stream_gap"]["gap_s"] == 4.0


async def test_ingestion_service_routes_frames_and_gaps_to_the_stream() -> None:
    rig = Rig()
    rig.stream.acquire("c", "BTCUSDT")
    svc = IngestionService()
    svc.attach_liquidations(rig.stream)
    assert await svc._dispatch(BURST[0])
    assert rig.sub.qsize() == 1
    from candleviewer.ingestion.dispatch import FrameRoute

    await svc._resync_symbol(FrameRoute("allLiquidation.BTCUSDT", "liquidation", "BTCUSDT"), "x")
    await svc.prune_unlisted()
    assert rig.desired == {"allLiquidation.BTCUSDT"}


async def test_stream_start_and_stop_own_their_tasks() -> None:
    rig = Rig()
    await rig.stream.start()
    assert len(rig.stream._tasks) == 3
    await rig.stream.stop()
    assert rig.stream._tasks == []


async def test_stream_health_loop_counts_a_drop_and_release_frees_demand() -> None:
    rig = Rig()
    gate = asyncio.Event()

    async def block(_s: float) -> None:
        await gate.wait()  # the sync loop parks here: no busy turn

    rig.stream._sleep = block
    rig.stream.acquire("c", "BTCUSDT")
    assert rig.stream.is_listed("BTCUSDT")
    await rig.stream.start()
    health = Topic(env="live", domain="health", detail="feed")
    await rig.bus.publish(health, feed_health("*", "degraded", 0.0, now_us=NOW_US))
    for _ in range(50):
        if rig.obs.reconnects:
            break
        await asyncio.sleep(0)
    await rig.stream.stop()
    assert rig.obs.reconnects == 1
    rig.stream.release("c", "BTCUSDT")
    rig.stream.note_gap("dispatch_overflow", "BTCUSDT")


def _window(now_ms: int) -> EventWindow:
    """The trades' `EventWindow` over a fixed clock (no listing time: that side is skipped)."""
    return EventWindow(lambda: now_ms * 1000, lambda _s: None)


async def test_stream_refuses_a_push_stamped_ahead_of_the_local_clock() -> None:
    """A print far in the future would hold its side's live cluster open for good (#667 r1)."""
    push = json.loads(BURST[1])
    rig = Rig(event_window=_window(push["ts"]))
    rig.stream.acquire("c", "BTCUSDT")
    await rig.stream.handle_frame(BURST[1])  # the fixture's own clock: accepted
    assert rig.sub.qsize() == 3 and rig.stream.queued == 1
    push["data"][2]["T"] = push["ts"] + 365 * 86_400_000  # a year ahead; the envelope too
    push["ts"] = push["data"][2]["T"]
    await rig.stream.handle_frame(json.dumps(push))
    assert rig.obs.rejects == 1 and rig.sub.qsize() == 3 and rig.stream.queued == 1


async def test_stream_write_queue_is_bounded_in_prints_too() -> None:
    rig = Rig(queue_max_prints=4)
    rig.stream.acquire("c", "BTCUSDT")
    await rig.stream.handle_frame(BURST[1])  # 3 prints
    blocked = asyncio.ensure_future(rig.stream.handle_frame(BURST[2]))  # 2 more: over 4
    await asyncio.sleep(0)
    assert not blocked.done() and rig.stream.queued == 1
    assert await rig.stream.write_once() == 3
    await blocked
    assert rig.stream.queued == 1 and await rig.stream.write_once() == 2


async def test_stream_stop_stores_what_is_queued_first() -> None:
    rig = Rig()
    rig.stream.acquire("c", "BTCUSDT")
    await rig.stream.start()
    for frame in BURST[:3]:
        await rig.stream.handle_frame(frame)
    await rig.stream.stop()
    assert rig.stream.queued == 0 and len(rig.store.rows) == 6


async def test_stream_stop_drain_is_bounded_when_the_store_hangs() -> None:
    rig = Rig(stop_drain_s=0)

    class Hanging:
        hang = asyncio.Event()

        async def write_liquidations(self, events: Sequence[LiquidationEvent]) -> None:
            await self.hang.wait()  # never set: the hot tier does not answer

    rig.stream._writer = Hanging()
    rig.stream.acquire("c", "BTCUSDT")
    await rig.stream.handle_frame(BURST[0])
    with capture_logs() as logs:
        await rig.stream.stop()
    assert [e["event"] for e in logs] == ["liquidation_write_behind_unflushed"]
