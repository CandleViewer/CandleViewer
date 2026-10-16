"""Server-layer WS limits equal the protocol constants (single source: ws/limits.py)."""

from __future__ import annotations

import pytest
import uvicorn
from pydantic import ValidationError

from candleviewer.server import APP, CvWebSocketsProtocol, uvicorn_kwargs
from candleviewer.settings import Settings
from candleviewer.ws import limits
from candleviewer.ws.lifecycle import HEARTBEAT_INTERVAL_S, HEARTBEAT_TIMEOUT_S


def test_server_config_matches_limits() -> None:
    cfg = uvicorn.Config(APP, **uvicorn_kwargs())
    assert cfg.ws_max_size == limits.MAX_INBOUND_FRAME_BYTES + limits.SERVER_WS_HEADROOM_BYTES
    assert limits.MAX_INBOUND_FRAME_BYTES < cfg.ws_max_size < 2 * limits.MAX_INBOUND_FRAME_BYTES
    assert cfg.ws_per_message_deflate is limits.SERVER_WS_PER_MESSAGE_DEFLATE
    assert cfg.ws is CvWebSocketsProtocol  # §3.5: deflate off for cv.v1.msgpack (server.py)
    assert cfg.ws_max_queue == limits.SERVER_WS_MAX_QUEUE <= 8
    assert cfg.limit_concurrency == limits.SERVER_LIMIT_CONCURRENCY
    assert cfg.ws_ping_interval == HEARTBEAT_INTERVAL_S
    assert cfg.ws_ping_timeout == HEARTBEAT_TIMEOUT_S
    # #2275: uvicorn never reads `X-Forwarded-For`; MeshOnly's trusted proxy is the only reader.
    assert cfg.proxy_headers is False


def test_server_limits_are_not_library_defaults() -> None:
    cfg = uvicorn.Config(APP, **uvicorn_kwargs())
    assert cfg.ws_max_size != 16 * 1024 * 1024
    assert cfg.ws_max_queue != 32
    assert cfg.limit_concurrency is not None
    assert cfg.timeout_graceful_shutdown is not None  # uvicorn's own default is no bound (#2565)


def test_server_bounds_uvicorns_drain_by_the_settings_timeout() -> None:
    """#2565: an unbounded drain (`_wait_tasks_to_complete`) keeps `lifespan.shutdown()`, and with
    it the module teardown, from ever running while one connection or task stays open."""
    kwargs = uvicorn_kwargs()
    assert kwargs["timeout_graceful_shutdown"] == Settings().uvicorn_drain_timeout_s == 5
    assert uvicorn.Config(APP, **kwargs).timeout_graceful_shutdown == 5
    custom = Settings(uvicorn_drain_timeout_s=9, api_stop_budget_s=60)
    assert uvicorn_kwargs(custom)["timeout_graceful_shutdown"] == 9


def test_server_host_and_port_come_from_settings() -> None:
    kwargs = uvicorn_kwargs(Settings(bind_host="172.28.0.10", bind_port=8123))
    assert kwargs["host"] == "172.28.0.10"
    assert kwargs["port"] == 8123


def test_server_default_host_is_loopback() -> None:
    assert uvicorn_kwargs(Settings())["host"] == "127.0.0.1"


def test_wildcard_bind_host_is_refused_by_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(bind_host="0.0.0.0")  # nosec B104  # noqa: S104 - asserting the refusal
