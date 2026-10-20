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

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candleviewer.api.deny_by_default import DECLARED_WS_ROUTES
from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.settings import Environment, Settings

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
    assert DECLARED_WS_ROUTES == {"/ws", "/api/v1/ws"}


@pytest.mark.parametrize("path", ["/api/v2/ws", "/api/v1/ws/x", "/api/ws"])
def test_any_other_websocket_path_is_refused(client: TestClient, path: str) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(path, subprotocols=JSON):
        pass  # the upgrade is refused before `accept`
