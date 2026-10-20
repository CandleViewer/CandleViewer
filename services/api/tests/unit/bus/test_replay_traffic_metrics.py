"""Replay traffic stays out of the bus's process-wide series (E26-T03, 24 Sec.2.9).

`bus_published_total{topic_class}`, `bus_delivered_total{subscriber}`,
`bus_subscriber_lag{subscriber}`, `ingest_queue_full_total{class}`,
`bus_stream_invalidated_total{topic_class}` and `bus_conflated_total{topic_class}` name no env, and
a replay lane reuses its live twin's subscriber name (`bars.{symbol}`). Counted, a slow replay
consumer, which is replay's designed backpressure, would fire the live `IngestionNeverDropQueueFull`
alert, overwrite the live lane's lag gauge and fill both drop counters with replay noise. The replay
clock's own `replay_*` series measure it.

The same state, a lane held at depth while its publisher waits, would also log the "bus subscriber
lagging" warning on every delivery: at replay's 100x, a warning per event in the live logs."""

from __future__ import annotations

import asyncio
import uuid

from structlog.testing import capture_logs

from candleviewer.bus.bus import DEFAULT_LAG_WARN_THRESHOLD, Bus
from candleviewer.bus.metrics import (
    bus_conflated_total,
    bus_delivered_total,
    bus_published_total,
    bus_stream_invalidated_total,
    bus_subscriber_lag,
    ingest_queue_full_total,
)
from candleviewer.bus.models import QueuePolicy, Topic, replay_env

REPLAY = replay_env(uuid.UUID("0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18"))
LANE = "bars.BTCUSDT"  # the live bars lane's name, which a replay session's lane reuses
BOOK_LANE = "book.BTCUSDT"  # an `INVALIDATE_ON_FULL` lane
TICKER_LANE = "ticker.BTCUSDT"  # a `CONFLATE_LATEST` lane


def series() -> tuple[float, float, float, float, float, float]:
    """The six series two trades on `{env}.md.BTCUSDT.trade` to the three lanes can move."""
    return (
        bus_published_total.labels(topic_class="md.trade")._value.get(),
        bus_delivered_total.labels(subscriber=LANE)._value.get(),
        bus_subscriber_lag.labels(subscriber=LANE)._value.get(),
        ingest_queue_full_total.labels(**{"class": "trade"})._value.get(),
        bus_stream_invalidated_total.labels(topic_class="md.trade")._value.get(),
        bus_conflated_total.labels(topic_class="md.trade")._value.get(),
    )


def trade_topic(env: str) -> Topic:
    return Topic(env=env, domain="md", symbol="BTCUSDT", detail="trade")


async def publish_two_through_full_lanes(env: str) -> None:
    """Two trades to one lane of each queue policy, each holding one. `NEVER_DROP`: the second
    waits for the reader (the queue is full), then both arrive, in order. `INVALIDATE_ON_FULL`:
    the second flushes the first for a marker. `CONFLATE_LATEST`: the second replaces the first."""
    bus = Bus()
    pattern = f"{env}.md.BTCUSDT.trade"
    lane = bus.subscribe(LANE, pattern, QueuePolicy.NEVER_DROP, maxsize=1)
    bus.subscribe(BOOK_LANE, pattern, QueuePolicy.INVALIDATE_ON_FULL, maxsize=1)
    bus.subscribe(TICKER_LANE, pattern, QueuePolicy.CONFLATE_LATEST, maxsize=1)
    await bus.publish(trade_topic(env), "t1")
    held = asyncio.ensure_future(bus.publish(trade_topic(env), "t2"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not held.done()  # backpressure: the publisher waits, nothing is dropped
    assert await lane.get() == "t1"
    await held
    assert await lane.get() == "t2"


async def test_replay_publishes_and_full_replay_queues_leave_the_live_series_unchanged() -> None:
    bus_subscriber_lag.labels(subscriber=LANE).set(7)  # what the live lane last reported
    before = series()
    await publish_two_through_full_lanes(REPLAY)
    assert series() == before


async def test_live_traffic_still_counts_in_every_series() -> None:
    published, delivered, _, full, invalidated, conflated = series()
    await publish_two_through_full_lanes("live")
    assert series() == (published + 2, delivered + 2, 1, full + 1, invalidated + 1, conflated + 1)


async def lag_warnings(env: str) -> list[tuple[str, str, int]]:
    """The "bus subscriber lagging" warnings (subscriber, topic, depth) logged while a default
    `NEVER_DROP` lane, whose threshold is 512, takes 513 trades nobody reads: the state a replay
    consumer is held in while its publisher waits."""
    bus = Bus()
    bus.subscribe(LANE, f"{env}.md.BTCUSDT.trade", QueuePolicy.NEVER_DROP)
    with capture_logs() as logs:
        for i in range(DEFAULT_LAG_WARN_THRESHOLD + 1):
            await bus.publish(trade_topic(env), i)
    return [
        (e["subscriber"], e["topic"], e["queue_depth"])
        for e in logs
        if e["event"] == "bus subscriber lagging"
    ]


async def test_a_replay_subscriber_at_depth_logs_no_lag_warning() -> None:
    assert await lag_warnings(REPLAY) == []


async def test_a_live_subscriber_at_depth_still_logs_the_lag_warning() -> None:
    key = trade_topic("live").key
    assert await lag_warnings("live") == [(LANE, key, 512), (LANE, key, 513)]
