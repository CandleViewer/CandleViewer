"""tests/xstate_contract/test_gateway.py — E50-T15 gateway contract tests.

Gherkin:
  1. Order-lane overflow returns 503 (+ page, counted, nothing silently dropped).
  2. Cross-thread send reads the future (failure counted and logged).
  3. priority=True is refused by CV-LINT-PRIORITY.
Plus loop affinity (CV-C33), system-event refusal (CV-C42), receipt rule (CV-C06).
"""

from __future__ import annotations

import ast
import asyncio
import concurrent.futures
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from prometheus_client import generate_latest
from xstate_statemachine import SimulatedClock, system_event

from candleviewer.observability.metrics import Metrics
from candleviewer.statechart import build
from candleviewer.statechart.config import CV_INBOX_BOUND, Lane
from candleviewer.statechart.factory import InboxFullError
from candleviewer.statechart.gateway import (
    Gateway,
    GatewayDegradedError,
    GatewayOverloadedError,
    LoopAffinityError,
    SystemEventRefusedError,
    UnknownMachineError,
    receipt_is_conclusive,
)
from candleviewer.statechart.plugins import InMemoryMachineEventSink, cv_plugins
from candleviewer.statechart.registry import Registry
from tests.xstate_contract.plugin_fixtures import binding_plugins  # noqa: F401 - registers bindings

KIND = "test.plugins_min"
REPO = Path(__file__).resolve().parents[4]


class _Pager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.calls.append((severity, summary))


@pytest.fixture()
def registry() -> Registry:
    return Registry(machines_dir=Path(__file__).resolve().parent / "plugin_fixtures")


async def _setup(registry: Registry, lane: Lane) -> tuple[Gateway, Any, Metrics, _Pager]:
    pager, metrics = _Pager(), Metrics("dev")
    plugins = cv_plugins(
        machine_kind=KIND,
        lane=lane,
        entity_id="00000000-0000-0000-0000-000000000001",
        env="dev",
        metrics=metrics,
        sink=InMemoryMachineEventSink(),
        pager=pager,
        write_ahead=False,
    )
    res = await build(KIND, clock=SimulatedClock(), lane=lane, plugins=plugins, registry=registry)
    gw = Gateway(pager=pager)
    gw.register("m1", res.interpreter, kind=KIND, lane=lane, metrics=plugins[1])
    return gw, res.interpreter, metrics, pager


def _refused(metrics: Metrics, reason: str) -> float:
    for line in generate_latest(metrics.registry).decode().splitlines():
        if line.startswith("cv_machine_send_refused_total{") and f'reason="{reason}"' in line:
            return float(line.rsplit(" ", 1)[1])
    return 0.0


async def test_order_lane_overflow_returns_503_and_pages(registry: Registry) -> None:
    gw, interp, metrics, pager = await _setup(registry, "order")
    try:
        for _ in range(CV_INBOX_BOUND["order"]):
            await gw.send("m1", "NOOP")
        with pytest.raises(GatewayOverloadedError) as ei:
            await gw.send("m1", "NOOP")
        assert ei.value.status_code == 503
        assert any(sev == "page" for sev, _ in pager.calls)
        assert _refused(metrics, "queue_full") == 1.0
    finally:
        await interp.stop()


async def test_platform_lane_overflow_alerts_not_pages(registry: Registry) -> None:
    gw, interp, _metrics, pager = await _setup(registry, "platform")
    try:
        for _ in range(CV_INBOX_BOUND["platform"]):
            await gw.send("m1", "NOOP")
        with pytest.raises(GatewayOverloadedError):
            await gw.send("m1", "NOOP")
        assert [sev for sev, _ in pager.calls] == ["alert"]
    finally:
        await interp.stop()


async def test_send_threadsafe_call_site_overflow_is_503(registry: Registry) -> None:
    gw, interp, metrics, pager = await _setup(registry, "order")
    try:
        for _ in range(CV_INBOX_BOUND["order"]):
            await gw.send("m1", "NOOP")
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            with pytest.raises(GatewayOverloadedError):
                await asyncio.wrap_future(pool.submit(gw.send_threadsafe, "m1", "NOOP"))
        assert _refused(metrics, "queue_full") == 1.0
        assert any(sev == "page" for sev, _ in pager.calls)
    finally:
        await interp.stop()


async def test_send_threadsafe_from_worker_thread_delivers(registry: Registry) -> None:
    gw, interp, _metrics, _pager = await _setup(registry, "order")
    try:
        done = threading.Event()
        holder: list[concurrent.futures.Future[None]] = []

        def worker() -> None:
            holder.append(gw.send_threadsafe("m1", "GO"))
            done.set()

        t = threading.Thread(target=worker)
        t.start()
        await asyncio.wrap_future(asyncio.get_running_loop().run_in_executor(None, done.wait))
        t.join()
        await asyncio.wrap_future(holder[0])
        for _ in range(20):
            await asyncio.sleep(0)
        assert any("busy" in str(s) for s in interp.current_state_ids)
    finally:
        await interp.stop()


class _Recorder:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    def record_send_refused(self, reason: str) -> None:
        self.reasons.append(reason)


class _FakeInterp:
    """Returns a caller-controlled future so loop-side failures are exact."""

    def __init__(self) -> None:
        self.fut: concurrent.futures.Future[None] = concurrent.futures.Future()
        self.raise_on_call: BaseException | None = None

    def send_threadsafe(self, event: Any) -> concurrent.futures.Future[None]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self.fut


async def _fake(lane: Lane = "order") -> tuple[Gateway, _FakeInterp, _Recorder, _Pager]:
    pager, rec, interp = _Pager(), _Recorder(), _FakeInterp()
    gw = Gateway(pager=pager)
    gw.register("f", interp, kind="fake", lane=lane, metrics=rec)
    return gw, interp, rec, pager


async def test_send_threadsafe_failed_future_is_counted_and_logged() -> None:
    from structlog.testing import capture_logs

    gw, interp, rec, _pager = await _fake()
    with capture_logs() as logs:
        await asyncio.to_thread(gw.send_threadsafe, "f", "GO")
        interp.fut.set_exception(RuntimeError("loop closed"))
    assert rec.reasons == ["send_failed"]
    assert any(e["event"] == "statechart_send_failed" for e in logs)


async def test_send_threadsafe_cancelled_future_is_counted() -> None:
    gw, interp, rec, _pager = await _fake()
    gw.send_threadsafe("f", "GO")
    interp.fut.cancel()
    assert rec.reasons == ["send_failed"]


async def test_send_threadsafe_loop_side_overflow_pages_without_double_count() -> None:
    gw, interp, rec, pager = await _fake("order")
    gw.send_threadsafe("f", "GO")
    interp.fut.set_exception(InboxFullError("f", 64, 64))
    assert rec.reasons == []  # counted by CvMetricsPlugin.on_event_dropped
    assert [sev for sev, _ in pager.calls] == ["page"]


async def test_send_threadsafe_success_records_nothing() -> None:
    gw, interp, rec, pager = await _fake()
    gw.send_threadsafe("f", "GO")
    interp.fut.set_result(None)
    assert rec.reasons == [] and pager.calls == []


async def test_send_threadsafe_call_site_error_is_counted_and_reraised() -> None:
    gw, interp, rec, _pager = await _fake()
    interp.raise_on_call = RuntimeError("not started")
    with pytest.raises(RuntimeError):
        gw.send_threadsafe("f", "GO")
    assert rec.reasons == ["send_failed"]


async def test_send_off_owning_loop_is_refused() -> None:
    gw, _interp, _rec, _pager = await _fake()

    def other_loop() -> None:
        asyncio.run(gw.send("f", "GO"))

    with pytest.raises(LoopAffinityError):
        await asyncio.to_thread(other_loop)


async def test_system_event_is_never_forwarded() -> None:
    gw, _interp, rec, _pager = await _fake()
    with pytest.raises(SystemEventRefusedError):
        gw.send_threadsafe("f", system_event("GO"))  # type: ignore[arg-type]  # deliberate misuse
    assert rec.reasons == ["system_event"]


async def test_unknown_and_duplicate_keys() -> None:
    gw, interp, rec, _pager = await _fake()
    with pytest.raises(UnknownMachineError):
        await gw.send("nope", "GO")
    with pytest.raises(Exception, match="already registered"):
        gw.register("f", interp, kind="fake", lane="order", metrics=rec)
    gw.unregister("f")
    with pytest.raises(UnknownMachineError):
        gw.send_threadsafe("f", "GO")


@pytest.mark.parametrize(
    ("receipt", "expected"),
    [
        (None, False),
        (SimpleNamespace(changed=False, error=None, deferred=False), False),
        (SimpleNamespace(changed=False, error=None, deferred=True), False),
        (SimpleNamespace(changed=True, error=None, deferred=True), False),
        (SimpleNamespace(changed=True, error=None, deferred=False), True),
        (SimpleNamespace(changed=False, error=ValueError(), deferred=False), True),
    ],
)
def test_receipt_is_conclusive_cv_c06(receipt: Any, expected: bool) -> None:
    assert receipt_is_conclusive(receipt) is expected


async def test_wait_receipt_for_deferred_event_is_not_a_gate(registry: Registry) -> None:
    gw, interp, _metrics, _pager = await _setup(registry, "platform")
    try:
        await gw.send("m1", "GO", wait=True)
        receipt = await gw.send("m1", "GO", wait=True)  # unhandled in `busy` -> deferred
        assert not receipt_is_conclusive(receipt)
    finally:
        await interp.stop()


def test_priority_true_fails_cv_lint_priority() -> None:
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import lint_statecharts
    finally:
        sys.path.pop(0)
    tree = ast.parse("gw.send('k', 'GO', priority=True)")
    rules = [f.rule for f in lint_statecharts.rule_priority("x.py", tree)]
    assert rules == ["CV-LINT-PRIORITY"]
    gateway_src = REPO / "services/api/candleviewer/statechart/gateway.py"
    assert lint_statecharts.lint_python_file(gateway_src) == []


def test_overloaded_error_maps_to_http_503_problem_response() -> None:
    """AC1 through the real app wiring: create_app registers the 503 handler."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.app import create_app, gateway_overloaded_handler

    assert GatewayOverloadedError in create_app().exception_handlers

    app = FastAPI()
    app.add_exception_handler(GatewayOverloadedError, gateway_overloaded_handler)

    @app.get("/boom")
    async def boom() -> None:
        raise GatewayOverloadedError("m1", "order")

    resp = TestClient(app).get("/boom")
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 503
    assert resp.headers["retry-after"] == "1"
    body = resp.json()  # #2828: a catalogued code, never about:blank; the cause in errors[].rule
    assert body["code"] == "lifecycle_unavailable"
    assert body["type"] == "https://candleviewer.local/errors/lifecycle_unavailable"
    assert body["errors"] == [{"rule": "gateway_overloaded"}]


def test_degraded_error_maps_to_lifecycle_unavailable_with_its_rule() -> None:
    """#2828: the degraded latch answers the same 503 code, told apart by `errors[].rule`."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.app import create_app, gateway_overloaded_handler

    assert GatewayDegradedError in create_app().exception_handlers
    app = FastAPI()
    app.add_exception_handler(GatewayDegradedError, gateway_overloaded_handler)

    @app.get("/boom")
    async def boom() -> None:
        raise GatewayDegradedError("m1", "order")

    resp = TestClient(app).get("/boom")
    body = resp.json()
    assert (resp.status_code, resp.headers["retry-after"]) == (503, "1")
    assert body["code"] == "lifecycle_unavailable"
    assert body["errors"] == [{"rule": "gateway_degraded"}]
