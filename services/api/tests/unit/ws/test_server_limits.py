"""Server-layer WS limits equal the protocol constants (single source: ws/limits.py)."""

from __future__ import annotations

import uvicorn

from candleviewer.server import APP, uvicorn_kwargs
from candleviewer.ws import limits
from candleviewer.ws.lifecycle import HEARTBEAT_INTERVAL_S, HEARTBEAT_TIMEOUT_S


def test_server_config_matches_limits() -> None:
    cfg = uvicorn.Config(APP, **uvicorn_kwargs())
    assert cfg.ws_max_size == limits.MAX_INBOUND_FRAME_BYTES + limits.SERVER_WS_HEADROOM_BYTES
    assert limits.MAX_INBOUND_FRAME_BYTES < cfg.ws_max_size < 2 * limits.MAX_INBOUND_FRAME_BYTES
    assert cfg.ws_per_message_deflate is limits.SERVER_WS_PER_MESSAGE_DEFLATE
    assert cfg.ws_max_queue == limits.SERVER_WS_MAX_QUEUE <= 8
    assert cfg.limit_concurrency == limits.SERVER_LIMIT_CONCURRENCY
    assert cfg.ws_ping_interval == HEARTBEAT_INTERVAL_S
    assert cfg.ws_ping_timeout == HEARTBEAT_TIMEOUT_S
    assert cfg.proxy_headers is True


def test_server_limits_are_not_library_defaults() -> None:
    cfg = uvicorn.Config(APP, **uvicorn_kwargs())
    assert cfg.ws_max_size != 16 * 1024 * 1024
    assert cfg.ws_max_queue != 32
    assert cfg.limit_concurrency is not None
