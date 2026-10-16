"""PUT /users/{id}/roles: owner floor, RBAC, audit, notify (QA #1648 d2)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.api.users import make_users_router
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import SessionNotFound, StepUpRequired
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.storage.errors import WriteAheadTimeout

OWNER = uuid.uuid4()
TARGET = uuid.uuid4()
_Hook = Callable[[frozenset[str]], Awaitable[None]]


class _Emitter:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail:
            raise AuditUnavailable("WAL unwritable")
        self.calls.append({"action": action, **kw})


class _Store:
    def __init__(self, roles: set[str], owners: int) -> None:
        self.roles = frozenset(roles)
        self.owners = owners

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        return self.roles

    async def count_active_owners(self) -> int:
        return self.owners

    async def apply_roles(
        self, user_id: uuid.UUID, roles: frozenset[str], *, actor: uuid.UUID, audit: _Hook
    ) -> bool:
        assert_owner_floor(
            current_roles=self.roles, new_roles=roles, active_owner_count=self.owners
        )
        await audit(self.roles)  # write-ahead: a refused audit leaves the roles untouched
        self.roles = roles
        return True


class _Resolver:
    def __init__(self, snap: PrincipalSnapshot | None) -> None:
        self.snap = snap

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return self.snap


class _Notifier:
    def __init__(self) -> None:
        self.users: list[uuid.UUID] = []

    async def roles_changed(self, user_id: uuid.UUID) -> None:
        self.users.append(user_id)


class _StepUp:
    def __init__(self, elevated: bool) -> None:
        self.elevated = elevated
        self.pending: list[tuple[str, str]] = []

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        if not self.elevated:
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> StepUpChallenge:
        self.pending.append((session_id, action_class))
        return StepUpChallenge(uuid.uuid4(), action_class, datetime.now(UTC) + CHALLENGE_WINDOW)


class _Sessions:
    async def authenticate_access_token(self, token: str) -> Any:
        if token != "tok":  # noqa: S105
            raise SessionNotFound("x")
        return SimpleNamespace(id=uuid.uuid4(), user_id=OWNER)


class _Auth:
    step_up_is_active = True
    sessions_is_active = True

    def __init__(self, elevated: bool) -> None:
        self.step_up = _StepUp(elevated)
        self.sessions = _Sessions()


def _client(
    store: _Store,
    snap: PrincipalSnapshot | None,
    em: _Emitter,
    n: _Notifier,
    *,
    elevated: bool = True,
):
    app = FastAPI()
    app.include_router(make_users_router(store, em, _Resolver(snap), n, auth=_Auth(elevated)))
    return TestClient(app, headers={"Authorization": "Bearer tok"})


def test_put_roles_without_elevation_is_step_up_required_and_no_change() -> None:
    store, em, n = _Store({"viewer"}, 2), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n, elevated=False).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager"]}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "step_up_required"
    assert r.json()["action_class"] == "users"
    assert store.roles == {"viewer"}
    assert n.users == []
    assert "roles.grant" not in {c["action"] for c in em.calls}


def test_put_roles_manager_forbidden_before_step_up() -> None:
    store, em, n = _Store({"viewer"}, 1), _Emitter(), _Notifier()
    r = _client(store, _manager(), em, n, elevated=False).put(
        f"/users/{TARGET}/roles", json={"roles": ["owner"]}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_put_roles_without_auth_wired_fails_closed() -> None:
    app = FastAPI()
    app.include_router(
        make_users_router(_Store({"viewer"}, 2), _Emitter(), _Resolver(_admin()), _Notifier())
    )
    r = TestClient(app).put(f"/users/{TARGET}/roles", json={"roles": ["manager"]})
    assert r.status_code == 503
    assert r.json()["code"] == "service_unavailable"


def _admin() -> PrincipalSnapshot:
    return PrincipalSnapshot(OWNER, frozenset({"owner"}), frozenset(Permission))


def _manager() -> PrincipalSnapshot:
    return PrincipalSnapshot(OWNER, frozenset({"manager"}), frozenset({Permission.ORDERS_READ}))


def test_put_roles_last_owner_demotion_is_rejected() -> None:
    store, em, n = _Store({"owner"}, 1), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 409
    assert store.roles == {"owner"}
    assert n.users == []


def test_put_roles_owner_demotion_allowed_when_another_owner_exists() -> None:
    store, em, n = _Store({"owner"}, 2), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 200
    assert store.roles == {"viewer"}
    assert n.users == [TARGET]
    assert {c["action"] for c in em.calls} == {"roles.grant", "roles.revoke"}


def test_put_roles_manager_forbidden_and_denial_audited() -> None:
    store, em, n = _Store({"viewer"}, 1), _Emitter(), _Notifier()
    r = _client(store, _manager(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["owner"]})
    assert r.status_code == 403
    assert em.calls[0]["action"] == "rbac.denied"
    assert store.roles == {"viewer"}


def test_put_roles_unauthenticated_is_401_and_unwired_is_501() -> None:
    em, n = _Emitter(), _Notifier()
    assert (
        _client(_Store({"viewer"}, 1), None, em, n)
        .put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
        .status_code
        == 401
    )
    app = FastAPI()
    app.include_router(make_users_router(None, em, None, n))
    assert TestClient(app).put(f"/users/{TARGET}/roles", json={"roles": ["x"]}).status_code == 501


def test_put_roles_rejects_unknown_role() -> None:
    r = _client(_Store({"viewer"}, 1), _admin(), _Emitter(), _Notifier()).put(
        f"/users/{TARGET}/roles", json={"roles": ["root"]}
    )
    assert r.status_code == 400


def test_put_roles_registry_pushes_permission_change_to_live_socket() -> None:
    import asyncio

    from candleviewer.ws.permissions import ConnectionAuthz, ConnectionRegistry

    viewer = PrincipalSnapshot(TARGET, frozenset({"viewer"}), frozenset({Permission.ORDERS_WRITE}))
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset())

    reg = ConnectionRegistry(resolve, lambda: 1)
    reg.register(ConnectionAuthz(viewer), send)
    asyncio.run(reg.roles_changed(TARGET))
    assert sent[0]["t"] == "permission_change"
    assert sent[0]["p"]["permissions"] == []


def test_put_roles_endpoint_enforces_owner_floor_even_if_store_does_not() -> None:
    """Contract: the endpoint guards the floor itself; a store that skips
    the check (e.g. a naive implementation) cannot demote the last owner."""

    class _NaiveStore(_Store):
        async def apply_roles(
            self, user_id: uuid.UUID, roles: frozenset[str], *, actor: uuid.UUID, audit: _Hook
        ) -> bool:
            self.roles = roles
            return True

    store, em, n = _NaiveStore({"owner"}, 1), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 409
    assert store.roles == {"owner"}
    assert n.users == []


def test_put_roles_conflict_is_audited_and_no_role_change_audit_on_failure() -> None:
    store, em, n = _Store({"owner"}, 1), _Emitter(), _Notifier()
    _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    actions = [c["action"] for c in em.calls]
    assert actions == ["rbac.denied"]
    assert "roles.grant" not in actions and "roles.revoke" not in actions


def test_put_roles_missing_user_writes_no_role_audit() -> None:
    class _Gone(_Store):
        async def apply_roles(
            self, user_id: uuid.UUID, roles: frozenset[str], *, actor: uuid.UUID, audit: _Hook
        ) -> bool:
            return False

    em = _Emitter()
    r = _client(_Gone({"viewer"}, 1), _admin(), em, _Notifier()).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager"]}
    )
    assert r.status_code == 404
    assert em.calls == []


def test_ws_gateway_hooks_auth_ok_sub_check_and_live_permission_change() -> None:
    import asyncio

    from candleviewer.ws.permissions import (
        ConnectionAuthz,
        ConnectionRegistry,
        auth_ok_payload,
        close_connection,
        handle_sub,
    )

    viewer = PrincipalSnapshot(TARGET, frozenset({"viewer"}), frozenset({Permission.ORDERS_READ}))
    sent: list[dict[str, Any]] = []
    perms = [viewer.permissions]  # the identity store; the role change below empties it

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset({"viewer"}), perms[0])

    async def scenario() -> None:
        reg = ConnectionRegistry(resolve, lambda: 1)
        snap = await reg.resolve(TARGET)  # the gateway's SR-189 path: read, register, re-check
        authz = ConnectionAuthz(snap.principal, reg.services, version=snap.version)
        reg.register(authz, send)
        await reg.recheck(authz)
        assert auth_ok_payload(authz.principal)["permissions"] == ["orders:read"]
        acc = str(uuid.uuid4())
        orders = {"ch": "orders", "opts": {"exchange_account_ids": [acc]}}
        viewer_grants = PrincipalSnapshot(
            TARGET,
            frozenset({"viewer"}),
            frozenset({Permission.ORDERS_READ}),
            (AccountGrant(uuid.UUID(acc), True, False, False),),
        )
        authz.principal = viewer_grants
        await handle_sub(authz, {"id": "s", "p": {"topics": [orders, {"ch": "bars.X"}]}}, send)
        res = sent[-1]["p"]["results"]
        assert [(r["ch"], r["ok"]) for r in res] == [("orders", True), ("bars.X", False)]
        sent.clear()
        store = _Store({"viewer"}, 2)
        app = FastAPI()
        app.include_router(
            make_users_router(store, _Emitter(), _Resolver(_admin()), reg, auth=_Auth(True))
        )
        perms[0] = frozenset()
        await reg.roles_changed(TARGET)
        assert [f["t"] for f in sent] == ["permission_change", "revoked"]
        close_connection(reg, authz)
        sent.clear()
        await reg.roles_changed(TARGET)
        assert sent == []

    asyncio.run(scenario())


def test_make_users_router_requires_audit_emitter_and_notifier() -> None:
    import pytest

    with pytest.raises(TypeError, match="required"):
        make_users_router(None, None, None, _Notifier())  # type: ignore[arg-type]  # the point
    with pytest.raises(TypeError, match="required"):
        make_users_router(None, _Emitter(), None, None)  # type: ignore[arg-type]  # the point


def test_put_roles_non_json_body_is_400() -> None:
    em = _Emitter()
    r = _client(_Store({"viewer"}, 1), _admin(), em, _Notifier()).put(
        f"/users/{TARGET}/roles", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400
    assert em.calls == []


def test_put_roles_unknown_user_is_404_before_any_change() -> None:
    class _Unknown(_Store):
        async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
            return None

    em, n = _Emitter(), _Notifier()
    r = _client(_Unknown({"viewer"}, 1), _admin(), em, n).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager"]}
    )
    assert r.status_code == 404
    assert em.calls == [] and n.users == []


def test_put_roles_audit_records_before_and_after_role_sets() -> None:
    store, em, n = _Store({"viewer", "manager"}, 1), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager", "owner"]}
    )
    assert r.status_code == 200
    by_action = {c["action"]: c for c in em.calls}
    assert set(by_action) == {"roles.grant", "roles.revoke"}
    for call in by_action.values():
        assert call["before_state"] == {"roles": ["manager", "viewer"]}
        assert call["after_state"] == {"roles": ["manager", "owner"]}
    assert by_action["roles.grant"]["reason"] == "owner"
    assert by_action["roles.revoke"]["reason"] == "viewer"


def test_put_roles_owner_floor_denial_records_before_and_requested_roles() -> None:
    store, em = _Store({"owner"}, 1), _Emitter()
    r = _client(store, _admin(), em, _Notifier()).put(
        f"/users/{TARGET}/roles", json={"roles": ["viewer"]}
    )
    assert r.status_code == 409
    (call,) = em.calls
    assert call["reason"] == "owner_floor"
    assert call["before_state"] == {"roles": ["owner"]}
    assert call["after_state"] == {"roles": ["viewer"]}


def test_put_roles_bad_bearer_is_401_with_code() -> None:
    c = _client(_Store({"viewer"}, 2), _admin(), _Emitter(), _Notifier())
    r = c.put(
        f"/users/{TARGET}/roles",
        json={"roles": ["manager"]},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


# -- SR-125 / #2117: `authz_denied_total` on the real route -------------------------------------


def _users_write_denied() -> float:
    labels = {"permission": Permission.USERS_WRITE.value}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


def test_put_roles_manager_forbidden_moves_authz_denied_total_with_the_audit_row() -> None:
    store, em, n = _Store({"viewer"}, 1), _Emitter(), _Notifier()
    before = _users_write_denied()
    r = _client(store, _manager(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["owner"]})
    assert r.status_code == 403
    assert [c["action"] for c in em.calls] == ["rbac.denied"]
    assert _users_write_denied() == before + 1


def test_put_roles_owner_floor_conflict_is_audited_but_is_not_a_permission_denial() -> None:
    store, em, n = _Store({"owner"}, 1), _Emitter(), _Notifier()
    before = _users_write_denied()
    r = _client(store, _admin(), em, n).put(f"/users/{TARGET}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 409
    assert [c["action"] for c in em.calls] == ["rbac.denied"]  # audited as a denial ...
    assert _users_write_denied() == before  # ... but the permission check passed


def test_put_roles_step_up_challenge_is_not_a_permission_denial() -> None:
    store, em, n = _Store({"viewer"}, 2), _Emitter(), _Notifier()
    before = _users_write_denied()
    r = _client(store, _admin(), em, n, elevated=False).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager"]}
    )
    assert (r.status_code, r.json()["code"]) == (403, "step_up_required")
    assert _users_write_denied() == before


def test_role_change_rejects_self_target() -> None:
    """SR-055 / threat U4: even with another owner present, no one changes their own roles."""
    store, em, n = _Store({"owner"}, 2), _Emitter(), _Notifier()
    r = _client(store, _admin(), em, n).put(f"/users/{OWNER}/roles", json={"roles": ["viewer"]})
    assert r.status_code == 403 and r.json()["reason"] == "self_target"
    assert store.roles == {"owner"} and n.users == []
    assert [(c["action"], c["reason"]) for c in em.calls] == [("rbac.denied", "self_target")]


def test_put_roles_audit_unavailable_rolls_back_with_503() -> None:
    """C-2.9 write-ahead: the role change happens only if its audit record was written."""
    store, n = _Store({"viewer"}, 2), _Notifier()
    r = _client(store, _admin(), _Emitter(fail=True), n).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager"]}
    )
    assert r.status_code == 503 and store.roles == {"viewer"} and n.users == []


def test_put_roles_write_ahead_timeout_answers_503_with_nothing_changed() -> None:
    """#2510: the store bounds its write-ahead hook under the locks; a timeout rolled back."""

    class _Hung(_Store):
        async def apply_roles(self, *_a: Any, **_k: Any) -> bool:
            raise WriteAheadTimeout("write-ahead audit exceeded 5.0 s")

    store, n = _Hung({"viewer"}, 2), _Notifier()
    r = _client(store, _admin(), _Emitter(), n).put(
        f"/users/{TARGET}/roles", json={"roles": ["manager"]}
    )
    assert r.status_code == 503 and store.roles == {"viewer"} and n.users == []


def test_put_roles_other_timeout_is_not_answered_as_nothing_changed() -> None:
    """#2510: only the store's `WriteAheadTimeout` means rolled back; a driver or commit
    `TimeoutError` (outcome unknown) is not mapped to 503 'nothing was changed'."""

    class _CommitTimeout(_Store):
        async def apply_roles(self, *_a: Any, **_k: Any) -> bool:
            raise TimeoutError

    c = _client(_CommitTimeout({"viewer"}, 2), _admin(), _Emitter(), _Notifier())
    with pytest.raises(TimeoutError):
        c.put(f"/users/{TARGET}/roles", json={"roles": ["manager"]})
