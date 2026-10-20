"""#3907: the gateway serves its one route at the external URL `/api/v1/ws` and at `/ws`.

The web client opens `/api/v1/ws` (23-ws-protocol.md section 2.1); the gateway registered only
`/ws`, so a real upgrade there was refused (HTTP 403). `include_ws_router` includes the one router
twice, so both paths run the same handler through the real `create_app()`; any other WebSocket
path is still refused before `accept`. No network, no sleeps (the TestClient portal only).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.csrf import route_path
from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.settings import Environment, Settings
from candleviewer.ws.gateway import WS_SERVER_BASE, include_ws_router

USER = uuid.uuid4()
JSON = ["cv.v1.json"]
ORIGIN = "http://testserver"  # section 2.5: listed in CV_ALLOWED_ORIGINS, sent on every upgrade
_EXPIRES = datetime(2100, 1, 1, tzinfo=UTC)


async def _load(uid: uuid.UUID) -> PrincipalSnapshot:
    perms = frozenset({Permission.MARKETDATA_READ})
    return PrincipalSnapshot(uid, frozenset({"viewer"}), perms, ())


async def _authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
    if token != "tok":  # noqa: S105 - test vector, not a credential
        raise PermissionError("bad token")
    return "sess-1", USER, _EXPIRES


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(environment=Environment.DEMO, allowed_origins=ORIGIN)
    app = create_app(settings, snapshot_loader=_load, ws_authenticate=_authenticate)
    with TestClient(app, client=("127.0.0.1", 50000), headers={"origin": ORIGIN}) as c:
        yield c


def _handshake(ws: Any) -> tuple[str, str]:
    """`hello` then `auth` (section 4.3): the frame types the gateway answers with."""
    ws.send_json({"t": "hello", "id": "h", "p": {"clock_ms": 1}})
    welcome = ws.receive_json()["t"]
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
    return welcome, ws.receive_json()["t"]


@pytest.mark.parametrize("path", ["/api/v1/ws", "/ws"])
def test_the_gateway_completes_a_handshake_on_both_paths(client: TestClient, path: str) -> None:
    with client.websocket_connect(path, subprotocols=JSON) as ws:
        assert _handshake(ws) == ("welcome", "auth_ok")


def test_both_paths_are_one_gateway(client: TestClient) -> None:
    """One router included twice: a socket on each path is held by the same hub."""
    app: Any = client.app  # a FastAPI app; TestClient types it as a bare ASGI callable
    hub = app.state.ws_runtime.hub
    with client.websocket_connect("/ws", subprotocols=JSON) as one:
        assert _handshake(one) == ("welcome", "auth_ok")
        with client.websocket_connect("/api/v1/ws", subprotocols=JSON) as other:
            assert _handshake(other) == ("welcome", "auth_ok")
            assert len(hub) == 2


@pytest.mark.parametrize(
    "path", ["/api/v2/ws", "/api/v1/ws/x", "/api/ws", "/ws/", "/api/v1/ws/", "/API/V1/WS"]
)
def test_any_other_websocket_path_is_refused(client: TestClient, path: str) -> None:
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(path, subprotocols=JSON):
            pass
    assert refused.value.code == 1000  # Starlette's not-found close, before `accept`


def test_include_ws_router_refuses_a_router_with_lifecycle_hooks() -> None:
    """FastAPI replays a router's hooks once per include, so the alias must not carry any."""
    with pytest.raises(ValueError, match="no startup or shutdown hook"):
        include_ws_router(FastAPI(), APIRouter(on_shutdown=[lambda: None]))


def test_the_ws_server_base_is_the_rest_contracts_base() -> None:
    """One spelling of `/api/v1`: the WS alias, the CSRF guard's prefix and the contract's base.

    M23b forbids `ws` importing `api`, so the two constants are pinned here instead of shared."""
    spec: Any = load_openapi_spec()
    assert {urlsplit(server["url"]).path for server in spec["servers"]} == {WS_SERVER_BASE}
    assert route_path(WS_SERVER_BASE + "/auth/session") == "/auth/session"
