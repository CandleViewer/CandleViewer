"""E35-T15 PR 2 (#5745): the metric producer bridge (`rules/producers.py`).

Unit tests on fakes: the demand (bound refs of the evaluable rules, market scope only, capped at
`MAX_DEMAND_REFS`), the push sink's refusals and guard, the watchdog's ``source_degraded`` mark
and the vocabulary's uncovered set. No sleeps: the clock is a fake, the timers are driven by hand.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics, AlertTick
from candleviewer.alerts.gating import StormSuppressor
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.rules import producers as producers_mod
from candleviewer.rules.evaluator import metric_key
from candleviewer.rules.ir.models import MetricRef, Rule
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules.producers import (
    LOST_AFTER_S,
    MAX_DEMAND_REFS,
    SOURCE_DEGRADED,
    WARMUP_ALERT_S,
    MetricDemand,
    ProducerBridge,
    ProducerMetrics,
    PushSink,
)
from candleviewer.rules.runner import PushedMetricSource
from tests.alerts._evaluator_env import Clock as AlertClock
from tests.alerts._evaluator_env import FakeStore, ir, row
from tests.alerts._evaluator_env import Metrics as AlertCounters
from tests.alerts._owners_env import allow
from tests.rules.test_instance_binding import NOW, SCOPES, evaluator, ref, rule

TS = 1_700_000_000_000


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class Producer:
    def __init__(
        self, name: str, metrics: set[str], feeds: set[str] | None = None, *, fail: bool = False
    ) -> None:
        self.name, self.metrics = name, frozenset(metrics)
        self.feeds = frozenset(feeds or {"book"})
        self.sink: PushSink | None = None
        self.detached = False
        self.fail = fail

    def attach(self, sink: PushSink) -> None:
        self.sink = sink

    async def detach(self) -> None:
        self.detached = True
        if self.fail:
            raise RuntimeError("boom")


async def _never(_s: float) -> None:
    await asyncio.Event().wait()


class Rig:
    def __init__(self, rules: Sequence[Rule], *producers: Producer) -> None:
        self.items = [EvaluableRule(r, "simulate", None, "v1", "h") for r in rules]
        self.clock = Clock()
        self.facade = Metrics("demo")
        register_r0(self.facade)
        self.bridge = ProducerBridge(
            self._read, SCOPES, metrics=self.facade, clock=self.clock, sleep=_never
        )
        for p in producers:
            self.bridge.add(p)
        self.source = PushedMetricSource()
        self.ticks: list[tuple[str, str | None, str | None]] = []

    async def _read(self) -> list[EvaluableRule]:
        return self.items

    def _submit(self, trigger: str, symbol: str | None, timeframe: str | None) -> bool:
        self.ticks.append((trigger, symbol, timeframe))
        return True

    async def __aenter__(self) -> Rig:
        self.bridge.attach(self.source, self._submit)
        await self.bridge.refresh()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.bridge.detach()

    def sample(self, name: str, **labels: str) -> float:
        value = self.facade.registry.get_sample_value(name, {"env": "demo", **labels})
        return value or 0.0

    def refused(self, reason: str) -> float:
        return self.sample("rule_metric_refused_total", reason=reason)


def _price_rule(**kw: Any) -> Rule:
    return rule({"metric": "price"}, **kw)


def _many_refs(count: int) -> list[Rule]:
    """Rules over `count` distinct bound refs (`n` varies the params), 32 leaves a rule at most."""
    rules: list[Rule] = []
    for start in range(0, count, 32):
        leaves = [
            {"node_id": f"c{i}", "op": "gt", "left": {"metric": "mid", "params": {"n": i}},
             "right": {"const": 0}}
            for i in range(start, min(start + 32, count))
        ]  # fmt: skip
        base = _price_rule(symbols=("BTCUSDT",), rid=start + 1).model_dump(mode="json")
        base["conditions"] = {"node_id": "root", "op": "any_of", "children": leaves}
        rules.append(Rule.model_validate(base))
    return rules


# --- the demand --------------------------------------------------------------------------------


def test_metric_demand_symbol_less_ref_binds_each_listed_symbol() -> None:
    demand = MetricDemand.of([_price_rule()], SCOPES)
    (want,) = demand.by_metric["price"]
    assert want.symbols == {"BTCUSDT", "ETHUSDT"} and not want.any_symbol
    assert want.bound["ETHUSDT"] == ref("price", symbol="ETHUSDT")
    rid = str(uuid.UUID(int=7))
    assert want.owners == {"BTCUSDT": {rid}, "ETHUSDT": {rid}}  # who reads it (fair leases)


def test_metric_demand_rule_without_symbols_wants_any_symbol() -> None:
    demand = MetricDemand.of([_price_rule(symbols=())], SCOPES)
    (want,) = demand.by_metric["price"]
    assert want.any_symbol and want.symbols == frozenset()


def test_metric_demand_account_and_position_scope_refs_are_not_demanded() -> None:
    rules = [
        rule({"metric": "account_equity"}, rid=1),
        rule({"metric": "position_qty"}, rid=2),
        rule({"metric": "price", "account_id": str(uuid.UUID(int=3))}, rid=3),
    ]
    assert MetricDemand.of(rules, SCOPES).wants == {}


def test_metric_demand_keeps_params_as_authored() -> None:
    demand = MetricDemand.of(
        [rule({"metric": "book_pressure", "params": {"n": 20}}, symbols=("BTCUSDT",))], SCOPES
    )
    (want,) = demand.by_metric["book_pressure"]
    assert dict(want.params) == {"n": 20} and want.key[1] == '{"n":20}'


def test_metric_demand_cap_refuses_the_4097th_ref() -> None:
    demand = MetricDemand.of(
        [*_many_refs(MAX_DEMAND_REFS), *_many_refs(MAX_DEMAND_REFS + 1)], SCOPES
    )
    assert (demand.size, demand.refused) == (MAX_DEMAND_REFS, 1)
    assert ("mid", f'{{"n":{MAX_DEMAND_REFS}}}', None) not in demand.wants


async def test_bridge_demand_cap_refusal_is_counted_once() -> None:
    async with Rig(_many_refs(MAX_DEMAND_REFS + 1), Producer("quote", {"mid"})) as rig:
        await rig.bridge.refresh()  # the same demand again: nothing new to count
        assert rig.refused("demand_cap") == 1


# --- the sink ----------------------------------------------------------------------------------


async def test_push_sink_demanded_ref_is_written_under_the_bound_key() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule()], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "ETHUSDT")
        assert ticker.sink.push(want, "ETHUSDT", Decimal("101"), TS, 250)
        got = rig.source.read(ref("price", symbol="ETHUSDT"))
        assert (got.value, got.ts_ms, got.cadence_ms, got.reason) == (Decimal("101"), TS, 250, None)
        assert rig.sample("rule_metric_pushes_total", metric="price") == 0  # counted off the path
        rig.bridge.watch()
        assert rig.sample("rule_metric_pushes_total", metric="price") == 1


async def test_push_sink_any_symbol_want_writes_the_ticking_symbol() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=())], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "SOLUSDT")
        assert ticker.sink.push(want, "SOLUSDT", Decimal("7"), TS, 250)
        assert rig.source.read(ref("price", symbol="SOLUSDT")).value == Decimal("7")
        assert ticker.sink.wanted("price", None) == ()


async def test_a_metric_outside_the_registry_or_outside_the_demand_is_never_pushed() -> None:
    """Gherkin: a name the registry does not hold and a registry metric no rule references are
    never written, each refusal is counted, and a demanded metric nobody pushed reads warmup."""
    rogue = Producer("rogue", {"not_a_metric", "spread_bps", "price"})
    async with Rig([_price_rule(symbols=("BTCUSDT",))], rogue) as rig:
        sink = rogue.sink
        assert sink is not None
        assert not sink.push_metric("not_a_metric", "BTCUSDT", Decimal(1), TS, 100)
        assert sink.wanted("not_a_metric", "BTCUSDT") == ()
        assert not sink.push_metric("spread_bps", "BTCUSDT", Decimal(1), TS, 100)
        assert rig.source._values == {}
        assert (rig.refused("unregistered"), rig.refused("undemanded")) == (2, 1)
        unpushed = rig.source.read(ref("price", symbol="BTCUSDT"))
        assert (unpushed.value, unpushed.ts_ms, unpushed.reason) == (None, 0, "warmup")


async def test_push_sink_symbol_outside_the_want_is_refused() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=("BTCUSDT",))], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        assert not ticker.sink.push(want, "ETHUSDT", Decimal(1), TS, 250)
        assert rig.refused("undemanded") == 1 and rig.source._values == {}


async def test_push_sink_want_of_a_dropped_demand_is_refused_and_its_value_leaves() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=("BTCUSDT",))], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        ticker.sink.push(want, "BTCUSDT", Decimal(1), TS, 250)
        version = ticker.sink.demand_version
        rig.items.clear()
        await rig.bridge.refresh()
        assert ticker.sink.demand_version == version + 1
        assert not ticker.sink.push(want, "BTCUSDT", Decimal(2), TS, 250)
        assert rig.source._values == {} and rig.bridge.lives == 0
        assert rig.sample("rule_metric_pushes_total", metric="price") == 1  # flushed on the drop


async def test_push_sink_unchanged_demand_keeps_the_want_and_its_bookkeeping() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule()], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        ticker.sink.push(want, "BTCUSDT", Decimal(1), TS, 250)
        version = rig.bridge.version
        await rig.bridge.refresh()
        assert rig.bridge.version == version and rig.bridge.demand.current(want)
        rig.items[0] = EvaluableRule(_price_rule(symbols=("BTCUSDT",)), "simulate", None, "v", "h")
        await rig.bridge.refresh()  # ETHUSDT dropped: BTCUSDT's push bookkeeping carries over
        (moved,) = ticker.sink.wanted("price", "BTCUSDT")
        assert moved is not want and set(moved.lives) == {"BTCUSDT"} and rig.bridge.lives == 1


async def test_push_sink_none_value_is_not_pushed() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule()], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        assert not ticker.sink.push(want, "BTCUSDT", None, TS, 250)
        assert rig.source._values == {}


async def test_push_sink_live_cap_refuses_a_new_key_past_the_bound() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=())], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        rig.bridge.any_lives = MAX_DEMAND_REFS  # as if the any-symbol budget were used up
        assert not ticker.sink.push(want, "BTCUSDT", Decimal(1), TS, 250)
        assert rig.refused("demand_cap") == 1


async def test_push_sink_tick_reaches_the_evaluator_and_not_after_detach() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    rig = Rig([_price_rule()], ticker)
    async with rig:
        assert ticker.sink is not None
        assert ticker.sink.tick("on_bar_close", "BTCUSDT", "1m")
        sink = ticker.sink
    assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]
    assert ticker.detached and not sink.tick("on_price_update", "BTCUSDT")


async def test_push_sink_lease_refusal_is_counted() -> None:
    bars = Producer("bars", {"delta"}, {"trades"})
    async with Rig([_price_rule()], bars) as rig:
        assert bars.sink is not None
        bars.sink.lease_refused()
        assert rig.refused("lease") == 1


async def test_push_sink_guard_isolates_and_logs_once_per_episode() -> None:
    quote, ticker = Producer("quote", {"mid"}), Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(), rule({"metric": "mid"}, rid=2)], quote, ticker) as rig:
        assert quote.sink is not None and ticker.sink is not None

        def boom(_value: Decimal) -> None:
            raise ValueError("secret-value-123")

        with capture_logs() as logs:
            for _ in range(3):
                assert quote.sink.guard(boom, Decimal("123")) is None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        assert ticker.sink.push(want, "BTCUSDT", Decimal(1), TS, 250)  # the others still push
        assert rig.sample("rule_metric_producer_errors_total", producer="quote") == 3
        assert [e["event"] for e in logs] == ["rules.producer_failed"]
        assert logs[0]["producer"] == "quote" and logs[0]["error"] == "ValueError"
        assert "secret-value-123" not in repr(logs) and "123" not in repr(logs)
        assert quote.sink.guard(lambda: 5) == 5  # a success ends the episode
        with capture_logs() as again:
            quote.sink.guard(boom, Decimal(1))
        assert [e["event"] for e in again] == ["rules.producer_failed"]


async def test_push_sink_guard_never_swallows_cancellation() -> None:
    quote = Producer("quote", {"mid"})
    async with Rig([], quote):
        assert quote.sink is not None

        def cancelled() -> None:
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            quote.sink.guard(cancelled)


# --- the bridge --------------------------------------------------------------------------------


def test_bridge_add_refuses_a_second_producer_of_one_metric() -> None:
    bridge = ProducerBridge(Rig([])._read, SCOPES)
    bridge.add(Producer("a", {"mid"}))
    with pytest.raises(ValueError, match="already has a producer"):
        bridge.add(Producer("b", {"mid", "price"}))


async def test_bridge_add_after_attach_is_refused() -> None:
    async with Rig([]) as rig:
        with pytest.raises(RuntimeError):
            rig.bridge.add(Producer("late", {"mid"}))


async def test_bridge_attach_twice_is_a_no_op_and_detach_is_idempotent() -> None:
    p = Producer("quote", {"mid"})
    async with Rig([], p) as rig:
        first = p.sink
        rig.bridge.attach(PushedMetricSource(), rig._submit)
        assert p.sink is first
    await rig.bridge.detach()
    assert rig.bridge.source is None


async def test_bridge_detach_carries_on_past_a_failing_producer() -> None:
    bad, good = Producer("bad", {"mid"}, fail=True), Producer("good", {"price"})
    async with Rig([], bad, good) as rig:
        pass
    assert bad.detached and good.detached and rig.bridge.source is None
    assert rig.sample("rule_metric_producer_errors_total", producer="bad") == 1


async def test_bridge_refresh_failure_keeps_the_last_demand() -> None:
    async with Rig([_price_rule()]) as rig:
        before = rig.bridge.demand

        async def broken() -> list[EvaluableRule]:
            raise OSError("store down")

        rig.bridge._rules = broken
        with capture_logs() as logs:
            await rig.bridge.refresh()
        assert rig.bridge.demand is before
        assert logs[0]["event"] == "rules.producer_demand_failed"


async def _until(done: Callable[[], bool]) -> bool:
    for _ in range(100):  # yield to the bridge's own tasks; never a sleep
        if done():
            return True
        await asyncio.sleep(0)
    return done()


async def test_bridge_poke_refreshes_the_demand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(producers_mod, "REFRESH_S", 3_600.0)  # only the poke can wake the loop
    rig = Rig([], Producer("ticker", {"price"}, {"ticker"}))
    calls: list[int] = []
    real = rig.bridge.refresh

    async def counted() -> None:
        await real()
        calls.append(1)

    rig.bridge.refresh = counted  # type: ignore[method-assign]  # spy on the loop's call
    async with rig:  # one refresh by the rig, one by the loop, which then parks
        assert await _until(lambda: len(calls) == 2)
        rig.items.append(EvaluableRule(_price_rule(), "simulate", None, "v", "h"))
        assert not await _until(lambda: len(calls) == 3)  # parked: the rule change is unread
        rig.bridge.poke()
        assert await _until(lambda: len(calls) == 3)
        assert "price" in rig.bridge.demand.by_metric


async def test_bridge_uncovered_lists_names_no_producer_covers_only_while_attached() -> None:
    rig = Rig([], Producer("ticker", {"price"}, {"ticker"}))
    assert rig.bridge.uncovered() is None
    async with rig:
        gaps = rig.bridge.uncovered()
        assert gaps == frozenset(SCOPES) - {"price"}
    assert rig.bridge.uncovered() is None


# --- the watchdog ------------------------------------------------------------------------------


async def _pushed_price(rig: Rig, ticker: Producer, cadence_ms: int = 250) -> None:
    assert ticker.sink is not None
    (want,) = ticker.sink.wanted("price", "BTCUSDT")
    assert ticker.sink.push(want, "BTCUSDT", Decimal(1), TS, cadence_ms)


async def test_watchdog_marks_a_silent_ref_source_degraded_after_the_lost_bound() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=("BTCUSDT",))], ticker) as rig:
        await _pushed_price(rig, ticker)
        rig.clock.t += LOST_AFTER_S - 1
        assert rig.bridge.watch() == 0
        rig.clock.t += 1
        with capture_logs() as logs:
            assert rig.bridge.watch() == 1
            assert rig.bridge.watch() == 0  # marked once
        got = rig.source.read(ref("price", symbol="BTCUSDT"))
        assert (got.value, got.reason, got.ts_ms) == (None, SOURCE_DEGRADED, 0)  # stale at once
        assert logs == [
            {"event": "rules.metric_source_lost", "refs": 1, "metrics": ["price"],
             "producers": ["ticker"], "log_level": "warning"}
        ]  # fmt: skip


async def test_watchdog_lost_bound_stretches_to_six_cadences() -> None:
    bars = Producer("bars", {"price"}, {"trades"})
    async with Rig([_price_rule(symbols=("BTCUSDT",))], bars) as rig:
        await _pushed_price(rig, bars, cadence_ms=3_600_000)  # an hourly bar
        rig.clock.t += 6 * 3_600 - 1
        assert rig.bridge.watch() == 0
        rig.clock.t += 1
        assert rig.bridge.watch() == 1


async def test_watchdog_mark_is_overwritten_by_the_next_push() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=("BTCUSDT",))], ticker) as rig:
        await _pushed_price(rig, ticker)
        rig.clock.t += LOST_AFTER_S
        rig.bridge.watch()
        await _pushed_price(rig, ticker)
        got = rig.source.read(ref("price", symbol="BTCUSDT"))
        assert (got.value, got.reason) == (Decimal(1), None)
        rig.clock.t += LOST_AFTER_S
        assert rig.bridge.watch() == 1  # a fresh episode marks again


async def test_watchdog_ref_without_producer_is_never_marked() -> None:
    async with Rig([_price_rule(symbols=("BTCUSDT",))]) as rig:
        rig.clock.t += 10 * LOST_AFTER_S
        assert rig.bridge.watch() == 0
        assert rig.source.read(ref("price", symbol="BTCUSDT")).reason == "warmup"


async def test_watchdog_counts_refs_in_warmup_past_the_alert_bound() -> None:
    ticker, quote = Producer("ticker", {"price"}, {"ticker"}), Producer("quote", {"mid"})
    rules = [_price_rule(), rule({"metric": "mid"}, symbols=(), rid=2)]
    async with Rig(rules, ticker, quote) as rig:
        await _pushed_price(rig, ticker)
        rig.bridge.watch()
        assert rig.sample("rule_metrics_in_warmup") == 0
        rig.clock.t += WARMUP_ALERT_S + 1
        rig.bridge.watch()
        assert rig.sample("rule_metrics_in_warmup") == 2  # ETHUSDT's price, the any-symbol mid


async def test_watchdog_loop_survives_a_failing_pass() -> None:
    passes: list[int] = []
    gate = asyncio.Event()

    async def tick(_s: float) -> None:
        if len(passes) >= 2:
            gate.set()
            await asyncio.Event().wait()
        passes.append(1)

    rig = Rig([])
    rig.bridge._sleep = tick
    rig.bridge.watch = lambda: 1 // 0  # type: ignore[method-assign]  # every pass raises
    with capture_logs() as logs:
        async with rig:
            await gate.wait()
    assert [e["event"] for e in logs].count("rules.producer_watchdog_failed") == 2


async def test_feed_degraded_marks_only_the_pushed_refs_of_its_feed_and_symbol() -> None:
    ticker, quote = Producer("ticker", {"price"}, {"ticker"}), Producer("quote", {"mid"})
    rules = [_price_rule(), rule({"metric": "mid"}, rid=2)]
    async with Rig(rules, ticker, quote) as rig:
        assert ticker.sink is not None and quote.sink is not None
        for symbol in ("BTCUSDT", "ETHUSDT"):
            (want,) = ticker.sink.wanted("price", symbol)
            ticker.sink.push(want, symbol, Decimal(1), TS, 250)
        (mid,) = quote.sink.wanted("mid", "BTCUSDT")
        quote.sink.push(mid, "BTCUSDT", Decimal(1), TS, 100)
        assert rig.bridge.feed_degraded("BTCUSDT", "ticker") == 1
        assert rig.bridge.feed_degraded("BTCUSDT", "ticker") == 0
        assert rig.source.read(ref("price", symbol="BTCUSDT")).reason == SOURCE_DEGRADED
        assert rig.source.read(ref("price", symbol="ETHUSDT")).reason is None
        assert rig.source.read(ref("mid", symbol="BTCUSDT")).reason is None
        assert rig.bridge.feed_degraded(None, "book") == 1


# --- PushedMetricSource ------------------------------------------------------------------------


def test_pushed_metric_source_push_key_matches_push_and_discard_forgets() -> None:
    src, r = PushedMetricSource(), MetricRef(metric="price", symbol="BTCUSDT")
    src.push_key(metric_key(r), Decimal(2), TS, 250)
    assert src.read(r).value == Decimal(2)
    src.discard(metric_key(r))
    assert src.read(r).reason == "warmup"


async def test_push_sink_push_metric_by_name_writes_a_demanded_ref() -> None:
    pressure = Producer("depth", {"book_pressure"})
    rules = [rule({"metric": "book_pressure", "params": {"n": 20}}, symbols=("BTCUSDT",))]
    async with Rig(rules, pressure) as rig:
        assert pressure.sink is not None
        sink = pressure.sink
        assert sink.push_metric(
            "book_pressure", "BTCUSDT", Decimal("0.5"), TS, 100, params={"n": 20}
        )
        assert not sink.push_metric("book_pressure", "BTCUSDT", None, TS, 100, params={"n": 5})
        assert rig.refused("undemanded") == 0  # an uncomputable value is no refusal
        got = rig.source.read(ref("book_pressure", params={"n": 20}, symbol="BTCUSDT"))
        assert got.value == Decimal("0.5")


async def test_push_sink_undeclared_registry_metric_is_refused_as_unregistered() -> None:
    ticker, quote = Producer("ticker", {"price"}, {"ticker"}), Producer("quote", {"mid"})
    async with Rig([_price_rule()], ticker, quote) as rig:
        assert ticker.sink is not None and quote.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        assert not quote.sink.push(want, "BTCUSDT", Decimal(1), TS, 100)  # not quote's metric
        assert rig.refused("unregistered") == 1 and rig.source._values == {}


async def test_bridge_any_symbol_want_narrowed_keeps_only_the_listed_symbols() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=())], ticker) as rig:
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        for symbol in ("BTCUSDT", "SOLUSDT"):
            ticker.sink.push(want, symbol, Decimal(1), TS, 250)
        rig.items[0] = EvaluableRule(_price_rule(symbols=("BTCUSDT",)), "simulate", None, "v", "h")
        await rig.bridge.refresh()
        (narrowed,) = ticker.sink.wanted("price", "BTCUSDT")
        assert set(narrowed.lives) == {"BTCUSDT"} and rig.bridge.lives == 1
        assert rig.source.read(ref("price", symbol="SOLUSDT")).reason == "warmup"


def test_producer_metrics_unbound_counts_nothing_and_checks_its_closed_set() -> None:
    unbound = ProducerMetrics()
    unbound.pushed("price", 3)
    unbound.error("quote")
    unbound.refused("lease")
    unbound.in_warmup(1)
    outside: Any = "outside"
    with pytest.raises(ValueError, match="closed set"):
        unbound.refused(outside)


# --- review fold (#5745 PR 2) ------------------------------------------------------------------


async def test_watchdog_warmup_gauge_and_demand_skip_metrics_no_producer_binds() -> None:
    """A rule over an unsourced metric neither takes a demand slot nor holds the gauge up."""
    ticker = Producer("ticker", {"price"}, {"ticker"})
    rules = [_price_rule(symbols=("BTCUSDT",)), rule({"metric": "mid"}, rid=2)]
    async with Rig(rules, ticker) as rig:
        assert set(rig.bridge.demand.by_metric) == {"price"} and rig.bridge.demand.size == 1
        await _pushed_price(rig, ticker)
        rig.clock.t += WARMUP_ALERT_S + 1
        rig.bridge.watch()
        assert rig.sample("rule_metrics_in_warmup") == 0


async def test_bridge_refresh_a_rule_the_demand_cannot_read_keeps_the_last_demand() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule()], ticker) as rig:
        before = rig.bridge.demand
        rig.items.append(SimpleNamespace(rule=object()))  # type: ignore[arg-type]  # a bad item
        with capture_logs() as logs:
            await rig.bridge.refresh()  # never raises: the refresh loop lives on
        assert rig.bridge.demand is before
        assert [(e["event"], e["error"]) for e in logs] == [
            ("rules.producer_demand_failed", "AttributeError")
        ]


async def test_push_sink_guard_window_logs_one_symbol_failing_beside_healthy_ones_once() -> None:
    quote = Producer("quote", {"mid"})
    async with Rig([], quote) as rig:
        sink = quote.sink
        assert sink is not None

        def boom() -> None:
            raise ValueError("x")

        with capture_logs() as logs:
            for _ in range(5):  # symbol A raises, symbol B succeeds, every window
                with sink.window():
                    sink.guard(boom)
                    assert sink.guard(lambda: 1) == 1
        assert [e["event"] for e in logs] == ["rules.producer_failed"]
        assert rig.sample("rule_metric_producer_errors_total", producer="quote") == 5
        with sink.window():  # a clean window ends the episode
            sink.guard(lambda: 1)
        with capture_logs() as again:
            sink.guard(boom)
        assert [e["event"] for e in again] == ["rules.producer_failed"]


async def test_any_symbol_keys_never_starve_the_listed_symbols_of_other_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(producers_mod, "MAX_DEMAND_REFS", 4)
    ticker, quote = Producer("ticker", {"price"}, {"ticker"}), Producer("quote", {"mid"})
    rules = [_price_rule(symbols=()), rule({"metric": "mid"}, symbols=("BTCUSDT",), rid=2)]
    async with Rig(rules, ticker, quote) as rig:
        assert ticker.sink is not None and quote.sink is not None
        (price,) = ticker.sink.wanted("price", "SYM0USDT")
        pushed = [ticker.sink.push(price, f"SYM{i}USDT", Decimal(1), TS, 250) for i in range(5)]
        assert pushed == [True, True, True, False, False]  # 4 less the one listed `mid` ref
        (mid,) = quote.sink.wanted("mid", "BTCUSDT")
        assert quote.sink.push(mid, "BTCUSDT", Decimal(2), TS, 100)  # never starved
        assert rig.refused("demand_cap") == 2
        eth_rule = rule({"metric": "mid"}, symbols=("ETHUSDT",), rid=3)
        rig.items.append(EvaluableRule(eth_rule, "simulate", None, "v", "h"))  # a listed ref more
        await rig.bridge.refresh()
        (eth,) = quote.sink.wanted("mid", "ETHUSDT")
        assert quote.sink.push(eth, "ETHUSDT", Decimal(3), TS, 100)
        assert (rig.bridge.lives, rig.bridge.any_lives) == (4, 2)
        assert len(rig.source._values) == 4 and rig.refused("demand_cap") == 3
        assert (
            rig.source.read(ref("price", symbol="SYM2USDT")).reason == "warmup"
        )  # the last one out


async def test_watchdog_quiet_symbol_its_producer_still_holds_is_not_marked() -> None:
    held: set[str] = {"BTCUSDT"}
    ticker = Producer("ticker", {"price"}, {"ticker"})
    ticker.holds = held.__contains__  # type: ignore[attr-defined]  # pushes on a change only
    async with Rig([_price_rule(symbols=("BTCUSDT",))], ticker) as rig:
        await _pushed_price(rig, ticker)
        rig.clock.t += LOST_AFTER_S + 1  # quiet but healthy
        assert rig.bridge.watch() == 0
        assert rig.source.read(ref("price", symbol="BTCUSDT")).value == Decimal(1)
        held.clear()  # the producer lost its latest (stopped, invalidated): lost after the bound
        rig.clock.t += LOST_AFTER_S
        assert rig.bridge.watch() == 1


# --- slice review fold (#5745 PR 2a) -----------------------------------------------------------


async def test_feed_mark_inside_the_stale_bound_skips_a_none_of_rule_and_disarms_an_alert() -> None:
    """The mark reads stale at once: a `none_of` rule skips (it would fire on the None), and the
    alert evaluator, which reads the lost reason before staleness, still disarms loudly."""
    ticker = Producer("ticker", {"price"}, {"ticker"})
    base = _price_rule(symbols=("BTCUSDT",)).model_dump(mode="json")
    base["conditions"] = {"node_id": "root", "op": "none_of", "children": [base["conditions"]]}
    left = {"metric": "price", "symbol": "BTCUSDT"}
    store = FakeStore(row("a1", condition_ir=ir() | {"conditions": {
        "node_id": "c1", "op": "gt", "left": left, "right": {"const": 100}}}))  # fmt: skip
    async with Rig([Rule.model_validate(base)], ticker) as rig:
        alerts = AlertEvaluator(store, rig.source, owners=allow(), metrics=AlertMetrics(
            AlertCounters()), storm=StormSuppressor(), clock=AlertClock(NOW))  # fmt: skip
        await alerts.warm_up()
        assert ticker.sink is not None
        (want,) = ticker.sink.wanted("price", "BTCUSDT")
        assert ticker.sink.push(want, "BTCUSDT", Decimal(150), NOW - 1_000, 250)
        assert rig.bridge.feed_degraded("BTCUSDT", "ticker") == 1  # 1 s after the push
        result = evaluator(Rule.model_validate(base), rig.source).on_trigger(
            "BTCUSDT@*", "on_price_update"
        )
        assert not result.fired and result.skipped_reason == "stale_data"
        await alerts.process(AlertTick("on_price_update", NOW, "BTCUSDT"))
        assert not store.rows["a1"].enabled
        assert store.deliveries[-1].context["reason"] == "source_unavailable"


async def test_watchdog_raising_holds_is_isolated_and_counts_as_not_held() -> None:
    bad, good = Producer("bad", {"mid"}), Producer("good", {"price"}, {"ticker"})
    bad.holds = lambda _s: 1 // 0  # type: ignore[attr-defined]  # a faulty producer hook
    good.holds = lambda _s: False  # type: ignore[attr-defined]
    async with Rig([_price_rule(), rule({"metric": "mid"}, rid=2)], bad, good) as rig:
        assert bad.sink is not None and good.sink is not None
        (mid,) = bad.sink.wanted("mid", "BTCUSDT")
        assert bad.sink.push(mid, "BTCUSDT", Decimal(1), TS, 100)
        await _pushed_price(rig, good)
        rig.clock.t += LOST_AFTER_S
        with capture_logs() as logs:
            assert rig.bridge.watch() == 2  # the healthy producer's silent ref is still marked
        assert [e["event"] for e in logs] == ["rules.producer_failed", "rules.metric_source_lost"]
        assert logs[1]["refs"] == 2 and logs[1]["producers"] == ["bad", "good"]


async def test_feed_degraded_socket_wide_logs_one_line_for_every_ref_it_marks() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    rules = [_price_rule(symbols=tuple(f"S{i}USDT" for i in range(50)))]
    async with Rig(rules, ticker) as rig:
        assert ticker.sink is not None
        for i in range(50):
            (want,) = ticker.sink.wanted("price", f"S{i}USDT")
            ticker.sink.push(want, f"S{i}USDT", Decimal(1), TS, 250)
        with capture_logs() as logs:
            assert rig.bridge.feed_degraded(None, "ticker") == 50
            assert rig.bridge.feed_degraded(None, "ticker") == 0
        assert [(e["event"], e["refs"]) for e in logs] == [("rules.metric_source_lost", 50)]


class _Hanging(Producer):
    async def detach(self) -> None:
        self.detached = True
        await asyncio.Event().wait()


def _bridge_tasks() -> list[asyncio.Task[Any]]:
    return [t for t in asyncio.all_tasks() if t.get_name().startswith("rule-producers-")]


async def test_bridge_detach_bounds_a_hung_producer_and_stops_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(producers_mod, "DETACH_S", 0)
    hung, good = _Hanging("hung", {"mid"}), Producer("good", {"price"})
    async with asyncio.timeout(5):  # a guard: an unbounded detach fails rather than hangs
        async with Rig([], hung, good) as rig:
            pass
    assert hung.detached and good.detached and rig.bridge.source is None
    assert rig.sample("rule_metric_producer_errors_total", producer="hung") == 1
    assert _bridge_tasks() == []


async def test_bridge_detach_cancelled_midway_still_stops_its_timers() -> None:
    hung = _Hanging("hung", {"mid"})
    rig = Rig([], hung)
    await rig.__aenter__()
    assert len(_bridge_tasks()) == 2
    stopping = asyncio.create_task(rig.bridge.detach())
    assert await _until(lambda: hung.detached)
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert _bridge_tasks() == [] and rig.bridge.source is None


async def test_watchdog_warmup_counts_a_newly_listed_symbol_from_when_it_was_listed() -> None:
    ticker = Producer("ticker", {"price"}, {"ticker"})
    async with Rig([_price_rule(symbols=("BTCUSDT",))], ticker) as rig:
        rig.clock.t += WARMUP_ALERT_S + 1
        rig.items[0] = EvaluableRule(_price_rule(), "simulate", None, "v2", "h")  # + ETHUSDT
        await rig.bridge.refresh()
        rig.bridge.watch()
        assert rig.sample("rule_metrics_in_warmup") == 1  # BTCUSDT only: ETHUSDT just listed
        rig.clock.t += WARMUP_ALERT_S + 1
        rig.bridge.watch()
        assert rig.sample("rule_metrics_in_warmup") == 2
