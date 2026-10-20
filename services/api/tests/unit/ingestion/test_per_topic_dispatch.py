"""#1916 / #1905 regressions: per-topic dispatch lanes behind the WS frame pump.

Unit-level twins of chaos scenarios 10 (`test_s10_bus_backpressure`) and 4
(`test_s04_trade_stream_gap`) from PR #1921. Fake clock, fake streams, real
`Bus` and `TradeStream`; no network, no sleeps (only `asyncio.sleep(0)` yields).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.public_ws import frame_route
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion import dispatch
from candleviewer.ingestion.metrics import ingest_dispatch_overflow_total
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.ingestion.watchdog import feed_health


def book(sym: str, n: int) -> str:
    return json.dumps({"topic": f"orderbook.200.{sym}", "u": n})


def trade(sym: str, n: int) -> str:
    return json.dumps(
        {
            "topic": f"publicTrade.{sym}",
            "data": [
                {
                    "T": 1_700_000_000_000 + n,
                    "s": sym,
                    "S": "Buy",
                    "v": "0.01",
                    "p": "100.0",
                    "i": f"{sym}-{n}",
                    "BT": False,
                }
            ],
        }
    )


class FakeStreams:
    """Book/trade double: book frames publish to a bus topic (a NEVER_DROP
    subscriber may never drain it); every handled frame is recorded."""

    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.seen: list[str] = []
        self.marked: list[tuple[str, str | None]] = []
        self.invalidated: list[tuple[str, str | None]] = []
        self.prefix = "orderbook"

    def for_trades(self) -> FakeStreams:
        twin = FakeStreams.__new__(FakeStreams)
        twin.__dict__.update(self.__dict__)
        twin.prefix = "publicTrade"
        return twin

    async def handle_frame(self, frame: str) -> None:
        msg = json.loads(frame)
        topic = msg["topic"]
        if not topic.startswith(self.prefix):
            return  # each real stream ignores topics it does not own
        self.seen.append(frame)
        sym = topic.rsplit(".", 1)[-1]
        detail = "book" if topic.startswith("orderbook") else "trade"
        await self.bus.publish(Topic(env="live", domain="md", symbol=sym, detail=detail), msg)

    def mark_gap(self, reason: str, symbol: str | None = None) -> None:
        self.marked.append((reason, symbol))

    async def invalidate(self, reason: str) -> None:
        self.invalidated.append((reason, None))

    async def invalidate_symbol(self, symbol: str, reason: str) -> None:
        self.invalidated.append((reason, symbol))

    async def stop(self) -> None:
        return None


def rig() -> tuple[IngestionService, FakeStreams, Bus, list[str]]:
    bus = Bus()
    svc, fake = IngestionService(), FakeStreams(bus)
    touched: list[str] = []
    svc.trades = fake.for_trades()  # type: ignore[assignment]  # duck-typed stream double
    svc.books = fake  # type: ignore[assignment]  # duck-typed stream double
    svc.attach_router(frame_route, touched.append)
    return svc, fake, bus, touched


async def settle(n: int = 50) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def overflow(stream: str) -> float:
    return float(ingest_dispatch_overflow_total.labels(stream=stream)._value.get())


async def test_slow_never_drop_book_consumer_does_not_starve_other_symbols() -> None:
    svc, _fake, bus, touched = rig()
    bus.subscribe("stuck", "live.md.BTCUSDT.book", QueuePolicy.NEVER_DROP, maxsize=4)
    eth = bus.subscribe("eth", "live.md.ETHUSDT.trade", QueuePolicy.NEVER_DROP, maxsize=10_000)
    pump = asyncio.create_task(svc._pump_frames())
    try:
        for i in range(200):
            svc.offer_frame(book("BTCUSDT", i))
            svc.offer_frame(trade("ETHUSDT", i))
            await settle(2)
        await settle()
        assert eth.queue.qsize() == 200  # every ETH print published, full rate
        assert svc.ws_frames.qsize() == 0  # the raw queue never backs up
        assert touched.count("orderbook.200.BTCUSDT") == 200  # freshness = venue
        assert touched.count("publicTrade.ETHUSDT") == 200
        assert not pump.done()
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)


async def test_lane_overflow_resyncs_only_that_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "LANE_MAXSIZE", 8)
    svc, fake, bus, _ = rig()
    stuck = bus.subscribe("stuck", "live.md.BTCUSDT.book", QueuePolicy.NEVER_DROP, maxsize=1)
    before = overflow("book")
    pump = asyncio.create_task(svc._pump_frames())
    try:
        eth_before = overflow("trade")
        for i in range(40):
            svc.offer_frame(book("BTCUSDT", i))
            svc.offer_frame(trade("ETHUSDT", i))
            await settle(2)
        await settle()
        assert overflow("book") > before and overflow("trade") == eth_before
        assert fake.invalidated == []  # resync is applied in order, ahead of later frames
        while not stuck.queue.empty():  # consumer recovers
            stuck.queue.get_nowait()
            await settle(5)
        await settle()
        assert ("dispatch_overflow", "BTCUSDT") in fake.invalidated
        assert all(sym == "BTCUSDT" for _, sym in fake.invalidated)
        assert sum("publicTrade.ETHUSDT" in f for f in fake.seen) == 40
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)


async def test_stop_cancels_every_lane_without_leaking_tasks() -> None:
    svc, _fake, bus, _ = rig()
    bus.subscribe("stuck", "live.md.BTCUSDT.book", QueuePolicy.NEVER_DROP, maxsize=1)
    baseline = set(asyncio.all_tasks())
    svc._pump = asyncio.create_task(svc._pump_frames())
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        for i in range(5):
            svc.offer_frame(book(sym, i))
            svc.offer_frame(trade(sym, i))
    await settle()
    assert svc.lanes is not None and len(svc.lanes.lanes) == 6
    await svc.stop(1.0)
    await settle()
    assert set(asyncio.all_tasks()) - baseline == set()


@settings(max_examples=30, deadline=None)
@given(order=st.lists(st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"]), max_size=60))
def test_property_per_symbol_order_preserved(order: list[str]) -> None:
    async def run() -> list[str]:
        svc, fake, _bus, _ = rig()
        pump = asyncio.create_task(svc._pump_frames())
        try:
            for n, sym in enumerate(order):
                svc.offer_frame(book(sym, n))
            await settle(4 * len(order) + 20)
        finally:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        return fake.seen

    seen = asyncio.run(run())
    assert len(seen) == len(order)
    for sym in set(order):
        mine = [json.loads(f)["u"] for f in seen if sym in f]
        assert mine == sorted(mine)


def test_frame_route_parses_venue_topics_and_ignores_control_frames() -> None:
    assert frame_route(book("BTCUSDT", 1)) == ("orderbook.200.BTCUSDT", "book", "BTCUSDT")
    assert frame_route(trade("ETHUSDT", 1)) == ("publicTrade.ETHUSDT", "trade", "ETHUSDT")
    assert frame_route('{"op":"pong","success":true}') is None
    assert frame_route('{"topic":"kline.1.BTCUSDT"}') is None


def test_lane_count_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "MAX_LANES", 2)

    async def run() -> int:
        svc, _fake, _bus, _ = rig()
        pump = asyncio.create_task(svc._pump_frames())
        for sym in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"):
            svc.offer_frame(book(sym, 1))
        await settle()
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        assert svc.lanes is not None
        return len(svc.lanes.lanes)

    assert asyncio.run(run()) == 3  # two topic lanes + the shared fallback


# ---- #1905: trade gap backfill off the dispatch path --------------------------


async def test_stalled_backfill_never_blocks_frames_for_any_symbol() -> None:
    bus, release = Bus(), asyncio.Event()
    calls: list[str] = []

    async def fetch(sym: str) -> Sequence[TradePrint]:
        calls.append(sym)
        await release.wait()  # REST never returns until released
        return []

    out = bus.subscribe("t", "live.md.*.trade", QueuePolicy.NEVER_DROP, maxsize=10_000)
    stream = TradeStream(
        bus=bus,
        env="live",
        set_desired=lambda _t: None,
        parse_frame=parse_trade_frame,
        topic_for=trade_topic,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
        fetch_recent=fetch,
        tick_size=lambda _s: Decimal("0.1"),
        clock=lambda: 0.0,
        backfill_timeout_s=3600.0,
    )
    for sym in ("BTCUSDT", "ETHUSDT"):
        stream.acquire("tape", sym)
    svc = IngestionService()
    svc.trades = stream
    svc.attach_router(frame_route, lambda _t: None)
    pump = asyncio.create_task(svc._pump_frames())
    try:
        svc.offer_frame(trade("BTCUSDT", 0))
        await settle()
        await stream.process_health(
            feed_health("publicTrade.BTCUSDT", "resubscribing", 0, now_us=0)
        )
        for i in range(1, 51):
            svc.offer_frame(trade("BTCUSDT", i))
            svc.offer_frame(trade("ETHUSDT", i))
        await settle(200)
        got: list[Any] = []
        while not out.queue.empty():
            got.append(out.queue.get_nowait())
        assert calls == ["BTCUSDT"]  # single-flight
        assert sum(e.symbol == "ETHUSDT" for e in got) == 50  # ETH never waited
        assert sum(e.symbol == "BTCUSDT" for e in got) == 1  # BTC held behind its backfill
        assert svc.ws_frames.qsize() == 0
        release.set()
        await stream.wait_backfills()
        btc = []
        while not out.queue.empty():
            btc.append(out.queue.get_nowait())
        ts = [e.ts_event for e in btc]
        assert len(btc) == 50 and ts == sorted(ts)  # held prints published, in order
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await stream.stop()


async def test_cancelled_backfill_reopens_the_gap() -> None:
    bus = Bus()

    async def fetch(_s: str) -> Sequence[TradePrint]:
        await asyncio.Event().wait()
        return []

    stream = TradeStream(
        bus=bus,
        env="live",
        set_desired=lambda _t: None,
        parse_frame=parse_trade_frame,
        topic_for=trade_topic,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
        fetch_recent=fetch,
        clock=lambda: 0.0,
    )
    stream.acquire("tape", "BTCUSDT")
    await stream.handle_frame(trade("BTCUSDT", 0))
    stream.mark_gap("reconnect", "BTCUSDT")
    await stream.handle_frame(trade("BTCUSDT", 1))
    await settle()
    await stream.stop()  # cancels the in-flight backfill
    assert stream.open_gaps()["BTCUSDT"][1] == "backfill_failed"


async def test_lane_breaker_resyncs_only_that_lanes_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candleviewer.ingestion import service as service_mod

    monkeypatch.setattr(service_mod, "PUMP_BREAKER_TRIPS", 3)
    svc, fake, _bus, _ = rig()
    inner = fake.handle_frame

    async def poisoned(frame: str) -> None:
        if "orderbook.200.BTCUSDT" in frame:
            raise KeyError("poison")
        await inner(frame)

    fake.handle_frame = poisoned  # type: ignore[method-assign]
    pump = asyncio.create_task(svc._pump_frames())
    try:
        for i in range(6):
            svc.offer_frame(book("BTCUSDT", i))
            svc.offer_frame(book("ETHUSDT", i))
            svc.offer_frame(trade("ETHUSDT", i))
            await settle(4)
        await settle()
        assert svc.pump_breaker_trips == 2
        assert fake.invalidated == [("pump_breaker", "BTCUSDT")] * 2  # never every symbol
        assert fake.marked == []  # ETH tape untouched
        assert sum("ETHUSDT" in f for f in fake.seen) == 12
        assert not pump.done()
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
