"""E04-T02 correlation propagation tests (HTTP, WS hooks, async hops)."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.observability.context import (
    bind_context,
    current_request_id,
    get_context,
    run_in_thread,
    spawn,
    thread_future,
)
from candleviewer.observability.correlation import (
    CorrelationMiddleware,
    sanitize_correlation_id,
    ws_connection_context,
    ws_frame_context,
)

GOOD = "3f2b8c1e-9d4a-4b7e-8a51-0c6d2e7f9a10"


@pytest.fixture(autouse=True)
def _clean_ctx() -> Iterator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/x")
    async def x() -> dict[str, Any]:
        async def bg() -> dict[str, Any]:
            return get_context()

        with bind_context(user_id="u1", account_id="a1"):
            inner = await spawn(bg(), name="t")
        return {"rid": current_request_id(), "inner": inner}

    return app


def test_middleware_mints_and_echoes_when_absent() -> None:
    r = TestClient(_app()).get("/x")
    rid = r.headers["X-Correlation-Id"]
    assert uuid.UUID(rid).version == 4
    assert r.json()["rid"] == rid
    assert r.json()["inner"]["request_id"] == rid
    assert r.json()["inner"]["user_id"] == "u1"


def test_middleware_accepts_valid_inbound_id() -> None:
    r = TestClient(_app()).get("/x", headers={"X-Correlation-Id": GOOD})
    assert r.headers["X-Correlation-Id"] == GOOD


@pytest.mark.parametrize(
    "hostile",
    [
        "'; DROP TABLE",
        "A" * 10_240,
        "3f2b8c1e-9d4a-1b7e-8a51-0c6d2e7f9a10",
        GOOD + "x",
        "{{7*7}}",
    ],
)
def test_malformed_inbound_id_replaced(hostile: str) -> None:
    r = TestClient(_app()).get("/x", headers={"X-Correlation-Id": hostile})
    out = r.headers["X-Correlation-Id"]
    assert out != hostile
    assert uuid.UUID(out).version == 4
    assert hostile not in r.text


def test_sanitize_rejects_none() -> None:
    assert uuid.UUID(sanitize_correlation_id(None)).version == 4


def test_bind_context_unknown_field_rejected() -> None:
    with pytest.raises(ValueError), bind_context(not_a_field="x"):
        pass


def test_bind_context_unbinds_and_nests() -> None:
    with bind_context(request_id="r1"):
        with bind_context(symbol="BTCUSDT"):
            assert get_context() == {"request_id": "r1", "symbol": "BTCUSDT"}
        assert get_context() == {"request_id": "r1"}
    assert get_context() == {}


async def test_spawn_inherits_context() -> None:
    async def child() -> dict[str, Any]:
        return get_context()

    with bind_context(request_id="r1", user_id="u1", account_id="a1"):
        got = await spawn(child(), name="c")
    assert got == {"request_id": "r1", "user_id": "u1", "account_id": "a1"}


async def test_executor_offload_inherits_context() -> None:
    with bind_context(request_id="r9"):
        got = await run_in_thread(get_context)
    assert got == {"request_id": "r9"}


async def test_thread_future_inherits_context_and_is_a_plain_future() -> None:
    """#2250: event-loop teardown cancels every Task, so the audit WAL's lock holder
    needs the executor's own Future: it must never come back wrapped in a Task."""
    with bind_context(request_id="r8", user_id="u8"):
        fut = thread_future(get_context)
    assert isinstance(fut, asyncio.Future)
    assert not isinstance(fut, asyncio.Task)
    assert await fut == {"request_id": "r8", "user_id": "u8"}


def test_ws_hooks_bind_conn_and_frame() -> None:
    with ws_connection_context(user_id="u1") as conn_id:
        with ws_frame_context("bad") as rid:
            ctx = get_context()
            assert ctx["conn_id"] == conn_id
            assert ctx["request_id"] == rid
            assert ctx["user_id"] == "u1"
        assert "request_id" not in get_context()
    assert get_context() == {}


def test_single_request_id_across_path_in_json_logs() -> None:
    """api -> oms -> adapter all share the request_id (captured JSON lines)."""
    import logging
    from contextlib import redirect_stdout

    import candleviewer.observability.logging as lg

    buf = io.StringIO()
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    try:
        with redirect_stdout(buf):
            lg.configure_logging(env="ci", level="info", fmt="json")
            log = structlog.get_logger()

            async def adapter() -> None:
                log.info("bybit.submit")

            @app.post("/orders")
            async def orders() -> dict[str, str]:
                log.info("api.received")
                with bind_context(order_link_id="olid-1"):
                    log.info("oms.validate")
                    await spawn(adapter(), name="adapter")
                return {}

            r = TestClient(app).post("/orders")
            assert lg._listener is not None
            lg._listener.stop()
    finally:
        lg._listener = None
        logging.getLogger().handlers = []
        structlog.reset_defaults()
    mine = {"api.received", "oms.validate", "bybit.submit"}
    lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln["event"] in mine]
    assert {ln["event"] for ln in lines} >= {"api.received", "oms.validate", "bybit.submit"}
    assert {ln["request_id"] for ln in lines} == {r.headers["X-Correlation-Id"]}
    assert all(ln.get("order_link_id") == "olid-1" for ln in lines if ln["event"] != "api.received")
