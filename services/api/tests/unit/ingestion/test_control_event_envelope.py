"""C6 envelope on E08's control events (#3876; drift D1, decision (a) on #2701).

`BookStatus`, `GapEvent` and `FeedHealthEvent` carry the 24 §1.4 envelope with `schema_version = 1`
(24 §2.9: adding it is additive, so 24 §17.1 asks no bump). Each is checked where production builds
it, on recorded fixtures and injected clocks: `source = "live"`, a UUID7 `event_id` stamped with the
millisecond of `ts_event`, and the timestamps 24 §2.9 gives the event.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.book.tiers import DEFAULT_DEPTH
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, TopicPattern
from candleviewer.domain.events import DomainEvent
from candleviewer.exchange.base.models import BookSnapshot
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion.connection import ConnectionManager, Sleep, Socket
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import GapEvent, TradeStream
from candleviewer.ingestion.watchdog import FeedHealthEvent, StalenessWatchdog
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import TICKS, frames

#: The producers' injected wall clock (µs), inside the recorded trade capture's window.
NOW_US = 1_792_391_740_000_123
TRADES = frames("ws/recorded_publicTrade_BTCUSDT.jsonl")
HEALTH = TopicPattern(env="live", domain="health", detail="feed")


async def _noop(*_topic: str) -> None:
    return None


def _assert_envelope(ev: object, *, ts_event: int, ts_ingest: int) -> None:
    assert isinstance(ev, DomainEvent)
    assert (ev.schema_version, ev.source) == (1, "live")
    assert (ev.ts_event, ev.ts_ingest) == (ts_event, ts_ingest)
    assert ev.event_id.version == 7 and ev.event_id.variant == uuid.RFC_4122
    assert ev.event_id.int >> 80 == ts_event // 1000  # UUID7's 48-bit Unix-millisecond prefix


async def test_book_status_is_enveloped_at_the_engine_clock_reading_it_carries_as_ts_us() -> None:
    """A lifecycle edge is a local observation: `ts_event` = `ts_ingest` = `ts_us`."""
    out: list[object] = []

    async def publish(ev: object) -> None:
        out.append(ev)

    eng = BookEngine(
        symbol="BTCUSDT", depth=200, publish=publish, resubscribe=_noop, now_us=lambda: NOW_US
    )
    snapshot = parse_book_frame(frames("ws/orderbook_BTCUSDT.jsonl")[0], TICKS.get)
    assert isinstance(snapshot, BookSnapshot)
    await eng.start()
    await eng.on_event(snapshot)
    await eng.invalidate("reconnect")
    statuses = [ev for ev in out if isinstance(ev, BookStatus)]

    assert [s.state for s in statuses] == [BookPhase.LIVE, BookPhase.DESYNCED]
    for status in statuses:
        _assert_envelope(status, ts_event=NOW_US, ts_ingest=NOW_US)
        assert status.ts_us == NOW_US
    assert statuses[0].event_id != statuses[1].event_id


def _shared(bus: Bus, listed: set[str]) -> dict[str, Any]:
    """The keywords E08's three streams share: the live env, a catalogue, the injected clocks."""
    return {
        "bus": bus,
        "env": "live",
        "set_desired": lambda _t: None,
        "is_listed": lambda s: s in listed,
        "touch": lambda _t: None,
        "clock": lambda: 0.0,
        "now_us": lambda: NOW_US,
    }


TRADE: dict[str, Any] = {"parse_frame": parse_trade_frame, "topic_for": trade_topic}
BOOK: dict[str, Any] = {"parse_frame": lambda _f: None, "topic_for": book_topic}


async def test_gap_event_is_stamped_with_the_closing_print_and_that_batchs_receipt() -> None:
    """`ts_event` = `end_us` (the first live print after the window, exchange time); `ts_ingest` =
    the receipt time of the batch that closed it."""
    bus = Bus()
    gaps = bus.subscribe("g", "live.md.*.gap", QueuePolicy.NEVER_DROP)
    stream = TradeStream(**_shared(bus, {"BTCUSDT"}), **TRADE)
    stream.acquire("t", "BTCUSDT")
    await stream.handle_frame(TRADES[0])
    stream.mark_gap("reconnect")
    await stream.handle_frame(TRADES[1])
    await stream.wait_backfills()
    gap = gaps.queue.get_nowait()
    first = parse_trade_frame(TRADES[1])

    assert isinstance(gap, GapEvent) and gaps.queue.empty() and first
    assert gap.end_us == min(p.ts_event_us for p in first)
    _assert_envelope(gap, ts_event=gap.end_us, ts_ingest=NOW_US)


@pytest.mark.parametrize(
    ("stream", "own", "topic"),
    [
        (TradeStream, TRADE, trade_topic("BTCUSDT")),
        (BookStream, {**BOOK, "resubscribe": _noop}, book_topic("BTCUSDT", DEFAULT_DEPTH)),
    ],
    ids=["trade", "book"],
)
async def test_delisted_feed_health_is_enveloped_at_the_streams_clock(
    stream: Callable[..., TradeStream | BookStream], own: dict[str, Any], topic: str
) -> None:
    bus, listed = Bus(), {"BTCUSDT"}
    health = bus.subscribe("h", HEALTH, QueuePolicy.NEVER_DROP)
    made = stream(**_shared(bus, listed), **own)
    made.acquire("t", "BTCUSDT")
    listed.clear()
    assert await made.prune_unlisted() == ["BTCUSDT"]
    ev = health.queue.get_nowait()

    assert isinstance(ev, FeedHealthEvent) and (ev.topic, ev.state) == (topic, "delisted")
    _assert_envelope(ev, ts_event=NOW_US, ts_ingest=NOW_US)


async def test_ticker_feed_health_is_enveloped_at_the_streams_clock() -> None:
    bus = Bus()
    health = bus.subscribe("h", HEALTH, QueuePolicy.NEVER_DROP)
    stream = TickerStream(
        **_shared(bus, {"BTCUSDT"}), parse_frame=parse_ticker_frame, topic_for=ticker_topic
    )
    stream.acquire("t", "BTCUSDT")
    await stream.handle_frame(frames("ws/tickers_BTCUSDT.jsonl")[0])
    ev = health.queue.get_nowait()

    assert isinstance(ev, FeedHealthEvent) and ev.state == "healthy"
    _assert_envelope(ev, ts_event=NOW_US, ts_ingest=NOW_US)


def test_watchdog_stale_feed_health_is_enveloped_at_its_wall_clock() -> None:
    """The age comes from the monotonic clock; the envelope from the injected wall clock."""
    seen: list[FeedHealthEvent] = []
    mono = [100.0]
    dog = StalenessWatchdog(lambda: mono[0], seen.append, now_us=lambda: NOW_US)
    dog.watch("trade.BTCUSDT")
    mono[0] += 12.5
    assert dog.check() == ["trade.BTCUSDT"]

    (ev,) = seen
    assert (ev.state, ev.last_msg_age_s) == ("stale", 12.5)
    _assert_envelope(ev, ts_event=NOW_US, ts_ingest=NOW_US)


async def _no_socket() -> Socket:
    raise AssertionError("never dialled: this test opens no socket")


def _manager(bus: Bus, dog: StalenessWatchdog, sleep: Sleep = asyncio.sleep) -> ConnectionManager:
    return ConnectionManager(
        _no_socket,
        SubscriptionPlanner(),
        dog,
        ReconnectPolicy(),
        ConnectionRateGuard(lambda: 0.0),
        lambda _m: None,
        sleep=sleep,
        bus=bus,
        now_us=lambda: NOW_US,
    )


async def test_connection_feed_health_is_enveloped_at_its_wall_clock() -> None:
    bus = Bus()
    health = bus.subscribe("h", HEALTH, QueuePolicy.NEVER_DROP)
    manager = _manager(bus, StalenessWatchdog(lambda: 0.0, lambda _e: None))
    manager.set_desired({"publicTrade.BTCUSDT", "tickers.BTCUSDT"})
    await manager.emit_health("resubscribing")
    events = [health.queue.get_nowait() for _ in range(2)]

    assert health.queue.empty()
    for ev in events:
        assert isinstance(ev, FeedHealthEvent) and ev.state == "resubscribing"
        _assert_envelope(ev, ts_event=NOW_US, ts_ingest=NOW_US)
    assert len({ev.event_id for ev in events}) == 2


async def test_connection_stale_loop_feed_health_is_enveloped_at_its_wall_clock() -> None:
    """#1913's stale loop publishes each newly stale topic itself, at the injected wall clock."""
    bus, mono = Bus(), [0.0]
    health = bus.subscribe("h", HEALTH, QueuePolicy.NEVER_DROP)
    dog = StalenessWatchdog(lambda: mono[0], lambda _e: None)

    async def sleep(_seconds: float) -> None:  # fake time: each check runs past every limit
        mono[0] += 60.0

    dog.watch("trade.BTCUSDT")
    await _manager(bus, dog, sleep)._watch()  # returns once every watched topic is stale
    ev = health.queue.get_nowait()

    assert health.queue.empty()
    assert isinstance(ev, FeedHealthEvent) and (ev.topic, ev.state) == ("trade.BTCUSDT", "stale")
    _assert_envelope(ev, ts_event=NOW_US, ts_ingest=NOW_US)
