"""#2752 through the real `create_app()` wiring.

The owner invite routes (`POST /users`, invite re-issue / revoke) rely on the
step-up guard alone (`api/invites.py`), so they are what a guard bypass would
expose:

- served under an ASGI `root_path` (`uvicorn --root-path /api/v1`, which puts
  the prefix in the scope `path`), an owner without a fresh step-up is still
  refused with `403 step_up_required`;
- with sessions wired but step-up not (no user repository: a wiring fault),
  the dangerous write answers 503 before the handler runs instead of minting
  an invite unchecked.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.app import create_app
from candleviewer.auth.service import AuthService
from tests.unit.api.test_invites_create_app_e2e import (
    _BODY,
    _OWNER_PERMS,
    _PW,
    _h,
    _login,
    _World,
)
from tests.unit.auth.auth_fakes import FullUsers
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_ROOT = "/api/v1"  # the contract `servers` base


async def _world(
    monkeypatch: pytest.MonkeyPatch, *, with_user_repository: bool, root_path: str = ""
) -> _World:
    """`test_invites_create_app_e2e.world`, with the user repository optional
    (step-up needs it; sessions, MFA and invites do not) and a root path."""
    w = _World()
    w.auth = AuthService(
        w.users if with_user_repository else None,
        mfa_repository=FakeMfaRepository(),
        totp_encryption_key=os.urandom(32),
        recovery_code_hmac_key=os.urandom(32),
        session_repository=FakeSessionRepository(),
        invite_repository=w.invites,
        pepper="test-pepper",
        clock=w.clock,
    )
    monkeypatch.setattr(app_module, "build_auth_service", lambda *_a, **_k: w.auth)
    app = create_app(principal_resolver=w.resolver)
    ctx = app.state.app_context
    await w.auth.start(ctx)
    ctx.audit._writer = w.audit  # the lazy emitter resolves `audit.writer` per call
    w.codec = app.state.csrf_codec
    w.client = TestClient(app, client=("127.0.0.1", 50000), root_path=root_path)
    return w


async def test_invite_create_under_root_path_still_needs_step_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await _world(monkeypatch, with_user_repository=True, root_path=_ROOT)
    owner = await _login(w, "owner", _OWNER_PERMS)
    denied = w.client.post(f"{_ROOT}/users", headers=_h(owner), json=_BODY)
    assert denied.status_code == 403 and denied.json()["code"] == "step_up_required"
    assert not w.invites.rows and not w.audit.of("users.invited")
    body = {"code": w.code(owner), "password": _PW}
    ok = w.client.post(f"{_ROOT}/auth/step-up", headers=_h(owner), json=body)
    assert ok.status_code == 200 and ok.json()["action_class"] == "users"
    assert w.client.post(f"{_ROOT}/users", headers=_h(owner), json=_BODY).status_code == 201


async def test_invite_create_fails_closed_when_sessions_are_wired_without_step_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await _world(monkeypatch, with_user_repository=False)
    w.auth._repository = FullUsers()  # #2295: after `start`, so only the guard reads it
    assert w.auth.sessions_is_active and w.auth.invites_is_active
    assert not w.auth.step_up_is_active  # the wiring fault
    owner = await _login(w, "owner", _OWNER_PERMS)
    r = w.client.post("/users", headers=_h(owner), json=_BODY)
    assert r.status_code == 503 and r.json()["code"] == "service_unavailable"
    assert not w.invites.rows and not w.audit.of("users.invited")
    # Not an outage: the owner's non-dangerous read is served as before.
    assert w.client.get("/users/invites", headers=_h(owner)).status_code == 200
