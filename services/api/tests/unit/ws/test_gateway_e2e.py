"""End-to-end through the real `create_app()` (QA #1648 d1, PR #1654 review):
auth_ok permissions -> forbidden sub rejected -> role change via the API ->
permission_change pushed and the now-forbidden subscription dropped."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from candleviewer.app import create_app
from candleviewer.auth.errors import SessionNotFound, StepUpRequired
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot

ADMIN = uuid.uuid4()
MGR = uuid.uuid4()
ACC = uuid.uuid4()
OTHER_ACC = uuid.uuid4()
_PERMS = {
    "owner": frozenset(Permission),
    "manager": frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ}),
    "viewer": frozenset({Permission.MARKETDATA_READ}),
}


class _World:
    def __init__(self) -> None:
        self.roles: dict[uuid.UUID, frozenset[str]] = {
            ADMIN: frozenset({"owner"}),
            MGR: frozenset({"manager"}),
        }
        self.grants: dict[uuid.UUID, tuple[AccountGrant, ...]] = {
            MGR: (AccountGrant(ACC, True, True, False),)
        }
        self.audit: list[dict[str, Any]] = []

    async def load(self, uid: uuid.UUID) -> PrincipalSnapshot:
        roles = self.roles.get(uid, frozenset())
        perms = frozenset().union(*(_PERMS[r] for r in roles)) if roles else frozenset()
        return PrincipalSnapshot(uid, roles, perms, self.grants.get(uid, ()))

    # UserRoleStore
    async def get_roles(self, uid: uuid.UUID) -> frozenset[str] | None:
        return self.roles.get(uid)

    async def count_active_owners(self) -> int:
        return sum("owner" in r for r in self.roles.values())

    async def apply_roles(self, uid: uuid.UUID, roles: frozenset[str]) -> bool:
        assert_owner_floor(
            current_roles=self.roles[uid],
            new_roles=roles,
            active_owner_count=await self.count_active_owners(),
        )
        self.roles[uid] = roles
        return True

    # SnapshotResolver: the HTTP caller is always the admin here.
    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return PrincipalSnapshot(ADMIN, self.roles[ADMIN], frozenset(Permission))

    async def emit(self, action: str, **kw: Any) -> None:
        self.audit.append({"action": action, **kw})


class _StepUp:
    """Stand-in for the DB-backed StepUpService (not wired without a database)."""

    def __init__(self) -> None:
        self.elevated = False

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        if not self.elevated:
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> None:
        return None

    async def assert_writable(self, session_id: str) -> None:
        return None


class _Sessions:
    async def authenticate_access_token(self, token: str) -> Any:
        if token != "admin-token":  # noqa: S105
            raise SessionNotFound("x")
        return SimpleNamespace(id=uuid.uuid4(), user_id=ADMIN)


async def _authenticate(presented: str) -> tuple[str, uuid.UUID]:
    if presented != "mgr-token":
        raise PermissionError("bad token")
    return "sess-1", MGR


@pytest.fixture
def env() -> tuple[TestClient, _World]:
    w = _World()
    app = create_app(
        snapshot_loader=w.load,
        user_role_store=w,
        principal_resolver=w,
        ws_authenticate=_authenticate,
    )
    app.state.app_context.audit._writer = w  # stand-in for the started AuditWriter
    # The router holds this same AuthService: wire the step-up/session seams.
    auth: Any = app.state.app_context.auth
    auth._sessions = _Sessions()
    auth._step_up = _StepUp()
    client = TestClient(
        app, client=("127.0.0.1", 50000), headers={"Authorization": "Bearer admin-token"}
    )
    return client, w


def _elevate(client: TestClient) -> None:
    """Complete step-up for action class "users" on the admin session."""
    client.app.state.app_context.auth._step_up.elevated = True  # type: ignore[attr-defined]  # Starlette app typed as ASGIApp


def _sub(ws: Any, ch: str, accounts: list[uuid.UUID] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"ch": ch}
    if accounts is not None:
        entry["opts"] = {"exchange_account_ids": [str(a) for a in accounts]}
    ws.send_json({"t": "sub", "id": ch, "p": {"topics": [entry]}})
    result: dict[str, Any] = ws.receive_json()["p"]["results"][0]
    return result


def test_ws_e2e_permissions_sub_check_and_live_role_change(env: tuple[TestClient, _World]) -> None:
    client, w = env
    with client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        assert ws.receive_json()["t"] == "welcome"
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "mgr-token"}})
        ok = ws.receive_json()
        assert ok["t"] == "auth_ok"
        assert ok["p"]["permissions"] == ["marketdata:read", "orders:read"]
        assert ok["p"]["account_scope"] == [str(ACC)]
        assert _sub(ws, "audit.all")["error"]["code"] == "unknown_topic"  # §10.2
        assert _sub(ws, "positions", [ACC])["error"]["code"] == "forbidden"  # no positions:read
        assert _sub(ws, "orders")["error"]["code"] == "account_scope_denied"  # account-less
        assert _sub(ws, "orders", [OTHER_ACC])["error"]["code"] == "account_scope_denied"
        assert _sub(ws, "orders", [ACC])["ok"] is True
        assert _sub(ws, "book.BTCUSDT.50")["ok"] is True

        _elevate(client)
        r = client.put(f"/users/{MGR}/roles", json={"roles": ["viewer"]})
        assert r.status_code == 200
        change = ws.receive_json()
        assert change["t"] == "permission_change"
        assert change["p"]["permissions"] == ["marketdata:read"]
        revoked = ws.receive_json()
        assert (revoked["t"], revoked["ch"]) == ("revoked", "orders")
        assert _sub(ws, "orders", [ACC])["error"]["code"] == "forbidden"
    assert {a["action"] for a in w.audit} >= {"roles.grant", "roles.revoke"}
    # #377: the gateway's audit sink is wired, so the denied subs are audited too.
    denied = [r for r in w.audit if r["action"] == "ws.subscribe.denied"]
    assert {r["reason"] for r in denied} == {"forbidden", "account_scope_denied"}
    for rec in (r for r in w.audit if r["action"].startswith("roles.")):
        assert rec["before_state"] == {"roles": ["manager"]}
        assert rec["after_state"] == {"roles": ["viewer"]}


def test_ws_e2e_bad_token_closes_4401_and_frames_before_auth_refused(
    env: tuple[TestClient, _World],
) -> None:
    client, _ = env
    with client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        assert ws.receive_json()["t"] == "welcome"
        ws.send_json({"t": "ping", "id": "p"})
        assert ws.receive_json()["t"] == "pong"
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.X"]}})
        assert ws.receive_json()["p"]["code"] == "not_authenticated"
        for _ in range(2):  # §4.3: attempts 1-2 get `err auth_failed`, the 3rd closes
            ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "nope"}})
            assert ws.receive_json()["p"]["code"] == "auth_failed"
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "nope"}})
        bye = ws.receive_json()
        assert bye["t"] == "bye" and bye["p"]["reason"] == "auth_failed"


def test_ws_e2e_roles_change_without_step_up_is_403_step_up_required(
    env: tuple[TestClient, _World],
) -> None:
    client, w = env
    r = client.put(f"/users/{MGR}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 403
    assert r.json()["code"] == "step_up_required"
    assert w.roles[MGR] == frozenset({"manager"})


def test_ws_e2e_last_owner_demotion_409_is_audited(env: tuple[TestClient, _World]) -> None:
    client, w = env
    _elevate(client)
    r = client.put(f"/users/{ADMIN}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 409
    assert [a["action"] for a in w.audit] == ["rbac.denied"]
    assert w.audit[0]["reason"] == "owner_floor"
    assert w.audit[0]["before_state"] == {"roles": ["owner"]}
    assert w.audit[0]["after_state"] == {"roles": ["viewer"]}


def test_ws_e2e_session_revocation_closes_socket(env: tuple[TestClient, _World]) -> None:
    client, _ = env
    hub = client.app.state.revocation_hub  # type: ignore[attr-defined]  # Starlette app typed as ASGIApp
    with client, client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        assert ws.receive_json()["t"] == "welcome"
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "mgr-token"}})
        assert ws.receive_json()["t"] == "auth_ok"
        ws.send_json({"t": "unsub", "id": "u", "p": {"topics": ["orders"]}})
        assert ws.receive_json()["t"] == "unsub_ok"
        assert client.portal.call(hub.revoke, "sess-1") == 1  # type: ignore[union-attr]  # portal set inside ctx
        assert ws.receive_json()["p"]["code"] == 4401


def test_ws_undeclared_path_is_refused_by_global_deny(env: tuple[TestClient, _World]) -> None:
    from fastapi import WebSocket
    from starlette.websockets import WebSocketDisconnect

    client, _ = env

    @client.app.websocket("/ws-undeclared")  # type: ignore[attr-defined]  # FastAPI app
    async def _rogue(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_json({"leak": True})

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws-undeclared") as ws:
            ws.receive_json()
    assert exc.value.code == 1008
