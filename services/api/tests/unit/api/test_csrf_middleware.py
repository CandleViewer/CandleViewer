"""`CsrfMiddleware` edges not reachable through the auth routers (#2090). No I/O."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.csrf import CsrfMiddleware, is_exempt, route_path
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec
from candleviewer.auth.errors import SessionNotFound

_CODEC = CsrfCodec(b"\x07" * 32)
_SID = uuid.uuid4()


class _Sessions:
    def __init__(self) -> None:
        self.peeked: list[str] = []

    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        if token != "good":  # noqa: S105 - test token
            raise SessionNotFound("x")
        return SimpleNamespace(id=_SID, user_id=_SID)

    async def peek_refresh(self, raw: str) -> Any:
        self.peeked.append(raw)
        return SimpleNamespace(id=_SID, user_id=_SID) if raw == "rt" else None


class _Audit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})


def _app(sessions: Any) -> tuple[TestClient, _Audit]:
    app = FastAPI()
    audit = _Audit()

    @app.post("/auth/refresh")
    async def refresh(body: dict[str, Any]) -> dict[str, Any]:
        return {"echo": body}

    @app.post("/w")
    async def w() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(CsrfMiddleware, codec=_CODEC, sessions=lambda: sessions, audit=audit)
    return TestClient(app), audit


def _pair(sid: uuid.UUID = _SID) -> tuple[dict[str, str], dict[str, str]]:
    t = _CODEC.issue(str(sid))
    return {CSRF_HEADER: t}, {CSRF_COOKIE: t}


def test_route_path_and_exemptions() -> None:
    assert route_path("/api/v1/auth/login") == "/auth/login"
    assert route_path("/api/v1") == "/"
    assert route_path("/api/v10/x") == "/api/v10/x"
    assert is_exempt("GET", "/anything")
    assert is_exempt("post", "/api/v1/invites/t/confirm")
    assert not is_exempt("PUT", "/auth/login")  # exemption is POST only
    assert not is_exempt("DELETE", "/invites/t")


def test_body_refresh_body_is_replayed_to_the_route() -> None:
    sessions = _Sessions()
    client, _ = _app(sessions)
    h, c = _pair()
    r = client.post("/auth/refresh", json={"refresh_token": "rt"}, headers=h, cookies=c)
    assert r.status_code == 200 and r.json() == {"echo": {"refresh_token": "rt"}}
    assert sessions.peeked == ["rt"]


@pytest.mark.parametrize(
    "content", [b"not json", b'{"refresh_token": 5}', b"[]", b'{"refresh_token": ""}']
)
def test_body_refresh_without_a_usable_token_passes_to_the_route(content: bytes) -> None:
    client, audit = _app(_Sessions())
    h, c = _pair()
    r = client.post("/auth/refresh", content=content, headers=h, cookies=c)
    assert r.status_code != 403  # no session resolved: the route answers itself
    assert not audit.calls


def test_oversized_refresh_body_is_not_buffered_and_resolves_no_session() -> None:
    sessions = _Sessions()
    client, _ = _app(sessions)
    h, c = _pair()
    client.post("/auth/refresh", content=b"x" * 10_000, headers=h, cookies=c)
    assert sessions.peeked == []


def test_unknown_refresh_token_resolves_no_session() -> None:
    client, _ = _app(_Sessions())
    h, c = _pair(uuid.uuid4())
    r = client.post("/auth/refresh", json={"refresh_token": "nope"}, headers=h, cookies=c)
    assert r.status_code == 200  # the route (stub here) is what returns 401 in production


def test_sessions_backend_not_wired_passes_well_formed_tokens_to_the_route() -> None:
    client, _ = _app(None)
    h, c = _pair()
    assert client.post("/w", headers=h, cookies=c).status_code == 200


def test_valid_bound_token_passes_and_unknown_bearer_falls_through() -> None:
    client, audit = _app(_Sessions())
    h, c = _pair()
    assert client.post("/w", headers={**h, "Authorization": "Bearer good"}, cookies=c).json() == {
        "ok": "yes"
    }
    assert (
        client.post("/w", headers={**h, "Authorization": "Bearer bad"}, cookies=c).status_code
        == 200
    )
    assert not audit.calls


def test_malformed_cookie_header_counts_as_missing() -> None:
    client, audit = _app(_Sessions())
    h, _ = _pair()
    r = client.post("/w", headers={**h, "Cookie": 'a="unterminated'})
    assert r.status_code == 403 and audit.calls[-1]["reason"] == "missing"


def test_refusal_audit_carries_no_token_value() -> None:
    client, audit = _app(_Sessions())
    h, c = _pair(uuid.uuid4())
    r = client.post("/w", headers={**h, "Authorization": "Bearer good"}, cookies=c)
    assert r.status_code == 403
    rec = audit.calls[-1]
    assert rec["action"] == "auth.csrf_refused" and rec["reason"] == "wrong_session"
    assert h[CSRF_HEADER] not in repr(rec) and h[CSRF_HEADER] not in r.text
    assert rec["after_state"] == {"method": "POST", "path": "/w"}
