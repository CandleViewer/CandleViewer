"""#2421: `cv_http_request_duration_seconds` ASGI middleware."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from candleviewer.app import create_app
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.observability.http_duration import (
    METRIC_NAME,
    HttpDurationMiddleware,
)
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE, register_r0
from candleviewer.settings import Environment, Settings


class _Clock:
    """Advances 0.25 s per read: every request measures exactly 0.25 s."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.25
        return self.now


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request"}


async def _noop_send(_: Any) -> None:
    return None


def _hist() -> tuple[Metrics, BoundedMetric]:
    m = Metrics("demo")
    return m, register_r0(m)[METRIC_NAME]


def _app(hist: BoundedMetric) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/things/{thing_id}")
    def get_thing(thing_id: str) -> dict[str, str]:
        return {"id": thing_id}

    @app.post("/v1/things")
    def post_thing() -> dict[str, str]:
        return {}

    @app.get("/v1/bad")
    def bad() -> None:
        raise HTTPException(status_code=409)

    @app.get("/v1/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    app.add_middleware(HttpDurationMiddleware, histogram=hist, clock=_Clock())
    return app


def _keys(m: Metrics) -> set[tuple[str, ...]]:
    fam = next(f for f in m.registry.collect() if f.name == METRIC_NAME)
    return {
        (s.labels["route"], s.labels["method"], s.labels["status_class"])
        for s in fam.samples
        if s.name.endswith("_count")
    }


def _sum(m: Metrics, route: str, method: str, cls: str) -> float | None:
    return m.registry.get_sample_value(
        f"{METRIC_NAME}_sum",
        {"env": "demo", "route": route, "method": method, "status_class": cls},
    )


def test_route_template_labels_series_and_ids_share_one_series() -> None:
    m, hist = _hist()
    client = TestClient(_app(hist))
    client.get("/v1/things/a")
    client.get("/v1/things/b")
    assert _keys(m) == {("/v1/things/{thing_id}", "GET", "2xx")}
    assert _sum(m, "/v1/things/{thing_id}", "GET", "2xx") == pytest.approx(0.5)


def test_unknown_path_goes_to_unmatched_series() -> None:
    m, hist = _hist()
    TestClient(_app(hist)).get("/nope/123")
    assert _keys(m) == {("unmatched", "GET", "4xx")}


def test_custom_method_is_other() -> None:
    m, hist = _hist()
    TestClient(_app(hist)).request("BREW", "/v1/things/a")
    assert {k[1] for k in _keys(m)} == {"other"}


def test_status_classes_and_raised_exception() -> None:
    m, hist = _hist()
    client = TestClient(_app(hist), raise_server_exceptions=False)
    client.get("/v1/things/a")
    client.get("/v1/bad")
    client.post("/v1/things")
    client.get("/v1/boom")
    assert _keys(m) == {
        ("/v1/things/{thing_id}", "GET", "2xx"),
        ("/v1/bad", "GET", "4xx"),
        ("/v1/things", "POST", "2xx"),
        ("/v1/boom", "GET", "5xx"),
    }


def test_exception_is_reraised_unchanged() -> None:
    _, hist = _hist()
    with pytest.raises(RuntimeError, match="boom"):
        TestClient(_app(hist)).get("/v1/boom")


def test_exception_after_response_start_keeps_sent_status() -> None:
    m, hist = _hist()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("late")

    mw = HttpDurationMiddleware(app, histogram=hist, clock=_Clock())

    async def run() -> None:
        await mw({"type": "http", "method": "GET"}, _noop_receive, _noop_send)

    with pytest.raises(RuntimeError):
        asyncio.run(run())
    assert _keys(m) == {("unmatched", "GET", "2xx")}


class _Refuse:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await PlainTextResponse("no", status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def test_refusal_by_inner_middleware_is_timed() -> None:
    m, hist = _hist()
    app = FastAPI()
    app.add_middleware(_Refuse)  # added first = inner; the timer wraps it
    app.add_middleware(HttpDurationMiddleware, histogram=hist, clock=_Clock())
    r = TestClient(app).post("/v1/things/x")
    assert r.status_code == 403
    assert _keys(m) == {("unmatched", "POST", "4xx")}
    assert _sum(m, "unmatched", "POST", "4xx") == pytest.approx(0.25)


def test_cardinality_bound_holds_at_max_series() -> None:
    m = Metrics("demo")
    hist = m.histogram(
        "cv_t_seconds", "t", ("route", "method", "status_class"), buckets=(0.1,), max_series=2
    )
    app = FastAPI()
    for i in range(5):

        def h(i: int = i) -> dict[str, int]:
            return {}

        app.add_api_route(f"/r{i}", h)
    app.add_middleware(HttpDurationMiddleware, histogram=hist)
    client = TestClient(app)
    for i in range(5):
        client.get(f"/r{i}")
    assert hist.series_count == 2
    assert hist.breached


def test_non_http_scopes_pass_through_untouched() -> None:
    m, hist = _hist()
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    mw = HttpDurationMiddleware(inner, histogram=hist)

    async def run() -> None:
        for t in ("websocket", "lifespan"):
            await mw({"type": t}, _noop_receive, _noop_send)

    asyncio.run(run())
    assert seen == ["websocket", "lifespan"]
    assert _keys(m) == set()


def test_catalogue_entry_is_live_and_bracketing_budgets() -> None:
    spec = next(s for s in CATALOGUE if s.name == METRIC_NAME)
    assert spec.status == "live"
    assert spec.labels == ("route", "method", "status_class")
    assert spec.buckets is not None
    assert 0.15 in spec.buckets and 0.3 in spec.buckets
    text = generate_latest(_hist()[0].registry).decode()
    assert f"# TYPE {METRIC_NAME} histogram" in text


def test_create_app_orders_correlation_outermost_then_http_duration() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    classes = [m.cls for m in app.user_middleware]
    assert classes[0] is CorrelationMiddleware
    assert classes[1] is HttpDurationMiddleware


def test_create_app_times_a_mesh_refusal() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    hist = app.state.metrics_facade.get(METRIC_NAME)
    r = TestClient(app, client=("203.0.113.9", 5)).get("/v1/anything/x")
    assert r.status_code >= 400
    assert hist.series_count == 1
    assert "X-Correlation-Id" in r.headers


def test_cancelled_request_without_response_is_not_recorded_and_reraised() -> None:
    m, hist = _hist()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        raise asyncio.CancelledError

    mw = HttpDurationMiddleware(app, histogram=hist, clock=_Clock())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(mw({"type": "http", "method": "GET"}, _noop_receive, _noop_send))
    assert _keys(m) == set()


def test_create_app_matched_route_is_labelled_by_template() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    hist = app.state.metrics_facade.get(METRIC_NAME)
    r = TestClient(app, client=("127.0.0.1", 5)).get("/healthz")
    assert r.status_code == 200
    assert hist.series_count == 1
    assert (
        app.state.metrics_facade.registry.get_sample_value(
            f"{METRIC_NAME}_count",
            {"env": "demo", "route": "/healthz", "method": "GET", "status_class": "2xx"},
        )
        == 1.0
    )


def test_cancelled_after_response_start_keeps_sent_status() -> None:
    m, hist = _hist()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise asyncio.CancelledError

    mw = HttpDurationMiddleware(app, histogram=hist, clock=_Clock())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(mw({"type": "http", "method": "GET"}, _noop_receive, _noop_send))
    assert _keys(m) == {("unmatched", "GET", "2xx")}
