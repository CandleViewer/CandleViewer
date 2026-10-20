"""tests/xstate_contract/test_plugins.py — E50-T60 plugin contract tests.

Gherkin:
  1. chain trip observed on both lanes (hook + `cv_machine_chain_trips_total`;
     supervisors read `chain_trips`, never `last_error`);
  2. dropped receipt pages (counter + alert);
  3. audit is write-ahead (the `ahead` row exists before the action body runs).
Run with `-W error::RuntimeWarning` (the drop-receipt case filters its own
expected finaliser warning locally).
"""

from __future__ import annotations

import asyncio
import gc
import warnings
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import generate_latest
from xstate_statemachine import SimulatedClock

from candleviewer.observability.metrics import Metrics
from candleviewer.statechart import build
from candleviewer.statechart.config import Lane
from candleviewer.statechart.plugins import (
    CvAuditPlugin,
    CvErrorHooks,
    CvMetricsPlugin,
    InMemoryMachineEventSink,
    cv_plugins,
)
from candleviewer.statechart.plugins.audit import verify_chain
from candleviewer.statechart.registry import Registry
from tests.xstate_contract.plugin_fixtures import binding_plugins
from tests.xstate_contract.plugin_fixtures.binding_plugins import PROBE

KIND = "test.plugins_min"


class _Pager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.calls.append((severity, summary))


@pytest.fixture()
def registry() -> Registry:
    return Registry(machines_dir=Path(__file__).resolve().parent / "plugin_fixtures")


async def _build(
    registry: Registry, lane: Lane, *, write_ahead: bool = True
) -> tuple[
    Any, CvErrorHooks, CvMetricsPlugin, CvAuditPlugin, InMemoryMachineEventSink, Metrics, _Pager
]:
    pager = _Pager()
    metrics = Metrics("dev")
    sink = InMemoryMachineEventSink()
    plugins = cv_plugins(
        machine_kind=KIND,
        lane=lane,
        entity_id="00000000-0000-0000-0000-000000000001",
        env="dev",
        metrics=metrics,
        sink=sink,
        pager=pager,
        write_ahead=write_ahead,
    )
    err, met, aud = plugins
    res = await build(KIND, clock=SimulatedClock(), lane=lane, plugins=plugins, registry=registry)
    return res.interpreter, err, met, aud, sink, metrics, pager


def _sample(metrics: Metrics, name: str) -> float:
    text = generate_latest(metrics.registry).decode()
    total = 0.0
    for line in text.splitlines():
        if line.startswith(name + "{") and f'kind="{KIND}"' in line:
            total += float(line.rsplit(" ", 1)[1])
    return total


async def _settle(interp: Any) -> None:
    for _ in range(20):
        await asyncio.sleep(0)


@pytest.mark.parametrize("lane", ["order", "control", "platform"])
async def test_chain_trip_observed_and_counted(registry: Registry, lane: Lane) -> None:
    interp, err, _met, _aud, _sink, metrics, pager = await _build(registry, lane)
    try:
        interp.send("PING")
        await _settle(interp)
        assert interp.chain_trips == 1
        assert err.chain_trips == 1
        assert _sample(metrics, "cv_machine_chain_trips_total") == 1.0
        assert any(sev == "page" for sev, _ in pager.calls)
    finally:
        await interp.stop()


async def test_dropped_receipt_increments_and_alerts(registry: Registry) -> None:
    interp, err, _met, _aud, _sink, metrics, pager = await _build(registry, "platform")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            interp.send("DROP")
            await _settle(interp)
            gc.collect()
        assert interp.dropped_receipts >= 1
        assert err.dropped_receipts == interp.dropped_receipts
        assert _sample(metrics, "cv_machine_dropped_receipts_total") == interp.dropped_receipts
        assert ("alert", "send(wait=True) receipt dropped: NOOP") in pager.calls
    finally:
        await interp.stop()


async def test_audit_is_write_ahead(registry: Registry) -> None:
    interp, _err, _met, _aud, sink, _metrics, _pager = await _build(registry, "order")
    PROBE["sink"], PROBE["seen"] = sink, []
    try:
        interp.send("GO")
        await _settle(interp)
        (seen,) = PROBE["seen"]
        assert seen[-1].phase == "ahead" and seen[-1].event_type == "GO"
        commit = sink.rows[-1]
        assert commit.phase == "commit" and commit.actions_run == ["probe"]
        assert "test.plugins_min.busy" in commit.to_states
        assert verify_chain(sink.rows)
    finally:
        PROBE["sink"] = None
        await interp.stop()


async def test_audit_write_behind_has_no_ahead_rows(registry: Registry) -> None:
    interp, _err, _met, _aud, sink, _metrics, _pager = await _build(
        registry, "platform", write_ahead=False
    )
    try:
        interp.send("GO")
        await _settle(interp)
        assert [r.phase for r in sink.rows] == ["commit", "commit"]
    finally:
        await interp.stop()


async def test_failed_transition_writes_fault_row_and_pages(registry: Registry) -> None:
    interp, err, _met, _aud, sink, _metrics, pager = await _build(registry, "order")
    try:
        interp.send("FAIL")
        await _settle(interp)
        assert err.transition_failures == 1
        fault = sink.rows[-1]
        assert fault.phase == "fault"
        assert fault.fault == {"failed": [{"action": "boom", "error": "RuntimeError"}]}
        assert verify_chain(sink.rows)
        assert any(sev == "page" for sev, _ in pager.calls)
    finally:
        await interp.stop()


async def test_transitions_and_timer_handles_scraped(registry: Registry) -> None:
    interp, _err, met, _aud, _sink, metrics, _pager = await _build(registry, "platform")
    try:
        interp.send("GO")
        await _settle(interp)
        assert _sample(metrics, "cv_machine_transitions_total") == 1.0
        assert _sample(metrics, "cv_machine_timer_handles") == 1.0
        met.record_send_refused("queue_full")
        assert _sample(metrics, "cv_machine_send_refused_total") == 1.0
    finally:
        await interp.stop()


def test_binding_module_registered() -> None:
    assert binding_plugins.ACTIONS


class _BrokenSink:
    def append(self, row: object) -> None:
        raise OSError("disk gone")


async def test_hooks_never_raise_into_interpreter(registry: Registry) -> None:
    """A failing sink is logged + counted; the machine keeps running."""
    aud = CvAuditPlugin(
        machine_kind=KIND, entity_id="e", env="dev", sink=_BrokenSink(), write_ahead=True
    )
    res = await build(KIND, clock=SimulatedClock(), lane="order", plugins=(aud,), registry=registry)
    interp = res.interpreter
    try:
        interp.send("GO")
        await _settle(interp)
        assert "test.plugins_min.busy" in interp.current_state_ids
        assert aud.sink_failures >= 1 and aud.hook_errors >= 1
    finally:
        await interp.stop()


def test_control_lane_pages_on_unhandled_and_guard_denial() -> None:
    pager = _Pager()
    hooks = CvErrorHooks(machine_kind=KIND, lane="control", pager=pager)
    hooks.on_unhandled_event(None, type("E", (), {"type": "X"})(), set(), "deferred")
    hooks.on_guard_evaluated(None, "g", None, False)
    hooks.on_guard_evaluated(None, "g", None, True)
    assert hooks.unhandled_events == 1 and hooks.guard_denials == 1
    assert [s for s, _ in pager.calls] == ["page", "page"]
    platform = CvErrorHooks(machine_kind=KIND, lane="platform", pager=pager)
    platform.on_unhandled_event(None, None, set(), "deferred")
    assert len(pager.calls) == 2


def test_invalid_event_and_stranded_invocation_are_counted() -> None:
    pager = _Pager()
    hooks = CvErrorHooks(machine_kind=KIND, lane="order", pager=pager)
    hooks.on_invalid_event(None, ValueError("x"), 42)
    hooks.on_invocation_stranded(None, "s", "inv", RuntimeError("cut"))
    hooks.on_event_dropped(None, None, "not_running")
    hooks.on_guard_error(None, "g", None, RuntimeError("x"))
    assert (hooks.invalid_events, hooks.stranded_invocations, hooks.dropped_events) == (1, 1, 1)
    assert len(pager.calls) == 3


def test_order_lane_pages_when_a_deferred_event_is_evicted() -> None:
    """24 §8.2 S10 (#847): a full deferral buffer evicts its oldest event, which on the order
    lane may be a fill, so it pages; a plain deferral, or an eviction elsewhere, does not."""
    pager = _Pager()
    order = CvErrorHooks(machine_kind=KIND, lane="order", pager=pager)
    event = type("E", (), {"type": "EXEC"})()
    order.on_unhandled_event(None, event, set(), "deferred")
    order.on_unhandled_event(None, event, set(), "dropped")
    CvErrorHooks(machine_kind=KIND, lane="platform", pager=pager).on_unhandled_event(
        None, event, set(), "dropped"
    )
    assert pager.calls == [("page", f"order-lane deferred event evicted EXEC: {KIND}")]
