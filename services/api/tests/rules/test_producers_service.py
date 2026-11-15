"""E35-T15 PR 2: the bridge's lifecycle in `RulesService` and the vocabulary's producer marking."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.rules.manager import EvaluableRule, InMemoryRuleStore
from candleviewer.rules.producers import ProducerBridge, PushSink
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules.vocabulary.build import PRODUCER_GAP_REASON, build_vocabulary, etag_for
from candleviewer.settings import Settings
from tests.rules.test_instance_binding import SCOPES


class Fake:
    name = "fake"
    metrics = frozenset({"price"})
    feeds = frozenset({"ticker"})

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def attach(self, sink: PushSink) -> None:
        self.events.append("attach")

    async def detach(self) -> None:
        self.events.append("detach")


async def _no_hook(*_args: Any) -> None:
    """No audit backend or bus in these rigs."""


async def _none() -> list[EvaluableRule]:
    return []


def _rig(*, enabled: bool = True) -> tuple[Any, ProducerBridge, list[str]]:
    events: list[str] = []
    bridge = ProducerBridge(_none, SCOPES)
    bridge.add(Fake(events))
    ctx = create_app(Settings(rules_evaluator_enabled=enabled)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore(), audit=_no_hook, broadcast=_no_hook, producers=bridge)
    return ctx, bridge, events


async def test_service_start_attaches_the_bridge_after_the_runner_runs() -> None:
    ctx, bridge, events = _rig()
    await ctx.rules.start(ctx)
    try:
        assert events == ["attach"]
        assert bridge.source is ctx.rules.metric_source and ctx.rules.runner is not None
        assert bridge.submit == ctx.rules.submit_tick
        assert bridge.submit is not None
        assert bridge.submit("on_bar_close", None, None) is True  # the runner exists: not dropped
    finally:
        await ctx.rules.stop(1.0)


async def test_service_stop_detaches_the_bridge_before_the_runner_stops() -> None:
    ctx, bridge, events = _rig()
    await ctx.rules.start(ctx)
    runner = ctx.rules.runner
    assert runner is not None
    seen: list[bool] = []
    real_stop = runner.stop

    async def _stop() -> None:
        seen.append(bridge.source is None)  # detached already when the runner stops
        await real_stop()

    runner.stop = _stop  # test seam: observe the order
    await ctx.rules.stop(1.0)
    assert events == ["attach", "detach"] and seen == [True]


async def test_service_start_survives_a_bridge_attach_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, bridge, _ = _rig()

    def _boom(*_args: Any) -> None:
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(bridge, "attach", _boom)  # an attach that raises
    with capture_logs() as logs:
        await ctx.rules.start(ctx)
    try:
        assert ctx.rules.runner is not None  # the runner runs on; the metrics stay warmup
        failed = [e for e in logs if e["event"] == "rules.producers_attach_failed"]
        assert [e["error"] for e in failed] == ["RuntimeError"]
    finally:
        await ctx.rules.stop(1.0)


async def test_service_evaluator_off_never_attaches_the_bridge() -> None:
    ctx, bridge, events = _rig(enabled=False)
    await ctx.rules.start(ctx)
    try:
        assert events == [] and bridge.source is None
        assert ctx.rules.producer_gaps() is None
    finally:
        await ctx.rules.stop(1.0)


async def test_service_rules_broadcast_wakes_the_demand_refresh() -> None:
    ctx, bridge, _ = _rig()
    await ctx.rules.start(ctx)
    try:
        pokes: list[int] = []
        bridge.poke = lambda: pokes.append(1)  # type: ignore[method-assign]  # a public spy
        manager = ctx.rules.manager()
        assert manager is not None
        await manager._bc({"topic": "rules"})
        assert pokes == [1]
    finally:
        await ctx.rules.stop(1.0)


async def test_service_rules_broadcast_failure_still_wakes_the_demand_refresh() -> None:
    async def _down(_payload: dict[str, Any]) -> None:
        raise ConnectionError("ws down")

    events: list[str] = []
    bridge = ProducerBridge(_none, SCOPES)
    bridge.add(Fake(events))
    ctx = create_app(Settings(rules_evaluator_enabled=True)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore(), audit=_no_hook, broadcast=_down, producers=bridge)
    await ctx.rules.start(ctx)
    try:
        pokes: list[int] = []
        bridge.poke = lambda: pokes.append(1)  # type: ignore[method-assign]  # a public spy
        manager = ctx.rules.manager()
        assert manager is not None
        with pytest.raises(ConnectionError):
            await manager._bc({"topic": "rules"})
        assert pokes == [1]
    finally:
        await ctx.rules.stop(1.0)


async def test_service_producer_gaps_follow_the_attach_state() -> None:
    ctx, _, _ = _rig()
    assert ctx.rules.producer_gaps() is None
    await ctx.rules.start(ctx)
    try:
        gaps = ctx.rules.producer_gaps()
        assert gaps == frozenset(SCOPES) - {"price"}
    finally:
        await ctx.rules.stop(1.0)
    assert ctx.rules.producer_gaps() is None
    await asyncio.sleep(0)


def _by(**kw: Any) -> dict[str, Any]:
    return {s["id"]: s for s in build_vocabulary(default_registry(), **kw)["signals"]}


def test_vocabulary_producer_gap_marks_the_metric_unavailable() -> None:
    by = _by(producer_gaps=frozenset({"spread_ticks"}))
    s = by["spread_ticks"]
    assert s["available"] is False and s["unavailable_reason"] == PRODUCER_GAP_REASON
    assert s["missing_dependency"] == {"kind": "producer"}
    assert PRODUCER_GAP_REASON == "No live data source yet."
    assert by["price"]["available"] is True


def test_vocabulary_producer_gap_wins_over_recording_and_drops_the_recorder_action() -> None:
    by = _by(
        symbol="DOGEUSDT", recorded_symbols={"BTCUSDT"}, producer_gaps=frozenset({"tape_speed"})
    )
    s = by["tape_speed"]
    assert s["missing_dependency"] == {"kind": "producer"} and "recorder_action" not in s
    assert s["unavailable_reason"] == PRODUCER_GAP_REASON


def test_vocabulary_without_a_bridge_marks_nothing_as_a_producer_gap() -> None:
    assert all(
        s.get("missing_dependency", {}).get("kind") != "producer"
        for s in build_vocabulary(default_registry(), producer_gaps=None)["signals"]
    )
    assert build_vocabulary(default_registry()) == build_vocabulary(
        default_registry(), producer_gaps=None
    )


def test_vocabulary_etag_varies_with_the_producer_marking() -> None:
    plain = build_vocabulary(default_registry())
    marked = build_vocabulary(default_registry(), producer_gaps=frozenset({"price"}))
    assert etag_for(plain, set(), None) != etag_for(marked, set(), None)


def test_vocabulary_route_marks_gaps_while_a_bridge_is_attached_and_the_etag_follows() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.api.rules import make_rules_router
    from tests.rules._check_limiter import unthrottled
    from tests.rules.test_vocabulary import _P, _Resolver

    gaps: list[frozenset[str] | None] = [None]
    app = FastAPI()
    app.include_router(
        make_rules_router(
            default_registry,
            principal_resolver=_Resolver(_P("rules:read")),
            check_limiter=unthrottled(),
            producer_gaps=lambda: gaps[0],
        )
    )
    client = TestClient(app)
    off = client.get("/rules/vocabulary")
    gaps[0] = frozenset({"price"})
    on = client.get("/rules/vocabulary", headers={"If-None-Match": off.headers["etag"]})
    assert on.status_code == 200 and on.headers["etag"] != off.headers["etag"]
    assert {s["id"]: s for s in on.json()["signals"]}["price"]["missing_dependency"] == {
        "kind": "producer"
    }
