"""SR-042 / SR-183: the `Origin` / `Sec-Fetch-Site` check on the WS upgrade (#2239).

`23-ws-protocol.md` §2.5: the check runs before negotiation, `accept`, any frame, auth or
store access. A refusal is a close `4403` before `accept` (HTTP 403 on the wire, no `bye`).
No network, no sleeps: TestClient sessions plus one direct ASGI drive.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from starlette.types import Message, Scope
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.settings import Settings
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.lifecycle import ORIGIN_FORBIDDEN, OriginRefusal, origin_refusal
from candleviewer.ws.metrics import cv_ws_closes_total, cv_ws_connections_in_use
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub

ORIGIN = "http://testserver"  # the TestClient's own origin
EVIL = "https://evil.example"
ALLOWED = frozenset({ORIGIN})
JSON = ["cv.v1.json"]
USER = uuid.uuid4()


def _sample(metric: Any, name: str, **labels: str) -> float:
    for family in metric.collect():
        for s in family.samples:
            if s.name == name and all(s.labels.get(k) == v for k, v in labels.items()):
                return float(s.value)
    return 0.0


def _refusals() -> float:
    return _sample(cv_ws_closes_total, "cv_ws_closes_total", reason=ORIGIN_FORBIDDEN)


def _open_sockets() -> float:
    return _sample(cv_ws_connections_in_use, "cv_ws_connections_in_use")


class _Spy:
    """Stand-ins for the session store (`authenticate`) and the principal store (`resolve`)."""

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.resolved: list[uuid.UUID] = []

    async def authenticate(self, token: str) -> tuple[str, uuid.UUID]:
        self.tokens.append(token)
        return "sess-1", USER

    async def resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        self.resolved.append(uid)
        perms = frozenset({Permission.MARKETDATA_READ})
        return PrincipalSnapshot(uid, frozenset({"viewer"}), perms)


def _app(spy: _Spy, hub: GatewayHub) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_ws_router(
            authenticate=spy.authenticate,
            registry=ConnectionRegistry(spy.resolve, lambda: 1),
            revocation_hub=RevocationHub(),
            allowed_origins=ALLOWED,
            hub=hub,
            tick_s=0.005,
        )
    )
    return app


# -- the pure §2.5 decision ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origins", "sites", "expected"),
    [
        ([ORIGIN], ["cross-site"], OriginRefusal.FETCH_SITE),
        ([ORIGIN], ["same-site"], OriginRefusal.FETCH_SITE),
        ([ORIGIN], ["Cross-Site "], OriginRefusal.FETCH_SITE),
        ([ORIGIN], ["same-origin", "cross-site"], OriginRefusal.FETCH_SITE),
        ([], [], OriginRefusal.ORIGIN_MISSING),
        ([], ["same-origin"], OriginRefusal.ORIGIN_MISSING),
        (["null"], [], OriginRefusal.ORIGIN_NULL),
        (["NULL"], [], OriginRefusal.ORIGIN_NULL),
        (["null/"], ["same-origin"], OriginRefusal.ORIGIN_NULL),
        ([EVIL], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        (["http://testserver.evil.example"], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        (["https://testserver"], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        (["http://testserver:8443"], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        ([""], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        ([ORIGIN, ORIGIN], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        ([ORIGIN, EVIL], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
    ],
)
def test_origin_refusal_section_2_5_cases_are_refused(
    origins: list[str], sites: list[str], expected: OriginRefusal
) -> None:
    assert origin_refusal(origins, sites, ALLOWED) is expected


@pytest.mark.parametrize(
    ("origins", "sites"),
    [([ORIGIN], []), ([ORIGIN], ["same-origin"]), ([ORIGIN], ["none"]), ([f"{ORIGIN}/"], [])],
)
def test_origin_refusal_listed_origin_same_origin_fetch_is_admitted(
    origins: list[str], sites: list[str]
) -> None:
    assert origin_refusal(origins, sites, ALLOWED) is None


def test_origin_refusal_null_is_refused_even_when_listed() -> None:
    listed = frozenset({"null", ORIGIN})
    assert origin_refusal(["null"], [], listed) is OriginRefusal.ORIGIN_NULL


def test_origin_refusal_empty_allow_list_refuses_everything() -> None:
    refused = origin_refusal([ORIGIN], ["same-origin"], frozenset())
    assert refused is OriginRefusal.ORIGIN_NOT_ALLOWED


_printable = st.text(st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=40)


@given(
    origins=st.lists(
        st.sampled_from([ORIGIN, f"{ORIGIN}/", "null", EVIL]) | _printable, max_size=3
    ),
    sites=st.lists(
        st.sampled_from(["cross-site", "same-site", "same-origin", "none"]) | _printable, max_size=2
    ),
)
def test_origin_refusal_admits_only_one_listed_non_null_origin_without_a_cross_fetch(
    origins: list[str], sites: list[str]
) -> None:
    listed = ALLOWED | {"null"}  # a mis-configured `null` entry must still never admit
    admitted = origin_refusal(origins, sites, listed) is None
    expected = (
        len(origins) == 1
        and origins[0].strip().rstrip("/") in listed
        and origins[0].strip().rstrip("/").lower() != "null"
        and not any(s.strip().lower() in ("cross-site", "same-site") for s in sites)
    )
    assert admitted is expected


def test_make_ws_router_has_no_default_allow_list() -> None:
    """No `None` / default path that could skip the check (C-4.14 intent)."""
    param = inspect.signature(make_ws_router).parameters["allowed_origins"]
    assert param.default is inspect.Parameter.empty


# -- socket level: refused before accept, auth and the stores ----------------------------------

_REFUSED = [
    pytest.param({"origin": ORIGIN, "sec-fetch-site": "cross-site"}, "fetch_site", id="cross-site"),
    pytest.param({"origin": ORIGIN, "sec-fetch-site": "same-site"}, "fetch_site", id="same-site"),
    pytest.param({"origin": EVIL}, "origin_not_allowed", id="bad-origin"),
    pytest.param({"origin": "null"}, "origin_null", id="null-origin"),
    pytest.param({}, "origin_missing", id="missing-origin"),
]


@pytest.mark.parametrize(("headers", "check"), _REFUSED)
def test_upgrade_refused_4403_before_accept_auth_and_store(
    headers: dict[str, str], check: str
) -> None:
    spy, hub = _Spy(), GatewayHub()
    refusals, sockets = _refusals(), _open_sockets()
    with TestClient(_app(spy, hub)) as client, capture_logs() as logs:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws", subprotocols=JSON, headers=dict(headers)) as ws:
                ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "t"}})
    assert exc.value.code == 4403
    assert spy.tokens == [] and spy.resolved == []  # no auth, no principal lookup
    assert len(hub) == 0 and _open_sockets() == sockets  # never accepted or registered
    assert _refusals() == refusals + 1
    entries = [e for e in logs if e.get("event") == "ws upgrade refused"]
    assert [(e["reason"], e["check"], e["log_level"]) for e in entries] == [
        (ORIGIN_FORBIDDEN, check, "warning")
    ]
    assert not any(v in str(entries) for v in (ORIGIN, EVIL, "cross-site", "same-site"))


@pytest.mark.parametrize("site", [None, "same-origin", "none"])
def test_upgrade_from_allowed_origin_is_accepted_and_authenticates(site: str | None) -> None:
    spy = _Spy()
    headers = {"origin": ORIGIN} | ({"sec-fetch-site": site} if site else {})
    with TestClient(_app(spy, GatewayHub())) as client:
        with client.websocket_connect("/ws", subprotocols=JSON, headers=headers) as ws:
            assert ws.accepted_subprotocol == "cv.v1.json"
            ws.send_json({"t": "hello", "id": "h"})
            assert ws.receive_json()["t"] == "welcome"
            ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "t"}})
            assert ws.receive_json()["t"] == "auth_ok"
    assert spy.tokens == ["t"] and spy.resolved == [USER]


def test_origin_is_checked_before_subprotocol_negotiation() -> None:
    with TestClient(_app(_Spy(), GatewayHub())) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            headers = {"origin": EVIL}
            with client.websocket_connect("/ws", subprotocols=["cv.v2.json"], headers=headers):
                pass
    assert exc.value.code == 4403  # not 1002: a foreign page learns nothing about negotiation


async def test_refusal_is_a_close_before_accept_on_the_asgi_wire() -> None:
    """ASGI: `websocket.close` before `websocket.accept` makes the server answer HTTP 403."""
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/ws",
        "raw_path": b"/ws",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"origin", EVIL.encode()), (b"sec-websocket-protocol", b"cv.v1.json")],
        "subprotocols": ["cv.v1.json"],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "state": {},
    }
    await _app(_Spy(), GatewayHub())(scope, receive, send)
    assert [(m["type"], m.get("code")) for m in sent] == [("websocket.close", 4403)]


# -- create_app: `CV_ALLOWED_ORIGINS` is the allow-list ----------------------------------------


def _created(allowed: str, spy: _Spy) -> TestClient:
    app = create_app(
        Settings(allowed_origins=allowed),
        snapshot_loader=spy.resolve,
        ws_authenticate=spy.authenticate,
    )
    return TestClient(app, client=("127.0.0.1", 50000))  # on-mesh source


def test_create_app_admits_an_origin_listed_in_cv_allowed_origins() -> None:
    spy = _Spy()
    with _created(f" {ORIGIN}/ ,https://other.example", spy) as client:
        with client.websocket_connect("/ws", subprotocols=JSON, headers={"origin": ORIGIN}) as ws:
            ws.send_json({"t": "hello", "id": "h"})
            assert ws.receive_json()["t"] == "welcome"


@pytest.mark.parametrize(("allowed", "origin"), [(ORIGIN, EVIL), ("", ORIGIN)])
def test_create_app_refuses_unlisted_origin_before_auth_and_store(
    allowed: str, origin: str
) -> None:
    spy, refusals = _Spy(), _refusals()
    with _created(allowed, spy) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws", subprotocols=JSON, headers={"origin": origin}):
                pass
    assert exc.value.code == 4403 and _refusals() == refusals + 1  # this check, not the mesh
    assert spy.tokens == [] and spy.resolved == []
