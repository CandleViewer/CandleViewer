"""PR #1638 review fixes: reuse-revocation propagation (US-ONB-009), write-ahead
session audit (C-2.9), Settings-injected origin allow-list and the
`/auth/refresh` rate limit. No DB/network; fake clock."""

from __future__ import annotations

import uuid
from typing import Any

from candleviewer.audit.models import Severity
from candleviewer.settings import Settings
from tests.csrf_helpers import arm_csrf
from tests.unit.api.test_sessions_router import _CSRF_CODEC, REFRESH_COOKIE, _Env, _h, _Writer


class _FlakyAudit:
    """Active for the route's entry check only; down by the time the
    write-ahead record is attempted (audit dies mid-request)."""

    def __init__(self) -> None:
        self.writer = _Writer()
        self._checks = 0

    @property
    def is_active(self) -> bool:
        self._checks += 1
        return self._checks == 1


def _refresh(env: _Env, token: str) -> Any:
    env.client.cookies.delete(REFRESH_COOKIE, path="/api/v1/auth")  # never replay the rotated one
    return env.client.post("/api/v1/auth/refresh", json={"refresh_token": token})


async def test_refresh_reuse_propagates_revocation_for_whole_family() -> None:
    env = _Env()
    m = await env.mint(uuid.uuid4())
    r1 = _refresh(env, m.refresh_token)
    assert r1.status_code == 200
    successor = await env.svc.authenticate_access_token(r1.json()["tokens"]["access_token"])
    assert _refresh(env, m.refresh_token).status_code == 401
    family = {str(m.session_id), str(successor.id)}
    assert {sid for sid, _ in env.revoked} == family
    assert {reason for _, reason in env.revoked} == {"rotation_reuse"}  # the service publishes
    reuse = [e for e in env.audit.writer.events if e["action"] == "auth.refresh_reuse_detected"]
    assert len(reuse) == 1
    assert reuse[0]["severity"] == Severity.CRITICAL
    after = await env.repo.find_by_id(str(successor.id))
    assert after is not None
    assert after.revoked_reason == "rotation_reuse"


async def test_refresh_audit_unavailable_is_503_and_no_rotation() -> None:
    env = _Env(audit=_FlakyAudit())
    m = await env.mint(uuid.uuid4())
    r = _refresh(env, m.refresh_token)
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    rec = await env.repo.find_by_id(str(m.session_id))
    assert rec is not None
    assert not rec.is_revoked


async def test_logout_audit_unavailable_is_503_and_no_revocation() -> None:
    env = _Env(audit=_FlakyAudit())
    m = await env.mint(uuid.uuid4())
    assert env.client.post("/api/v1/auth/logout", headers=_h(m.access_token)).status_code == 503
    assert env.revoked == []
    rec = await env.repo.find_by_id(str(m.session_id))
    assert rec is not None
    assert not rec.is_revoked


async def test_revoke_other_session_audit_unavailable_is_503_and_no_revocation() -> None:
    env = _Env(audit=_FlakyAudit())
    user = uuid.uuid4()
    a = await env.mint(user)
    b = await env.mint(user)
    r = env.client.delete(f"/api/v1/me/sessions/{b.session_id}", headers=_h(a.access_token))
    assert r.status_code == 503
    rec = await env.repo.find_by_id(str(b.session_id))
    assert rec is not None
    assert not rec.is_revoked


def _record_order(env: _Env) -> list[str]:
    order: list[str] = []
    writer = env.audit.writer
    real_emit, real_revoke = writer.emit, env.repo.revoke

    async def emit(action: str, **kw: Any) -> None:
        order.append(f"audit:{action}")
        await real_emit(action, **kw)

    async def revoke(session_id: str, **kw: Any) -> Any:
        order.append(f"revoke:{kw['reason']}")
        return await real_revoke(session_id, **kw)

    writer.emit = emit  # type: ignore[method-assign]  # recording fake for call order
    env.repo.revoke = revoke  # type: ignore[method-assign]  # recording fake for call order
    return order


async def test_refresh_audit_record_precedes_rotation() -> None:
    env = _Env()
    m = await env.mint(uuid.uuid4())
    order = _record_order(env)
    assert _refresh(env, m.refresh_token).status_code == 200
    assert order == ["audit:auth.session_refreshed", "revoke:rotated"]


async def test_logout_audit_record_precedes_revocation() -> None:
    env = _Env()
    m = await env.mint(uuid.uuid4())
    order = _record_order(env)
    assert env.client.post("/api/v1/auth/logout", headers=_h(m.access_token)).status_code == 204
    assert order == ["audit:auth.logout", "audit:auth.session_revoked", "revoke:logout"]
    assert env.revoked == [(str(m.session_id), "logout")]


async def test_refresh_n_plus_one_within_window_is_429_with_retry_after() -> None:
    env = _Env(throttle_max=3)
    minted = [await env.mint(uuid.uuid4()) for _ in range(4)]

    def refresh_as(m: Any) -> Any:  # each client holds its own session's SR-041 token
        arm_csrf(env.client, _CSRF_CODEC, m.session_id)
        return _refresh(env, m.refresh_token)

    for m in minted[:3]:
        assert refresh_as(m).status_code == 200
    env.t = 15.0
    r = refresh_as(minted[3])
    assert r.status_code == 429
    assert r.headers["retry-after"] == "45"
    env.t = 61.0  # window elapsed; the refused attempt burned no token
    assert refresh_as(minted[3]).status_code == 200


async def test_refresh_per_session_budget_is_429() -> None:
    env = _Env(throttle_max=2)
    m = await env.mint(uuid.uuid4())
    assert _refresh(env, m.refresh_token).status_code == 200
    assert _refresh(env, m.refresh_token).status_code == 401  # reuse, 2nd for session
    r = _refresh(env, m.refresh_token)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1


async def test_allowed_origin_from_settings_permits_cookie_refresh() -> None:
    env = _Env(origins=Settings(allowed_origins="http://app.example").allowed_origin_set)
    m = await env.mint(uuid.uuid4())
    r = env.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": "http://app.example/"},
    )
    assert r.status_code == 200
    assert r.json()["tokens"]["refresh_token"] is None


def test_settings_allowed_origins_parses_csv() -> None:
    s = Settings(allowed_origins=" http://a.example/ ,,http://b.example")
    assert s.allowed_origin_set == frozenset({"http://a.example", "http://b.example"})
    assert Settings().allowed_origin_set == frozenset()


async def test_refresh_edge_inputs() -> None:
    env = _Env()
    post = env.client.post
    assert post("/api/v1/auth/refresh", content=b"{bad").status_code == 422
    assert post("/api/v1/auth/refresh", json={"x": 1}).status_code == 422
    assert post("/api/v1/auth/refresh", json={}).status_code == 401
    assert post("/api/v1/auth/refresh", json={"refresh_token": "unknown"}).status_code == 401
    m = await env.mint(uuid.uuid4())
    await env.svc.revoke(str(m.session_id), reason="logout")
    assert _refresh(env, m.refresh_token).status_code == 401
    r = env.client.post(
        "/api/v1/auth/refresh", cookies={REFRESH_COOKIE: m.refresh_token}
    )  # cookie without Origin => CSRF refusal
    assert r.status_code == 403


async def test_session_list_and_logout_edge_inputs() -> None:
    env = _Env()
    m = await env.mint(uuid.uuid4())
    h = _h(m.access_token)
    assert env.client.get("/api/v1/auth/sessions?cursor=x", headers=h).status_code == 422
    assert env.client.get("/api/v1/auth/sessions?cursor=-1", headers=h).status_code == 422
    logout = env.client.post
    assert logout("/api/v1/auth/logout", content=b"{bad", headers=h).status_code == 422
    assert logout("/api/v1/auth/logout", json={"all_sessions": 1}, headers=h).status_code == 422
    assert env.client.get("/api/v1/auth/session", headers=h).status_code == 200
    r = env.client.delete(f"/api/v1/me/sessions/{m.session_id}", headers=h)
    assert r.status_code == 204
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert env.revoked == [(str(m.session_id), "user_revoked")]


async def test_session_info_exposes_step_up_expires_at() -> None:
    from datetime import UTC, datetime, timedelta

    env = _Env()
    m = await env.mint(uuid.uuid4())
    h = _h(m.access_token)
    assert env.client.get("/api/v1/auth/session", headers=h).json()["step_up_expires_at"] is None
    until = datetime.now(UTC) + timedelta(minutes=4)
    await env.repo.save_step_up_state(
        str(m.session_id),
        elevations={"users": until, "pending:keys": until + timedelta(minutes=1)},
        failures=0,
        readonly_until=None,
    )
    body = env.client.get("/api/v1/auth/session", headers=h).json()
    assert datetime.fromisoformat(body["step_up_expires_at"]) == until
