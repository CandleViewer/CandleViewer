"""#2492 composition guard: the deployed `create_app()` (no injected seams) on the real backend
serves the role-change, invite and owner TOTP-reset routes through `SessionSnapshotResolver` and
`SqlAlchemyUserRoleStore`: every cell answers as `tests/contract/rbac/matrix.yaml` says and an
owner is never refused with the fail-closed 501/503. Only the SQL edges of those real classes and
the session/step-up/invite services are faked (the RBAC pack's seams; no Postgres, no network)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.settings import Settings
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore
from tests.contract.rbac import rbac_harness as rbac
from tests.csrf_helpers import csrf_headers

_ROWS = yaml.safe_load(rbac.MATRIX_PATH.read_text(encoding="utf-8"))["operations"]
#: Derived, not listed: every served (`executed`) operation gated by `users:write` alone.
OWNER_ROUTES = tuple(
    key
    for key, row in _ROWS.items()
    if row["state"] == "executed" and row["permissions"] == ["users:write"]
)


def _delegate(target: Any, name: str) -> Callable[..., Any]:
    return lambda _self, *args, **kwargs: getattr(target, name)(*args, **kwargs)


@pytest.fixture(scope="module")
def deployed() -> Iterator[SimpleNamespace]:
    identity, users = rbac._Identity(rbac.load_contract()), rbac.UserStore()
    audit = rbac._AuditSink()
    real = Settings(
        storage_backend="real",
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )
    with pytest.MonkeyPatch.context() as mp:
        for name in ("user", "session_info"):
            mp.setattr(SqlAlchemyIdentityProvider, name, _delegate(identity, name))
        for name in ("get_roles", "count_active_owners", "apply_roles"):
            mp.setattr(SqlAlchemyUserRoleStore, name, _delegate(users, name))
        app = appmod.create_app(real)  # nothing injected: the deployed composition
        ctx = app.state.app_context
        ctx.audit._writer = audit
        ctx.auth._sessions, ctx.auth._step_up = rbac._Sessions(), rbac._StepUp()
        ctx.auth._invites = rbac._Invites()
        client = TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
        yield SimpleNamespace(client=client, users=users, audit=audit)


def _headers(client: TestClient, actor: str) -> dict[str, str]:
    codec = client.app.state.csrf_codec  # type: ignore[attr-defined]  # the FastAPI app
    if actor == "unauthenticated":
        return csrf_headers(codec)  # well-formed SR-041 pair, no session
    sid = uuid.uuid5(rbac.user_id_of(actor), "session")
    return {"Authorization": f"Bearer {rbac.token_of(actor)}", **csrf_headers(codec, sid)}


@pytest.mark.parametrize("actor", rbac.ACTORS)
@pytest.mark.parametrize("key", OWNER_ROUTES)
def test_deployed_app_owner_routes_answer_as_the_matrix_says(
    deployed: SimpleNamespace, key: str, actor: str
) -> None:
    """Branches on the cell's reviewed outcome class on purpose (allow / CSRF / 401-403)."""
    method, path = key.split(" ", 1)
    body: dict[str, Any] | None = {} if method in ("POST", "PUT") else None
    resp = deployed.client.request(
        method, rbac.fill_path(path), json=body, headers=_headers(deployed.client, actor)
    )
    expected = _ROWS[key]["outcomes"][actor]
    if expected == "allow":  # authorised AND served by the wired backend
        assert resp.status_code not in (401, 403, 500, 501, 503), (key, resp.text)
    elif actor == "unauthenticated" and method != "GET":  # SR-041 refuses before routing
        assert resp.status_code == 403 and resp.json()["code"] == "csrf_token_invalid"
    else:
        assert resp.status_code == int(expected), (key, actor, resp.text)


def test_deployed_app_role_change_reaches_the_store_and_is_audited(
    deployed: SimpleNamespace,
) -> None:
    viewer = rbac.user_id_of("viewer")
    headers = _headers(deployed.client, "owner")
    try:
        resp = deployed.client.put(
            f"/users/{viewer}/roles", json={"roles": ["manager"]}, headers=headers
        )
        assert resp.status_code == 200 and resp.json()["roles"] == ["manager"]
        assert deployed.users.roles[viewer] == frozenset({"manager"})
        assert {"roles.grant", "roles.revoke"} <= {r["action"] for r in deployed.audit.records}
    finally:
        deployed.users.roles.update(deployed.users.initial_roles)


def test_deployed_app_refuses_a_self_target_role_change(deployed: SimpleNamespace) -> None:
    owner = rbac.user_id_of("owner")
    headers = _headers(deployed.client, "owner")
    r = deployed.client.put(f"/users/{owner}/roles", json={"roles": ["viewer"]}, headers=headers)
    assert r.status_code == 403 and r.json()["reason"] == "self_target"  # SR-055
    assert deployed.users.roles == deployed.users.initial_roles


def test_deployed_app_refuses_unauditable_owner_actions_without_changing_anything(
    deployed: SimpleNamespace,
) -> None:
    audit = deployed.client.app.state.app_context.audit
    writer, audit._writer = audit._writer, None  # the audit service is not running
    headers = _headers(deployed.client, "owner")
    viewer = rbac.user_id_of("viewer")
    try:
        put = deployed.client.put(
            f"/users/{viewer}/roles", json={"roles": ["manager"]}, headers=headers
        )
        assert put.status_code == 503  # C-2.9 write-ahead: the change rolled back
        assert deployed.client.post("/users", json={}, headers=headers).status_code == 503
    finally:
        audit._writer = writer
    assert deployed.users.roles == deployed.users.initial_roles


def test_fake_backend_keeps_the_owner_routes_fail_closed() -> None:
    assert appmod.build_user_role_store(Settings()) is None
    client = TestClient(appmod.create_app(Settings()), client=("127.0.0.1", 50000))
    resp = client.get("/users/invites", headers={"Authorization": "Bearer tok-owner"})
    assert resp.status_code == 501


def test_owner_routes_derived_from_the_matrix_cover_the_issue_scope() -> None:
    """Guard for the derived parametrisation: it can never silently become empty."""
    named = {"PUT /users/{userId}/roles", "POST /users", "GET /users/invites"}  # by #2492
    assert named <= set(OWNER_ROUTES) and "POST /users/{userId}/mfa/reset" in OWNER_ROUTES
