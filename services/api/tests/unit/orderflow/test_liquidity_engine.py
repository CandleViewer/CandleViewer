"""E21-T04 PR 2 (#710): `LiquidityEngine`, the wired tracker. A fake heatmap (`Pins`) hands it
native deadlines with float levels; prints and events cross a real in-process `Bus`. Covers the
end-to-end Gherkin paths on the bus, the resync boundary, the grid's gaps (carry d), the event cap
and its overflow count (carry c), the call-once accessor (carry b), teardown and the metrics.
Synthetic levels; no network, no sleep (only `asyncio.sleep(0)` turns)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

import pytest
from prometheus_client import REGISTRY

from candleviewer.book.models import BookPhase
from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, Topic
from candleviewer.orderflow import liquidity_engine as E
from candleviewer.orderflow.heatmap import NativeLevels, Sampler
from candleviewer.orderflow.liquidity_engine import LiquidityEngine
from candleviewer.orderflow.liquidity_models import (
    LiquidityConfig,
    LiquidityPulled,
    LiquidityReload,
)
from tests.unit.orderflow._liquidity_helpers import STEP, TICK, trade

SYM = "BTCUSDT"
T0 = 1_700_000_000_000


class Levels:
    def __init__(self, bids: Mapping[int, float], asks: Mapping[int, float]) -> None:
        self.bids, self.asks = dict(bids), dict(asks)


def book(wall: float = 10.0, n_asks: int = 0, ask_size: float = 10.0) -> NativeLevels:
    """Best bid 1000, best ask 1001, the wall at ask 1002 (or `n_asks` levels of `ask_size`)."""
    if n_asks:
        return Levels({1000: 50.0}, {1001 + i: ask_size for i in range(n_asks)})
    return Levels({1000: 20.0, 999: 5.0}, {1001: 4.0, 1002: wall, 1003: 20.0})


class Pins:
    def __init__(self) -> None:
        self.sampler: Sampler | None = None
        self.pinned: dict[str, int] = {}
        self.unpinned: list[str] = []

    def set_sampler(self, sampler: Sampler | None) -> None:
        self.sampler = sampler

    def pin_native(self, symbol: str, depth: int) -> None:
        self.pinned[symbol] = depth

    def unpin_native(self, symbol: str) -> None:
        self.pinned.pop(symbol, None)
        self.unpinned.append(symbol)


class Rig:
    def __init__(self, symbols: tuple[str, ...] = (SYM,), **cfg: Any) -> None:
        self.bus, self.pins = Bus(), Pins()
        self.steps: dict[str, tuple[Decimal, Decimal]] = {SYM: (TICK, STEP)}
        self.engine = LiquidityEngine(
            self.bus, "live", pins=self.pins, steps=self.steps.get, symbols=symbols,
            config=LiquidityConfig(**cfg),
        )  # fmt: skip
        self.out = self.bus.subscribe(
            "test-liquidity", f"live.md.{SYM}.liquidity", QueuePolicy.NEVER_DROP, maxsize=4096
        )

    def at(self, ms: int, levels: NativeLevels | None) -> None:
        assert self.pins.sampler is not None
        self.pins.sampler(SYM, T0 + ms, levels)

    async def trade(self, ms: int, tick: int, qty: str, side: str = "buy") -> None:
        ev = trade(ms, tick, qty, side).model_copy(update={"ts_event": (T0 + ms) * 1000})
        await self.bus.publish(Topic(env="live", domain="md", symbol=SYM, detail="trade"), ev)

    async def events(self) -> list[Any]:
        for _ in range(5):
            await asyncio.sleep(0)
        got = []
        while self.out.qsize():
            got.append(self.out.get_nowait())
        return got


def _count(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _shed() -> float:
    return _count("liquidity_events_overflow_total", symbol=SYM, reason="publish_queue")


async def test_reload_reaches_the_bus_once_from_a_column_and_prints() -> None:
    """Gherkin "Reload flagged as estimated", wired: deadlines plus prints give exactly one
    `LiquidityReload` on `{env}.md.{symbol}.liquidity`."""
    rig = Rig()
    rig.engine.start()
    before = _count("liquidity_reload_events_total", symbol=SYM)
    rig.at(0, book(10.0))
    await rig.trade(40, 1002, "6")
    rig.at(100, book(3.0))
    rig.at(200, book(9.0))
    (ev,) = await rig.events()
    assert isinstance(ev, LiquidityReload) and ev.estimated is True
    assert (ev.prior_size, ev.replenished_size, ev.refill_count) == (
        Decimal("10.000"), Decimal("9.000"), 1,
    )  # fmt: skip
    assert ev.ts_event == (T0 + 200) * 1000  # on the 100 ms grid
    assert _count("liquidity_reload_events_total", symbol=SYM) - before == 1
    await rig.engine.stop()


async def test_pulled_reaches_the_bus_once_without_prints() -> None:
    """Gherkin "Pulled is not reload", wired."""
    rig = Rig()
    rig.engine.start()
    before = _count("liquidity_pulled_events_total", symbol=SYM)
    for k, wall in enumerate((10.0, 3.0, 3.0, 9.0)):
        rig.at(k * 100, book(wall))
    (ev,) = await rig.events()
    assert isinstance(ev, LiquidityPulled) and ev.traded_qty == 0
    assert _count("liquidity_pulled_events_total", symbol=SYM) - before == 1
    await rig.engine.stop()


async def test_float_sizes_are_quantised_to_the_qty_step() -> None:
    rig = Rig()
    rig.engine.start()
    rig.at(0, Levels({1000: 0.1 + 0.2, 999: 0.0004}, {1001: 1.0}))
    tracker = rig.engine.tracker(SYM)
    assert tracker is not None
    (band, *_) = tracker.on_sample(T0 * 1000 + 1, BookPhase.LIVE, E._Quantised(
        Levels({1000: 0.1 + 0.2, 999: 0.0004}, {1001: 1.0}), STEP)).bands  # fmt: skip
    assert (band.bid, band.ask) == (Decimal("0.300"), Decimal("1.000"))  # exact, not 0.3000...04
    view = E._Quantised(Levels({1000: 0.1 + 0.2, 999: 0.0004}, {}), STEP)
    assert list(view.walk(bids=True)) == [(1000, Decimal("0.300"))]  # 0.0004 rounds to 0: gone
    assert list(view.walk(bids=False)) == []
    await rig.engine.stop()


async def test_no_event_from_a_resync_and_the_first_live_sample_rebaselines() -> None:
    """Gherkin "Estimated data is excluded during resync", wired: a deadline without levels is
    a gap, and the drop across it is never an event."""
    rig = Rig()
    rig.engine.start()
    rig.at(0, book(10.0))
    await rig.trade(40, 1002, "6")
    rig.at(100, None)  # resyncing: the heatmap hands no levels
    rig.at(200, book(3.0))  # first live sample: re-baselined at 3
    rig.at(300, book(9.0))
    rig.at(400, book(9.0))
    assert await rig.events() == []
    await rig.engine.stop()


async def test_a_skipped_deadline_is_a_gap() -> None:
    """Carry (d): a jump of more than one column (a stall the heatmap skipped) records a gap,
    so the drop across it is not compared."""
    rig = Rig()
    rig.engine.start()
    rig.at(0, book(10.0))
    rig.at(500, book(3.0))  # 100..400 never came
    rig.at(600, book(3.0))
    tracker = rig.engine.tracker(SYM)
    assert tracker is not None
    assert bool(tracker.series(1002).estimated[-3]) is True  # the gap column before 500
    assert await rig.events() == []
    await rig.engine.stop()


async def test_a_tape_overflow_makes_the_next_sample_a_gap() -> None:
    rig = Rig()
    rig.engine.start()
    rig.at(0, book(10.0))
    rig.engine._offer(StreamInvalidated(topic=f"live.md.{SYM}.trade", ts_event=1))
    rig.at(100, book(3.0))  # would be a pull; the tape is incomplete, so a gap
    rig.at(200, book(3.0))
    rig.at(300, book(3.0))
    assert await rig.events() == []
    await rig.engine.stop()


async def test_event_cap_publishes_the_cap_and_counts_the_overflow() -> None:
    """Carry (c): a sample past `max_events` publishes the cap; the rest are counted."""
    rig = Rig(max_events=2)
    rig.engine.start()
    before = _count("liquidity_events_overflow_total", symbol=SYM, reason="sample_cap")
    rig.at(0, book(n_asks=10, ask_size=10.0))
    rig.at(100, book(n_asks=10, ask_size=1.0))
    rig.at(200, book(n_asks=10, ask_size=1.0))
    got = await rig.events()
    assert [e.price_ticks for e in got] == [1001, 1002]
    assert _count("liquidity_events_overflow_total", symbol=SYM, reason="sample_cap") - before == 8
    await rig.engine.stop()


async def test_full_outbound_queue_sheds_the_oldest_and_counts_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(E, "OUT_MAX", 3)
    rig = Rig()
    before = _shed()
    rig.engine._pins.set_sampler(rig.engine.on_deadline)  # sampled, but no publisher running
    rig.at(0, book(n_asks=5, ask_size=10.0))
    rig.at(100, book(n_asks=5, ask_size=1.0))
    rig.at(200, book(n_asks=5, ask_size=1.0))
    assert rig.engine.queued == 3
    assert _shed() - before == 2


async def test_a_failed_publish_is_counted_and_the_next_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    calls = 0
    real = rig.bus.publish

    async def flaky(topic: Topic, event: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("bus down")
        await real(topic, event)

    monkeypatch.setattr(rig.bus, "publish", flaky)
    rig.engine.start()
    before = _shed()
    rig.at(0, book(n_asks=2, ask_size=10.0))
    rig.at(100, book(n_asks=2, ask_size=1.0))
    rig.at(200, book(n_asks=2, ask_size=1.0))
    assert len(await rig.events()) == 1
    assert _shed() - before == 1
    await rig.engine.stop()


async def test_distance_accessor_reads_the_per_sample_cache() -> None:
    """Carry (b): the engine's accessor computes once per sample."""
    rig = Rig()
    rig.engine.start()
    assert rig.engine.distance_to_liquidity_cluster("ETHUSDT") is None  # no tracker
    for k in range(5):
        rig.at(k * 100, book(10.0))
    tracker = rig.engine.tracker(SYM)
    assert tracker is not None
    a = rig.engine.distance_to_liquidity_cluster(SYM)
    b = rig.engine.distance_to_liquidity_cluster(SYM)
    assert a == b and tracker.distance_computes == 1
    await rig.engine.stop()


async def test_teardown_releases_pins_sampler_task_and_subscription() -> None:
    rig = Rig()
    subs = len(rig.bus._subscriptions)
    rig.engine.start()
    assert rig.pins.pinned == {SYM: E.PIN_DEPTH} and rig.pins.sampler is not None
    assert len(rig.bus._subscriptions) == subs + 1
    task = rig.engine._task
    assert task is not None
    rig.at(0, book(10.0))
    await asyncio.sleep(0)
    await rig.engine.stop()
    assert task.done() and rig.engine._task is None
    assert rig.pins.pinned == {} and rig.pins.unpinned == [SYM] and rig.pins.sampler is None
    assert len(rig.bus._subscriptions) == subs
    assert rig.engine.tracker(SYM) is None and rig.engine.queued == 0
    rig.engine.start()  # restartable
    assert rig.engine._task is not None
    await rig.engine.stop()


async def test_no_symbols_is_a_no_op_and_unknown_steps_build_no_tracker() -> None:
    rig = Rig(symbols=())
    rig.engine.start()
    assert rig.engine._task is None and rig.pins.sampler is None
    await rig.engine.stop()
    rig = Rig()
    rig.steps.clear()
    rig.engine.start()
    rig.at(0, book(10.0))  # the instrument is not known yet
    assert rig.engine.tracker(SYM) is None
    assert rig.pins.sampler is not None
    rig.pins.sampler("ETHUSDT", T0, book(10.0))  # not pinned: ignored
    assert rig.engine.tracker("ETHUSDT") is None
    await rig.engine.stop()


async def test_prints_of_other_symbols_and_before_the_tracker_are_ignored() -> None:
    rig = Rig()
    rig.engine.start()
    rig.engine._offer(trade(0, 1002, "6").model_copy(update={"symbol": "ETHUSDT"}))
    rig.engine._offer(object())
    rig.at(0, book(10.0))
    assert await rig.events() == []
    await rig.engine.stop()


async def test_memory_gauge_is_set_per_tracker() -> None:
    rig = Rig()
    rig.engine.start()
    rig.at(0, book(10.0))
    tracker = rig.engine.tracker(SYM)
    assert tracker is not None
    assert _count("liquidity_tracker_memory_bytes", symbol=SYM) == tracker.memory_bytes
    assert 0 < tracker.memory_bytes <= 256 * 6_000 * 8 + 6_000 * 9 + 256 * 8
    await rig.engine.stop()


async def test_a_bad_print_is_logged_and_the_reader_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    rig.engine.start()
    rig.at(0, book(10.0))
    tracker = rig.engine.tracker(SYM)
    assert tracker is not None

    def boom(ev: object) -> None:
        raise ValueError("bad print")

    monkeypatch.setattr(tracker, "on_trade", boom)
    await rig.trade(10, 1002, "1")
    await asyncio.sleep(0)
    task = rig.engine._task
    assert task is not None and not task.done()
    await rig.engine.stop()


def test_a_task_that_died_is_logged() -> None:
    class Dead:
        def cancelled(self) -> bool:
            return False

        def exception(self) -> BaseException:
            return RuntimeError("died")

    E._stopped(cast(Any, Dead()))  # logs, never raises


def test_quantised_sizes_are_cached_within_a_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(E, "DECIMALS_MAX", 2)
    cache: dict[int, Decimal] = {}
    view = E._Quantised(Levels({1000: 1.0, 999: 2.0, 998: 3.0, 997: 1.0}, {}), STEP, cache)
    sizes = [q for _, q in view.walk(bids=True)]
    assert sizes == [Decimal("1.000"), Decimal("2.000"), Decimal("3.000"), Decimal("1.000")]
    assert len(cache) <= 2
