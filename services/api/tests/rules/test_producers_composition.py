"""E35-T15 PR 2 (#5745): the composition (`build_bridge`, `app.py`) and the feed-health watch.
The end-to-end pair lives in `test_producers_e2e.py`.

Clocks are fakes; the feed-health event is the ingestion module's own model and the topic
mapping the adapter's.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.bars.emit import BarEmission, EmitRouter
from candleviewer.bars.models import BarUpdate
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import StreamInvalidated, Topic
from candleviewer.exchange.bybit.public_ws import stream_for_topic
from candleviewer.ingestion.watchdog import feed_health
from candleviewer.rules.manager import EvaluableRule, InMemoryRuleStore
from candleviewer.rules.producers import ProducerBridge, PushSink
from candleviewer.rules.runner import PushedMetricSource
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules.vocabulary.build import PRODUCER_GAP_REASON, build_vocabulary
from candleviewer.rules_producers_wiring import (
    BarFieldProducer,
    BookTicks,
    FeedHealthWatch,
    QuoteProducer,
    build_bridge,
)
from candleviewer.settings import Settings
from tests.rules.test_instance_binding import ref
from tests.rules.test_producers import Rig, _never
from tests.rules.test_producers_bars import CLOSE_US, M1, _bar, _bar_rule
from tests.rules.test_producers_market import _Frames, _hand_driven, _quote, _rule

CLOSE_MS = CLOSE_US // 1000
BOUND = frozenset({
    "price", "spread_ticks", "spread_bps", "mid", "microprice", "dom_imbalance_ratio",
    "book_pressure", "book_staleness_ms", "delta", "bar_volume", "min_delta", "max_delta",
    "buy_sell_ratio",
})  # fmt: skip


async def _none() -> list[EvaluableRule]:
    return []


def _submit(_t: str, _s: str | None, _tf: str | None) -> bool:
    return True


def _subscribers(bus: Bus) -> list[str]:
    return sorted(s.name for s in bus._subscriptions if s.name.startswith("rule-producers-"))


async def _no_hook(*_args: Any) -> None:
    """No audit backend or bus fan-out in these rigs."""


def _app(*, enabled: bool) -> tuple[Any, Any]:
    app = create_app(Settings(rules_evaluator_enabled=enabled))
    ctx = app.state.app_context
    ctx.rules.bind(store=InMemoryRuleStore(), audit=_no_hook, broadcast=_no_hook)
    return app, ctx


def _bar_sinks(app: Any) -> list[Any]:
    return list(app.state.bars_runtime.builder_set._router._sinks)


# --- composition ---------------------------------------------------------------------------------


async def test_with_the_evaluator_off_nothing_is_attached() -> None:
    """Scenario: With the evaluator off nothing is attached."""
    app, ctx = _app(enabled=False)
    assert ctx.rules._producers is None
    assert not any(isinstance(s, BarFieldProducer) for s in _bar_sinks(app))
    await ctx.rules.start(ctx)
    try:
        assert _subscribers(ctx.bus.bus) == []
        assert ctx.rules.producer_gaps() is None  # the vocabulary is unchanged
    finally:
        await ctx.rules.stop(1.0)


async def test_composition_evaluator_on_splices_the_bar_sink_and_subscribes_while_running() -> None:
    app, ctx = _app(enabled=True)
    bridge = ctx.rules._producers
    assert isinstance(bridge, ProducerBridge) and bridge.bound == BOUND
    names = [s.name for s in _bar_sinks(app)]
    assert names[-1] == "questdb" and names[-2] == "bar_fields"  # after the engine, before writer
    # The bars' one router, on the live env, is the only emitter into the bar producer: a replay
    # session never reaches it (C-2.11).
    assert [s for s in _bar_sinks(app) if isinstance(s, BarFieldProducer)] == [_bar_sinks(app)[-2]]
    assert app.state.bars_runtime.builder_set._env == ctx.settings.environment.value
    assert _subscribers(ctx.bus.bus) == []  # nothing before the evaluator starts
    await ctx.rules.start(ctx)
    try:
        assert _subscribers(ctx.bus.bus) == [
            "rule-producers-feed-health", "rule-producers-quote", "rule-producers-ticker",
        ]  # fmt: skip
        assert ctx.rules.producer_gaps() == bridge.registered - BOUND
    finally:
        await ctx.rules.stop(1.0)
    assert _subscribers(ctx.bus.bus) == [] and bridge.source is None


def test_build_bridge_feeds_are_the_adapters_stream_kinds() -> None:
    bridge = build_bridge(Bus(), "demo", _none, bars=None, books=lambda: None,
                          topics=stream_for_topic)  # fmt: skip
    assert bridge.bound == BOUND - {"delta", "bar_volume", "min_delta", "max_delta",
                                    "buy_sell_ratio"}  # fmt: skip
    with pytest.raises(ValueError, match="live env"):
        build_bridge(Bus(), "replay-00000000-0000-0000-0000-000000000001", _none, bars=None,
                     books=lambda: None, topics=stream_for_topic)  # fmt: skip


def test_build_bridge_quote_producer_reads_the_books_frames_for_a_quiet_top() -> None:
    frames = _Frames()
    bridge = build_bridge(Bus(), "demo", _none, bars=None, books=lambda: frames,
                          topics=stream_for_topic)  # fmt: skip
    [quotes] = [p for p in bridge._producers if isinstance(p, QuoteProducer)]
    assert quotes._books is not None and quotes._books() is frames


async def test_the_vocabulary_marks_the_metrics_that_have_no_live_producer() -> None:
    """Scenario: The vocabulary marks the metrics that have no live producer."""
    registry = default_registry()
    bridge = build_bridge(
        Bus(), "demo", _none, bars=BarFieldProducer(lambda: None, lambda _s: None),
        books=lambda: None, topics=stream_for_topic,
    )  # fmt: skip
    plain = {s["id"]: s for s in build_vocabulary(registry)["signals"]}
    bridge.attach(PushedMetricSource(), _submit)
    try:
        marked = {s["id"]: s for s in build_vocabulary(registry, producer_gaps=bridge.uncovered())
                  ["signals"]}  # fmt: skip
    finally:
        await bridge.detach()
    assert {n: marked[n] for n in BOUND} == {n: plain[n] for n in BOUND}
    for name in set(marked) - BOUND:
        assert marked[name]["available"] is False
        assert marked[name]["unavailable_reason"] == PRODUCER_GAP_REASON
        assert marked[name]["missing_dependency"] == {"kind": "producer"}
    assert build_vocabulary(registry, producer_gaps=bridge.uncovered())["signals"] == list(
        plain.values()
    )  # detached: nothing marked


# --- the feed-health watch -----------------------------------------------------------------------


class _Marks:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str]] = []
        self.seen = asyncio.Event()

    def __call__(self, symbol: str | None, feed: str) -> int:
        self.calls.append((symbol, feed))
        self.seen.set()
        return 1


def _health(topic: str, state: str = "stale") -> Any:
    return feed_health(topic, state, 11.0, now_us=CLOSE_US)


@pytest.mark.parametrize(
    ("topic", "marks"),
    [
        ("publicTrade.BTCUSDT", [("BTCUSDT", "trades")]),
        ("orderbook.50.BTCUSDT", [("BTCUSDT", "book")]),  # delta and snapshot: one feed
        ("tickers.ETHUSDT", [("ETHUSDT", "ticker")]),
        ("*", [(None, "book"), (None, "ticker"), (None, "trades")]),  # socket-wide: every symbol
        ("allLiquidation.BTCUSDT", []),  # no producer reads it
        ("unknown.BTCUSDT", []),  # unmappable: the lost bound covers it
    ],
)
def test_feed_health_watch_lost_feed_maps_the_topic_to_its_feeds(
    topic: str, marks: list[tuple[str | None, str]]
) -> None:
    mark = _Marks()
    watch = FeedHealthWatch(Bus(), "demo", mark, stream_for_topic)
    assert watch.offer(_health(topic)) == len(marks) and mark.calls == marks


@pytest.mark.parametrize("state", ["healthy", "resubscribing", "warming"])
def test_feed_health_watch_states_other_than_lost_mark_nothing(state: str) -> None:
    mark = _Marks()
    watch = FeedHealthWatch(Bus(), "demo", mark, stream_for_topic)
    assert watch.offer(_health("publicTrade.BTCUSDT", state)) == 0 and mark.calls == []


def test_feed_health_watch_invalidation_and_foreign_items_mark_nothing() -> None:
    mark = _Marks()
    watch = FeedHealthWatch(Bus(), "demo", mark, stream_for_topic)
    with capture_logs() as logs:
        assert watch.offer(StreamInvalidated(topic="x", ts_event=CLOSE_US)) == 0
        assert watch.offer(object()) == 0
    assert mark.calls == [] and [e["event"] for e in logs] == ["rules.feed_health_invalidated"]


async def test_feed_health_watch_subscribes_the_live_health_topic_only_while_attached() -> None:
    bus, mark = Bus(), _Marks()
    watch = FeedHealthWatch(bus, "demo", mark, stream_for_topic)
    bridge = ProducerBridge(_none, {}, sleep=_never)
    bridge.add(watch)
    health = Topic(env="demo", domain="health", detail="feed")
    assert bus._resolve(health) == []
    bridge.attach(PushedMetricSource(), _submit)
    try:
        await bus.publish(health, _health("publicTrade.BTCUSDT"))
        async with asyncio.timeout(5):
            await mark.seen.wait()
    finally:
        await bridge.detach()
    assert mark.calls == [("BTCUSDT", "trades")] and bus._resolve(health) == []
    with pytest.raises(ValueError, match="live env"):
        FeedHealthWatch(bus, "replay-00000000-0000-0000-0000-000000000001", mark, stream_for_topic)


# --- isolation ------------------------------------------------------------------------------------


class _Raising(BarFieldProducer):
    def _take(self, sink: PushSink, emission: BarEmission) -> None:
        raise RuntimeError("secret value 12.5")


class _Recording:
    name = "after"

    def __init__(self) -> None:
        self.seen: list[BarEmission] = []

    async def emit(self, emission: BarEmission) -> None:
        self.seen.append(emission)


async def test_a_producer_that_raises_is_isolated() -> None:
    """Scenario: A producer that raises is isolated."""
    raising = _Raising(lambda: None, lambda _s: Decimal("0.001"), sleep=_never)
    quotes = QuoteProducer(Bus(), "demo", BookTicks(), sleep=_never)
    after = _Recording()
    router = EmitRouter([raising, after])
    rules = [_bar_rule(), _rule("mid", "on_book_update", rid=8)]
    async with Rig(rules, raising, quotes) as rig:  # type: ignore[arg-type]  # MetricProducers
        await _hand_driven(quotes)
        with capture_logs() as logs:
            for _ in range(3):
                await router.emit(M1, (BarUpdate(kind="close", bar=_bar()),), 1)
                quotes.offer(_quote())
                quotes.flush()
        assert len(after.seen) == 3  # the emit path reaches the next sink every time
        assert rig.source.read(ref("mid", symbol="BTCUSDT")).value is not None  # others push
        assert rig.source.read(ref("delta", symbol="BTCUSDT", timeframe="1m")).reason == "warmup"
        assert rig.sample("rule_metric_producer_errors_total", producer="bar_fields") == 3
    failed = [e for e in logs if e["event"] == "rules.producer_failed"]
    assert failed == [{"event": "rules.producer_failed", "producer": "bar_fields",
                       "error": "RuntimeError", "log_level": "error"}]  # fmt: skip
