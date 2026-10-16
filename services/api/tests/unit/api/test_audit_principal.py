"""QA #1596: session-backed principal resolver + HTTP RBAC (401 / 403 / 200)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.auth.errors import SessionIdleLocked, SessionNotFound, SessionRevoked
from candleviewer.net import CidrAllowList, MeshOnlyMiddleware
from tests.unit.api.test_audit_router import _FakeAuditService

_OWNER = uuid.uuid4()
_MANAGER = uuid.uuid4()


class _Sessions:
    async def authenticate_access_token(self, token: str) -> Any:
        users = {"owner-tok": _OWNER, "mgr-tok": _MANAGER}
        if token not in users:
            raise SessionNotFound("nope")
        return SimpleNamespace(id=uuid.uuid4(), user_id=users[token])


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        owner = user_id == str(_OWNER)
        return {"username": "o" if owner else "m", "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"] if user_id == str(_OWNER) else ["accounts:read"]}


def _client() -> tuple[TestClient, _FakeAuditService]:
    svc = _FakeAuditService()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(), _Identity())
    app.include_router(make_audit_router(svc, resolver))
    return TestClient(app), svc


def test_audit_query_without_token_is_401() -> None:
    client, _ = _client()
    assert client.get("/admin/audit").status_code == 401


def test_audit_query_unknown_token_is_401() -> None:
    client, _ = _client()
    r = client.get("/admin/audit", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401


def test_audit_query_manager_is_403_and_denial_audited() -> None:
    client, svc = _client()
    r = client.get("/admin/audit", headers={"Authorization": "Bearer mgr-tok"})
    assert r.status_code == 403
    assert svc.writer_service.emitted[0][0] == "admin.audit_denied"


def test_audit_query_owner_is_200() -> None:
    client, _ = _client()
    r = client.get("/admin/audit", headers={"Authorization": "Bearer owner-tok"})
    assert r.status_code == 200


def test_verify_and_export_without_token_are_401() -> None:
    client, _ = _client()
    assert client.post("/admin/audit/verify", json={}).status_code == 401
    assert client.post("/admin/audit/export", json={}).status_code == 401


def test_verify_and_export_manager_are_403() -> None:
    client, _ = _client()
    h = {"Authorization": "Bearer mgr-tok"}
    assert client.post("/admin/audit/verify", json={}, headers=h).status_code == 403
    assert client.post("/admin/audit/export", json={}, headers=h).status_code == 403


def test_verify_owner_is_authorized() -> None:
    client, _ = _client()
    r = client.post("/admin/audit/verify", json={}, headers={"Authorization": "Bearer owner-tok"})
    assert r.status_code not in (401, 403, 501)


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "recorded"),
    [
        ("127.0.0.1", "203.0.113.9, 100.64.1.2", "100.64.1.2"),  # the configured proxy
        ("127.0.0.2", "100.64.1.2", "127.0.0.2"),  # another loopback peer: header ignored
    ],
)
def test_audit_denial_records_the_address_mesh_only_admitted(
    peer: str, forwarded_for: str, recorded: str
) -> None:
    """#2275: the principal's `ip` is MeshOnly's admitted address, not the proxy's."""
    svc = _FakeAuditService()
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(), _Identity())
    app.include_router(make_audit_router(svc, resolver))
    app.add_middleware(
        MeshOnlyMiddleware,
        allow_list=CidrAllowList(["100.64.0.0/10"]),
        trusted_proxy_header="x-forwarded-for",
        trusted_proxy_address="127.0.0.1",
    )
    headers = {"Authorization": "Bearer mgr-tok", "X-Forwarded-For": forwarded_for}
    r = TestClient(app, client=(peer, 50000)).get("/admin/audit", headers=headers)
    assert r.status_code == 403
    assert svc.writer_service.emitted[0][1]["actor_ip"] == recorded


def _resolver_client(sessions: Any, identity: Any) -> TestClient:
    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: sessions, identity)
    app.include_router(make_audit_router(_FakeAuditService(), resolver))
    return TestClient(app)


def _raising_sessions(exc: Exception) -> Any:
    class _S:
        async def authenticate_access_token(self, token: str) -> Any:
            raise exc

    return _S()


def test_revoked_session_is_401() -> None:
    c = _resolver_client(_raising_sessions(SessionRevoked("x")), _Identity())
    assert c.get("/admin/audit", headers={"Authorization": "Bearer t"}).status_code == 401


def test_idle_locked_session_is_401() -> None:
    c = _resolver_client(_raising_sessions(SessionIdleLocked("x")), _Identity())
    assert c.get("/admin/audit", headers={"Authorization": "Bearer t"}).status_code == 401


def test_non_active_user_is_401() -> None:
    class _Disabled(_Identity):
        async def user(self, user_id: str) -> dict[str, Any]:
            return {"username": "o", "status": "disabled"}

    c = _resolver_client(_Sessions(), _Disabled())
    assert c.get("/admin/audit", headers={"Authorization": "Bearer owner-tok"}).status_code == 401


def test_app_without_identity_provider_fails_closed_501() -> None:
    app = FastAPI()
    app.include_router(make_audit_router(_FakeAuditService(), None))
    r = TestClient(app).get("/admin/audit", headers={"Authorization": "Bearer owner-tok"})
    assert r.status_code == 501


# ---- #2083: owner-ness resolved via PrincipalSnapshot.is_owner -------------------


async def test_resolver_owner_role_resolves_is_owner_true() -> None:
    from candleviewer.api.audit_principal import _is_owner

    assert _is_owner(uuid.uuid4(), ["owner"]) is True
    assert _is_owner(uuid.uuid4(), ["manager"]) is False
    assert _is_owner(uuid.uuid4(), ["viewer"]) is False


def test_resolver_unknown_role_fails_closed_not_owner() -> None:
    from candleviewer.api.audit_principal import _is_owner

    assert _is_owner(uuid.uuid4(), ["owner", "superadmin"]) is False
