"""E35-T13 (#5005) slice 4a: the signal bus (24 §11.5 "Signals"; RE-S3, RE-D7; BQ-3 to BQ-5).

The chain and owner scenarios run through `EngineRig`: a `RulesService` whose runner is driven by
hand, so each signal is evaluated as the runner's task would evaluate it, then settled. A chain of
`on_signal` rules relaying each other's signals is refused at save (`feedback_loop`), so those
rules are stored past the validator, as a version saved before that check would be (BQ-4): the
depth limit is the runtime's second fence. No sleeps: every wait is an event under a bound.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules.evaluator import Evaluator, SnapshotBuilder
from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.executor.signals import (
    KEYS_REMEMBERED,
    EmitSignalHandler,
    Signal,
    SignalBus,
)
from candleviewer.rules.ir.models import Action, Rule, RuleScope
from candleviewer.rules.limits import (
    SIGNAL_MAX_DEPTH_CAP,
    SIGNAL_MAX_DEPTH_DEFAULT,
    SIGNAL_QUEUE_BOUND,
)
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules.runner import EvalTick, PushedMetricSource, RuleEvaluationRunner
from candleviewer.rules.scope import ScopeInstanceRef
from tests.rules.executor.engine_rig import OTHER, EngineRig, emit, engine, set_var
from tests.rules.executor.request_builders import Counted, action_request
from tests.rules.test_scope_wiring import OWNER

__all__ = ["engine"]  # the rig's fixture, used by name

GUARD_S = 5.0


def _signal(depth: int = 1, key: str = "k1", owner: uuid.UUID = OWNER) -> Signal:
    return Signal(owner=owner, name="go", payload={}, depth=depth, rule_id="r1", dedupe_key=key)


def _emit_request(depth: int = 0, **params: Any) -> Any:
    action = Action.model_validate(
        {"node_id": "a1", "type": "emit_signal", "params": {"signal_name": "go", **params}}
    )
    instance = ScopeInstanceRef("*@*", None, None)
    return action_request(
        RuleScope(level="account"), OWNER, instance, action_type="emit_signal", payload=action,
        signal_depth=depth,
    )  # fmt: skip


def _truncations(logs: list[Any]) -> list[int]:
    return [e["depth"] for e in logs if e["event"] == "rules.signal_chain_truncated"]


async def test_signal_chains_are_bounded(engine: EngineRig) -> None:
    """Scenario: Signal chains are bounded (parent Gherkin 8, failure case). Rule A emits a signal
    that triggers rule B, which emits a signal that triggers rule A, a market rule starting the
    chain. With no name filter yet (BQ-3), each of the owner's signals triggers both, so the chain
    fans out; it stops at the depth limit (default 3): no signal deeper than 3 is enqueued, each
    cut is logged as an error and counted in `rule_signal_chain_truncated_total`, its action
    `failed`, and neither rule loops. The depth increments on every hop."""
    assert SIGNAL_MAX_DEPTH_DEFAULT == 3
    await engine.add(actions=[emit("s1")])  # the market rule: its signal has depth 1
    a = await engine.add(actions=[emit("a1", "to-b")], trigger="on_signal")
    b = await engine.add(actions=[emit("b1", "to-a")], trigger="on_signal")
    with capture_logs() as logs:
        await engine.fire()
        depths = await engine.drain()
    assert depths == [1, 2, 2, 3, 3, 3, 3]  # each hop one deeper: 1 signal, then 2, then 4
    assert engine.bus.waiting == 0  # the chain ended
    assert _truncations(logs) == [4] * 8  # the 8 relays of the depth-3 signals, each cut
    assert engine.counted.of("rule_signal_chain_truncated_total") == {(): 8.0}
    for rid in (a, b):
        results = engine.results(rid)
        assert len(results) == 7  # one fire per signal of depth 1 to 3, never more
        cut = [r for r in results if r[1] == "failed"]
        assert cut == [("emit_signal", "failed", "signal_chain_truncated")] * 4


async def test_signal_never_crosses_owner_boundary(engine: EngineRig) -> None:
    """Scenario: A signal never crosses an owner boundary (RE-S3). The cross-owner case: another
    owner's `on_signal` rule, whose condition holds, never evaluates on this owner's signal, while
    the emitting owner's own listener does; an `on_signal` tick that carries no signal reaches
    neither."""
    await engine.add(actions=[emit("s1")])
    mine = await engine.add(actions=[set_var("v1", "seen")], trigger="on_signal")
    theirs = await engine.add(actions=[set_var("v1", "seen")], trigger="on_signal", owner=OTHER)
    await engine.fire()
    assert await engine.drain() == [1]
    assert engine.results(mine) == [("set_variable", "ok", None)]
    assert engine.results(theirs) == []  # never evaluated: no fire, no run
    assert engine.svc._variables.get(theirs, "seen") is None
    await engine.runner.process(EvalTick("on_signal"))  # no signal: no owner to deliver to
    await engine.settle()
    assert engine.results(mine) == [("set_variable", "ok", None)]


async def test_signal_depth_increments_per_hop(engine: EngineRig) -> None:
    """One relaying rule: the market rule's signal has depth 1, and each relay of it one more, until
    the relay of depth 3 is cut at the limit; each fire carries the depth that caused it."""
    await engine.add(actions=[emit("s1")])
    relay = await engine.add(actions=[emit("r1")], trigger="on_signal")
    with capture_logs() as logs:
        await engine.fire()
        assert await engine.drain() == [1, 2, 3]
    assert _truncations(logs) == [4]
    assert [r[1:] for r in engine.results(relay)] == [
        ("ok", None), ("ok", None), ("failed", "signal_chain_truncated"),
    ]  # fmt: skip
    handler = EmitSignalHandler(SignalBus())
    for depth in (0, 1, 2):
        signal = handler.prepare(_emit_request(depth), None, max_notional_usd=None).request[
            "signal"
        ]
        assert signal.depth == depth + 1 and signal.owner == OWNER


async def test_emit_signal_never_awaits_on_the_tick(engine: EngineRig) -> None:
    """Scenario: Emitting a signal never waits on the tick. The market tick only offers its fire;
    the `emit_signal` action runs in the dispatch worker, where the bus takes the signal without
    awaiting (a synchronous `offer`), and the action is `ok` while the signal still waits: no
    delivery is awaited, by the tick or by the action."""
    assert not inspect.iscoroutinefunction(SignalBus.offer)
    await engine.add(actions=[emit("s1")])
    listener = await engine.add(actions=[set_var("v1", "seen")], trigger="on_signal")
    await engine.fire()  # the tick returns once the fire is offered
    await engine.settle()
    assert engine.results() == [("emit_signal", "ok", None)] and engine.bus.waiting == 1
    assert engine.results(listener) == []  # not delivered yet: the emit never waited for it
    assert await engine.drain() == [1]
    assert engine.results(listener) == [("set_variable", "ok", None)]


async def test_a_signal_burst_past_the_queue_bound_is_refused_and_counted() -> None:
    """BQ-5: the newest signal past the bound is refused, never one waiting, counted in
    `rule_signal_dropped_total` and logged once per episode, which ends when the queue next runs
    empty; the handler answers it `failed` (`signal_queue_full`) at once, never awaiting room."""
    assert SIGNAL_QUEUE_BOUND == 256
    counted = Counted()
    bus = SignalBus(bound=2, metrics=counted.metrics)
    with capture_logs() as logs:
        assert [bus.offer(_signal(key=k)) for k in ("k1", "k2", "k3", "k4")] == [
            "queued", "queued", "full", "full",
        ]  # fmt: skip
        assert [_named(EvalTick("on_signal", signal=bus.take())) for _ in "12"] == ["k1", "k2"]
        assert bus.take() is None and bus.offer(_signal(key="k5")) == "queued"
        assert bus.offer(_signal(key="k6")) == "queued"
        handler = EmitSignalHandler(bus)
        prepared = handler.prepare(_emit_request(), None, max_notional_usd=None)
        async with asyncio.timeout(GUARD_S):  # a refusal, never a wait for room
            answer = await handler.send(prepared, client_ref="k7")
    assert (answer.answer, answer.error_code) == ("refused", "signal_queue_full")
    assert counted.of("rule_signal_dropped_total") == {(): 3.0}
    dropped = [e for e in logs if e["event"] == "rules.signal_dropped"]
    assert len(dropped) == 2 and all(e["log_level"] == "warning" for e in dropped)


async def test_a_repeated_fire_key_reaches_the_bus_once() -> None:
    """`fire_key_signal_depth`: a repeat of an action's key is enqueued once, its answer `ok`."""
    bus = SignalBus()
    handler = EmitSignalHandler(bus)
    prepared = handler.prepare(_emit_request(), None, max_notional_usd=None)
    first = await handler.send(prepared, client_ref="key")
    again = await handler.send(prepared, client_ref="key")
    assert (first.answer, again.answer, bus.waiting) == ("done", "done", 1)
    assert bus.offer(_signal(key="key")) == "repeat"
    roomy = SignalBus(bound=KEYS_REMEMBERED + 2)  # the memory is bounded: the oldest key goes
    for n in range(KEYS_REMEMBERED + 1):
        assert roomy.offer(_signal(key=f"k{n}")) == "queued"
    assert (roomy.offer(_signal(key="k1")), roomy.offer(_signal(key="k0"))) == ("repeat", "queued")


@pytest.mark.parametrize(
    "params", [{"signal_name": ""}, {"signal_name": 7}, {"payload": [1]}], ids=str
)
async def test_an_emit_signal_with_mistyped_params_fails(params: dict[str, Any]) -> None:
    handler = EmitSignalHandler(SignalBus())
    prepared = handler.prepare(_emit_request(**params), None, max_notional_usd=None)
    answer = await handler.send(prepared, client_ref="k")
    assert (answer.answer, answer.error_code) == ("refused", "invalid_params")


async def test_the_runner_takes_signals_and_market_ticks_in_turn() -> None:
    """24 §11.5: a waiting signal and a market tick in turn, so neither queue starves the other;
    one alone is taken whenever the other is empty, and a signal wakes the runner's task."""
    bus = SignalBus()
    runner = _Runner(bus)
    for symbol in ("A", "B"):
        runner.submit(EvalTick("on_price_update", symbol))
    for key in ("k1", "k2", "k3"):
        bus.offer(_signal(key=key))
    taken = [runner._pick() for _ in range(6)]
    assert [_named(t) for t in taken] == ["k1", "A", "k2", "B", "k3", None]
    runner.start()
    try:
        bus.offer(_signal(key="k4"))
        async with asyncio.timeout(GUARD_S):
            await runner.processed_one.wait()
    finally:
        await runner.stop()
    assert [_named(t) for t in runner.seen] == ["k4"]


def _named(tick: EvalTick | None) -> str | None:
    """A market tick by its symbol, a signal's by its key."""
    if tick is None:
        return None
    return tick.signal.dedupe_key if tick.signal is not None else tick.symbol


class _Runner(RuleEvaluationRunner):
    """The runner with `process` recorded: no rule is evaluated."""

    def __init__(self, bus: SignalBus) -> None:
        super().__init__(_no_rules, SnapshotBuilder(PushedMetricSource()), _never, _discard,
                         signals=bus)  # fmt: skip
        self.seen: list[EvalTick] = []
        self.processed_one = asyncio.Event()

    async def process(self, tick: EvalTick) -> None:
        self.seen.append(tick)
        self.processed_one.set()


async def _no_rules() -> list[EvaluableRule]:
    return []


def _never(_rule: Rule, _snapshots: SnapshotBuilder) -> Evaluator:
    raise AssertionError("no rule is evaluated here")


def _discard(_result: EvaluationResult) -> None:
    raise AssertionError("no result is made here")


def test_a_depth_setting_above_its_cap_refuses_start() -> None:
    """BQ-5: `CV_RULES_SIGNAL_MAX_DEPTH` above the hard cap of 3 (interim, pending the owner's
    ratification, #2701) refuses start, whatever `rules_evaluator_enabled` says; the cap lives in
    `rules.limits` alone."""
    from candleviewer import rules_oms_wiring
    from candleviewer.app import create_app
    from candleviewer.settings import Settings

    assert (SIGNAL_MAX_DEPTH_CAP, SIGNAL_MAX_DEPTH_DEFAULT) == (3, 3)
    assert Settings().rules_signal_max_depth == 3
    assert [rules_oms_wiring.rule_signal_depth(d) for d in (1, 3)] == [1, 3]
    with pytest.raises(rules_oms_wiring.SignalDepthAboveCap, match="DEPTH is above"):
        rules_oms_wiring.rule_signal_depth(4)
    settings = Settings(rules_signal_max_depth=4)
    assert settings.rules_evaluator_enabled is False
    with pytest.raises(rules_oms_wiring.SignalDepthAboveCap):
        create_app(settings)


async def test_a_stop_drops_the_waiting_signals(engine: EngineRig) -> None:
    """Signals live in memory: a stop drops the waiting ones, as it drops queued fires, and says how
    many."""
    await engine.add(actions=[emit("s1")])
    await engine.fire()
    await engine.settle()
    bus = engine.bus
    assert bus.waiting == 1
    with capture_logs() as logs:
        await engine.svc.stop(1.0)
    assert bus.waiting == 0 and engine.svc._signals is None
    assert [e["dropped"] for e in logs if e["event"] == "rules.signals_dropped_at_stop"] == [1]
