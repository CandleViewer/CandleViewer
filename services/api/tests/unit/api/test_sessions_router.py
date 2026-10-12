"""HTTP-level tests for the E09-S03 session routes (QA #1634): refresh rotation,
reuse detection, logout, listing, IDOR and unauthenticated access. No DB/network."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.sessions import REFRESH_COOKIE, make_session_router
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.csrf_helpers import arm_csrf
from tests.unit.auth.session_fakes import FakeSessionRepository

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)  # SR-041 (#2090): routers require a codec

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
_BASE = "https://testserver"


class _Auth:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions
        self.sessions_is_active = True


class _Writer:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.events.append({"action": action, **kw})


class _Audit:
    is_active = True

    def __init__(self) -> None:
        self.writer = _Writer()


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "u", "roles": ["owner"]}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"], "account_scope": []}


class _Env:
    def __init__(
        self,
        *,
        identity: bool = True,
        origins: frozenset[str] = frozenset(),
        throttle_max: int = 10,
        audit: Any = None,
    ) -> None:
        self.repo = FakeSessionRepository()
        self.svc = SessionService(
            self.repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW
        )
        self.audit = audit if audit is not None else _Audit()
        self.t = 0.0
        self.revoked: list[tuple[str, str]] = []

        async def publish(sid: str, reason: str) -> None:
            self.revoked.append((sid, reason))

        app = FastAPI()
        app.include_router(
            make_session_router(
                _Auth(self.svc),
                self.audit,
                identity=_Identity() if identity else None,
                publish_revocation=publish,
                allowed_origins=origins,
                ip_throttle=PerIpLoginThrottle(
                    max_attempts=throttle_max, window_s=60.0, clock=lambda: self.t
                ),
                session_throttle=PerIpLoginThrottle(
                    max_attempts=throttle_max, window_s=60.0, clock=lambda: self.t
                ),
                csrf=_CSRF_CODEC,
            ),
            prefix="/api/v1",
        )
        self.client = TestClient(app, base_url=_BASE)

    async def mint(self, user: uuid.UUID) -> Any:
        """Mint a session and hold its SR-041 token, as the browser holds the
        `__Host-cv_csrf` cookie issued at login (refresh verifies it, #2090)."""
        minted = await self.svc.mint(str(user))
        arm_csrf(self.client, _CSRF_CODEC, minted.session_id)
        return minted


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def env() -> _Env:
    return _Env()


async def test_unauthenticated_routes_return_401(env: _Env) -> None:
    for method, path in [
        ("GET", "/api/v1/auth/session"),
        ("GET", "/api/v1/auth/sessions"),
        ("POST", "/api/v1/auth/logout"),
        ("DELETE", f"/api/v1/me/sessions/{uuid.uuid4()}"),
    ]:
        assert env.client.request(method, path).status_code == 401, path


async def test_refresh_rotates_and_sets_strict_cookie(env: _Env) -> None:
    m = await env.mint(uuid.uuid4())
    r = env.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "authenticated"
    assert body["tokens"]["access_token"] != m.access_token
    cookie = r.headers["set-cookie"]
    assert REFRESH_COOKIE in cookie
    for attr in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth"):
        assert attr.lower() in cookie.lower()


async def test_refresh_reuse_is_401_with_critical_audit(env: _Env) -> None:
    m = await env.mint(uuid.uuid4())
    assert (
        env.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token}).status_code
        == 200
    )
    env.client.cookies.clear()  # the client would otherwise replay the rotated cookie
    r = env.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token})
    assert r.status_code == 401
    ev = env.audit.writer.events[-1]
    assert ev["action"] == "auth.refresh_reuse_detected"
    assert ev["severity"] == Severity.CRITICAL
    assert ev["outcome"] == AuditOutcome.DENIED


async def test_refresh_without_identity_is_501_and_burns_no_token() -> None:
    e = _Env(identity=False)
    m = await e.mint(uuid.uuid4())
    assert (
        e.client.post("/api/v1/auth/refresh", json={"refresh_token": m.refresh_token}).status_code
        == 501
    )
    assert e.client.get("/api/v1/auth/sessions", headers=_h(m.access_token)).status_code == 200


async def test_cross_origin_cookie_refresh_is_refused(env: _Env) -> None:
    m = await env.mint(uuid.uuid4())
    r = env.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


async def test_same_host_origin_not_on_allow_list_is_refused() -> None:
    env = _Env(origins=frozenset({"http://app.example"}))
    m = await env.mint(uuid.uuid4())
    r = env.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": "http://testserver", "Host": "testserver"},
    )
    assert r.status_code == 403


async def test_list_sessions_is_scoped_to_caller(env: _Env) -> None:
    me, other = uuid.uuid4(), uuid.uuid4()
    a = await env.mint(me)
    await env.mint(me)
    await env.mint(other)
    r = env.client.get("/api/v1/auth/sessions", headers=_h(a.access_token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert sum(i["current"] for i in items) == 1


async def test_revoke_other_users_session_is_404_idor(env: _Env) -> None:
    mine = await env.mint(uuid.uuid4())
    theirs = await env.mint(uuid.uuid4())
    r = env.client.delete(f"/api/v1/me/sessions/{theirs.session_id}", headers=_h(mine.access_token))
    assert r.status_code == 404
    assert env.revoked == []
    assert (
        env.client.get("/api/v1/auth/sessions", headers=_h(theirs.access_token)).status_code == 200
    )


async def test_revoke_own_other_session_publishes_revocation(env: _Env) -> None:
    user = uuid.uuid4()
    a = await env.mint(user)
    b = await env.mint(user)
    r = env.client.delete(f"/api/v1/me/sessions/{b.session_id}", headers=_h(a.access_token))
    assert r.status_code == 204
    assert env.revoked == [(str(b.session_id), "session_revoked")]
    assert env.client.get("/api/v1/auth/session", headers=_h(b.access_token)).status_code == 401


async def test_logout_all_revokes_every_session_and_clears_cookie(env: _Env) -> None:
    user = uuid.uuid4()
    a = await env.mint(user)
    b = await env.mint(user)
    r = env.client.post(
        "/api/v1/auth/logout", json={"all_sessions": True}, headers=_h(a.access_token)
    )
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert {sid for sid, _ in env.revoked} == {str(a.session_id), str(b.session_id)}
    assert env.client.get("/api/v1/auth/session", headers=_h(b.access_token)).status_code == 401
    assert "auth.logout" in [e["action"] for e in env.audit.writer.events]


async def test_logout_rejects_unknown_body_fields(env: _Env) -> None:
    a = await env.mint(uuid.uuid4())
    r = env.client.post("/api/v1/auth/logout", json={"x": 1}, headers=_h(a.access_token))
    assert r.status_code == 422
