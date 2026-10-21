"""Private-bind listener, runtime wiring, import contract and scrape latency (E04-T03)."""

from __future__ import annotations

import asyncio
import gc
import re
import socket
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from prometheus_client.parser import text_string_to_metric_families
from structlog.testing import capture_logs

from candleviewer.observability import metrics_server
from candleviewer.observability.metrics import Metrics, generate_latest
from candleviewer.observability.metrics_catalogue import register_r0, registered_specs
from candleviewer.observability.metrics_server import (
    MetricsBindError,
    MetricsRuntime,
    make_metrics_app,
    parse_private_bind,
)


@pytest.mark.parametrize(
    "bind", ["127.0.0.1:9108", "10.0.0.5:9108", "100.64.1.2:9108", "[::1]:9108"]
)
def test_parse_private_bind_accepts_private(bind: str) -> None:
    host, port = parse_private_bind(bind)
    assert port == 9108 and host


@pytest.mark.parametrize(
    "bind",
    ["0.0.0.0:9108", "8.8.8.8:9108", "example.com:9108", "127.0.0.1", "127.0.0.1:0", ":9108"],
)
def test_parse_private_bind_rejects_public_or_malformed(bind: str) -> None:
    with pytest.raises(MetricsBindError):
        parse_private_bind(bind)


def test_no_module_outside_observability_imports_prometheus_client() -> None:
    root = Path(__file__).resolve().parents[3] / "candleviewer"
    pat = re.compile(r"^\s*(from|import)\s+prometheus_client\b", re.M)
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p.parent != root / "observability" and pat.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_runtime_serves_live_metrics_and_stops() -> None:
    metrics = Metrics("dev", process_collectors=True)
    runtime = MetricsRuntime(metrics, f"127.0.0.1:{_free_port()}")
    assert runtime.address[0] == "127.0.0.1"
    runtime.start()
    try:
        body = ""
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    r = await client.get(
                        f"http://{runtime.address[0]}:{runtime.address[1]}/metrics"
                    )
                    body = r.text
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
        families = {f.name for f in text_string_to_metric_families(body)}
        for spec in registered_specs():
            assert spec.name.removesuffix("_total") in families, spec.name
    finally:
        await runtime.stop()


_SAMPLERS = {
    "metrics-loop-lag": "run_loop_lag_sampler",
    "metrics-cardinality": "run_cardinality_check",
    "metrics-fallback": "run_fallback_snapshots",
}
_TASKS = ("metrics-listener", *_SAMPLERS)


def _runtime(monkeypatch: pytest.MonkeyPatch, dead: str) -> MetricsRuntime:
    """A runtime whose four tasks park until `stop()`, except `dead`, which raises at once."""

    async def parked(*_a: object, **_k: object) -> None:
        await asyncio.Event().wait()

    async def dies(*_a: object, **_k: object) -> None:
        raise RuntimeError("task died")

    async def serve(self: uvicorn.Server, sockets: object = None) -> None:
        while dead == "hang" or not self.should_exit:  # until `stop()` asks, unless it hangs
            if dead == "metrics-listener":
                raise RuntimeError("task died")
            await asyncio.sleep(0)

    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    for name, attr in _SAMPLERS.items():
        monkeypatch.setattr(metrics_server, attr, dies if name == dead else parked)
    return MetricsRuntime(Metrics("dev"), "127.0.0.1:9108")


def _task(name: str) -> asyncio.Task[object]:
    return next(t for t in asyncio.all_tasks() if t.get_name() == name)


@pytest.mark.parametrize("dead", _TASKS)
async def test_a_task_that_dies_is_logged_by_name_and_error_class(
    monkeypatch: pytest.MonkeyPatch, dead: str
) -> None:
    runtime = _runtime(monkeypatch, dead)
    with capture_logs() as logs:
        runtime.start()
        await asyncio.wait({_task(dead)})  # the runtime's callback was added first: it ran
    assert [(e["event"], e["log_level"], e["task"], e["error"]) for e in logs] == [
        ("metrics_task_failed", "error", dead, "RuntimeError")
    ]
    await runtime.stop()


async def test_stop_awaits_every_task_after_one_died_and_logs_only_the_dead_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(monkeypatch, "metrics-listener")
    unhandled: list[str] = []  # a callback that raises is reported to the loop's handler
    asyncio.get_running_loop().set_exception_handler(
        lambda _l, ctx: unhandled.append(ctx["message"])
    )
    with capture_logs() as logs:
        runtime.start()
        tasks = [_task(name) for name in _TASKS]
        await asyncio.wait({tasks[0]})
        await runtime.stop()
    assert all(t.done() for t in tasks)
    assert [e["task"] for e in logs] == ["metrics-listener"]  # the cancelled three are no failure
    assert unhandled == []


async def test_start_joins_the_gc_pause_timer_and_stop_takes_it_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(monkeypatch, "none")
    runtime.start()
    assert gc.callbacks.count(runtime.gc_timer) == 1
    await runtime.stop()
    assert runtime.gc_timer not in gc.callbacks


async def test_stop_does_not_swallow_a_cancellation_of_its_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(monkeypatch, "hang")  # a listener that never ends holds `stop()`
    runtime.start()
    stop = asyncio.ensure_future(runtime.stop())
    await asyncio.sleep(0)  # `stop()` is waiting for the listener
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop


@pytest.mark.perf
def test_scrape_latency_under_50ms_at_max_cardinality() -> None:
    metrics = Metrics("dev", process_collectors=True)
    r0 = register_r0(metrics)
    for spec in registered_specs():
        if not spec.labels:
            continue
        metric = r0[spec.name]
        for i in range(spec.max_series):
            child = metric.labels(*[f"v{i}"] * len(spec.labels))
            if spec.kind == "histogram":
                child.observe(0.01)
            elif spec.kind == "counter":
                child.inc()
            else:
                child.set(1)
    app = make_metrics_app(metrics.registry)
    handler = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/metrics")
    samples = []
    for _ in range(10):
        t0 = time.perf_counter()
        handler()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    median = samples[len(samples) // 2]
    print(f"scrape median={median * 1000:.1f}ms bytes={len(generate_latest(metrics.registry))}")
    assert median < 0.05
