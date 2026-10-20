"""C6 envelope on E08's control events (#3876; drift D1, decision (a) on #2701).

`BookStatus`, `GapEvent` and `FeedHealthEvent` carry the 24 §1.4 envelope with `schema_version = 1`
(24 §2.9: adding it is additive, so 24 §17.1 asks no bump). Each is checked where production builds
it, on recorded fixtures and injected clocks: `source = "live"`, a UUID7 `event_id` stamped with the
millisecond of `ts_event`, and the timestamps 24 §2.9 gives the event.
"""

from __future__ import annotations

import uuid

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, TopicPattern
from candleviewer.domain.events import DomainEvent
from candleviewer.exchange.base.models import BookSnapshot
from candleviewer.exchange.bybit.orderbook import parse_book_frame
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion.connection import ConnectionManager, Socket
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import GapEvent, TradeStream
from candleviewer.ingestion.watchdog import FeedHealthEvent, StalenessWatchdog
from tests._corpus import TICKS, frames

#: The producers' injected wall clock (µs), inside the recorded trade capture's window.
NOW_US = 1_792_391_740_000_123
TRADES = frames("ws/recorded_publicTrade_BTCUSDT.jsonl")
HEALTH = TopicPattern(env="live", domain="health", detail="feed")


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

    async def resubscribe() -> None:
        return None

    eng = BookEngine(
        symbol="BTCUSDT", depth=200, publish=publish, resubscribe=resubscribe, now_us=lambda: NOW_US
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


def _trades(bus: Bus, *, listed: set[str] | None = None) -> TradeStream:
    symbols = {"BTCUSDT"} if listed is None else listed
    stream = TradeStream(
        bus=bus,
        env="live",
        set_desired=lambda _t: None,
        parse_frame=parse_trade_frame,
        topic_for=trade_topic,
        is_listed=lambda s: s in symbols,
        touch=lambda _t: None,
        clock=lambda: 0.0,
        now_us=lambda: NOW_US,
    )
    stream.acquire("t", "BTCUSDT")
    return stream


async def test_gap_event_is_stamped_with_the_closing_print_and_that_batchs_receipt() -> None:
    """`ts_event` = `end_us` (the first live print after the window, exchange time); `ts_ingest` =
    the receipt time of the batch that closed it."""
    bus = Bus()
    gaps = bus.subscribe("g", "live.md.*.gap", QueuePolicy.NEVER_DROP)
    stream = _trades(bus)
    await stream.handle_frame(TRADES[0])
    stream.mark_gap("reconnect")
    await stream.handle_frame(TRADES[1])
    await stream.wait_backfills()
    gap = gaps.queue.get_nowait()
    first = parse_trade_frame(TRADES[1])

    assert isinstance(gap, GapEvent) and gaps.queue.empty() and first
    assert gap.end_us == min(p.ts_event_us for p in first)
    _assert_envelope(gap, ts_event=gap.end_us, ts_ingest=NOW_US)


async def test_delisted_feed_health_is_enveloped_at_the_streams_clock() -> None:
    bus = Bus()
    health = bus.subscribe("h", HEALTH, QueuePolicy.NEVER_DROP)
    listed = {"BTCUSDT"}
    stream = _trades(bus, listed=listed)
    listed.clear()
    assert await stream.prune_unlisted() == ["BTCUSDT"]
    ev = health.queue.get_nowait()

    assert isinstance(ev, FeedHealthEvent) and (ev.topic, ev.state) == (
        trade_topic("BTCUSDT"),
        "delisted",
    )
    _assert_envelope(ev, ts_event=NOW_US, ts_ingest=NOW_US)


async def test_ticker_feed_health_is_enveloped_at_the_streams_clock() -> None:
    bus = Bus()
    health = bus.subscribe("h", HEALTH, QueuePolicy.NEVER_DROP)
    stream = TickerStream(
        bus=bus,
        env="live",
        set_desired=lambda _t: None,
        parse_frame=parse_ticker_frame,
        topic_for=ticker_topic,
        is_listed=lambda s: s == "BTCUSDT",
        touch=lambda _t: None,
        clock=lambda: 0.0,
        now_us=lambda: NOW_US,
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


async def test_connection_feed_health_is_enveloped_at_its_wall_clock() -> None:
    bus = Bus()
    health = bus.subscribe("h", HEALTH, QueuePolicy.NEVER_DROP)

    async def no_socket() -> Socket:
        raise AssertionError("never dialled: this test opens no socket")

    manager = ConnectionManager(
        no_socket,
        SubscriptionPlanner(),
        StalenessWatchdog(lambda: 0.0, lambda _e: None),
        ReconnectPolicy(),
        ConnectionRateGuard(lambda: 0.0),
        lambda _m: None,
        bus=bus,
        now_us=lambda: NOW_US,
    )
    manager.set_desired({"publicTrade.BTCUSDT", "tickers.BTCUSDT"})
    await manager.emit_health("resubscribing")
    events = [health.queue.get_nowait() for _ in range(2)]

    assert health.queue.empty()
    for ev in events:
        assert isinstance(ev, FeedHealthEvent) and ev.state == "resubscribing"
        _assert_envelope(ev, ts_event=NOW_US, ts_ingest=NOW_US)
    assert len({ev.event_id for ev in events}) == 2
