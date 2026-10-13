"""E09-S05 e2e through the real `create_app()` wiring (PR #1689 review).

`create_app()` is built with its production routers/middleware; only the
storage-facing seams are faked (auth repos, audit writer) - the same fake
backend the other create_app tests use. Real step-up middleware, real
`AuthService`/`SessionService`/`MfaService`/`InviteService`.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.app import create_app
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.invite_service import INVITE_TTL
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.csrf_helpers import csrf_headers
from tests.unit.api.test_step_up_router import _T0, _Clock
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_invite_service import GOOD_PW, FakeRepo

_BODY = {"email": "ann@example.com", "username": "annie", "roles": ["viewer"]}


class _Writer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["action"] == action]


class _Resolver:
    """Bearer token -> principal (stands in for the identity provider)."""

    def __init__(self) -> None:
        self.by_token: dict[str, PrincipalSnapshot] = {}

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        auth = request.headers.get("authorization", "")
        return self.by_token.get(auth.removeprefix("Bearer "))


_PW = "correct horse battery staple"


class _World:
    def __init__(self) -> None:
        self.clock = _Clock()
        self.clock.now = _T0
        self.invites = FakeRepo()
        self.users = FakeUserRepository()
        self.hasher = Hasher(pepper="test-pepper")
        self.audit = _Writer()
        self.resolver = _Resolver()
        self.seeds: dict[str, bytes] = {}
        self.client: TestClient
        self.codec: CsrfCodec
        self.auth: AuthService

    def code(self, token: str) -> str:
        return generate_code(self.seeds[token], time_step_for(self.clock.now.timestamp()))

    def elevate(self, token: str, **kw: Any) -> Any:
        return self.client.post(
            "/auth/step-up",
            headers=_h(token),
            json={"code": self.code(token), "password": _PW, **kw},
        )


#: access token -> SR-041 header/cookie pair bound to that token's session.
_CSRF: dict[str, dict[str, str]] = {}


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **_CSRF.get(token, {})}


async def _login(w: _World, role: str, perms: frozenset[Permission]) -> str:
    uid = uuid.uuid4()
    mfa = w.auth.mfa
    res = await mfa.enroll(
        str(uid), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name=role
    )
    b32 = res.secret_base32
    assert b32 is not None
    seed = base64.b32decode(b32 + "=" * (-len(b32) % 8))
    await mfa.confirm_enrollment(
        str(uid),
        method_id=str(res.method_id),
        code=generate_code(seed, time_step_for(w.clock.now.timestamp()) - 1),
    )
    w.users.add(make_user(password_hash=await w.hasher.hash(_PW)).model_copy(update={"id": uid}))
    minted = await w.auth.sessions.mint(str(uid))
    token = minted.access_token
    _CSRF[token] = csrf_headers(w.codec, minted.session_id)
    w.seeds[token] = seed
    w.resolver.by_token[token] = PrincipalSnapshot(
        user_id=uid, roles=frozenset({role}), permissions=perms
    )
    return token


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    w = _World()
    w.auth = AuthService(
        w.users,
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
    w.client = TestClient(app, client=("127.0.0.1", 50000))
    return w


_OWNER_PERMS = frozenset({Permission.USERS_WRITE})


async def _owner_invite(w: _World) -> tuple[str, str]:
    owner = await _login(w, "owner", _OWNER_PERMS)
    r = w.client.post("/users", headers=_h(owner), json=_BODY)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    ok = w.elevate(owner)
    assert ok.status_code == 200 and ok.json()["action_class"] == "users"
    r = w.client.post("/users", headers=_h(owner), json=_BODY)
    assert r.status_code == 201
    return owner, r.json()["invite_url"].rsplit("/", 1)[1]


async def test_create_requires_step_up_then_link_only_in_response(
    world: _World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    owner = await _login(world, "owner", _OWNER_PERMS)
    denied = world.client.post("/users", headers=_h(owner), json=_BODY)
    assert denied.status_code == 403 and denied.json()["code"] == "step_up_required"
    assert not world.invites.rows  # nothing created before the code
    assert world.elevate(owner).status_code == 200  # `{code}` only, like the M-020 modal
    r = world.client.post("/users", headers=_h(owner), json=_BODY)
    assert r.status_code == 201 and r.json()["status"] == "invited"
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    assert len(token) >= 43
    # The token is never logged, audited, or listed.
    assert token not in caplog.text
    assert token not in repr(world.audit.calls)
    listing = world.client.get("/users/invites", headers=_h(owner)).json()["items"]
    assert len(listing) == 1 and token not in repr(listing)
    row = world.audit.of("users.invited")[0]
    assert row["actor_user_id"] == world.resolver.by_token[owner].user_id
    assert row["after_state"] == {"role": "viewer"} and row["object_kind"] == "user"


async def test_invite_accepted_end_to_end_roles_exactly_as_invited(world: _World) -> None:
    _, token = await _owner_invite(world)
    assert world.client.get(f"/invites/{token}").json()["role"] == "viewer"
    start = world.client.post(f"/invites/{token}", json={"password": GOOD_PW})
    assert start.status_code == 200
    seed = base64.b32decode(
        start.json()["secret_base32"] + "=" * (-len(start.json()["secret_base32"]) % 8)
    )
    done = world.client.post(
        f"/invites/{token}/confirm",
        json={
            "method_id": start.json()["method_id"],
            "code": generate_code(seed, time_step_for(world.clock.now.timestamp()) - 1),
        },
    )
    assert done.status_code == 200
    assert done.json()["status"] == "active" and done.json()["role"] == "viewer"
    assert len(done.json()["recovery_codes"]) > 0
    (row,) = world.invites.rows.values()
    assert row.role == "viewer" and row.user_status.value == "active"
    acc = world.audit.of("users.invite_redeemed")
    assert len(acc) == 1 and acc[0]["after_state"] == {"role": "viewer"}
    assert acc[0]["actor_label"] == "annie"


async def test_role_tamper_rejected_audited_and_token_single_use(world: _World) -> None:
    _, token = await _owner_invite(world)
    for key, val in (("role", "owner"), ("roles", ["owner", "viewer"])):
        r = world.client.post(f"/invites/{token}", json={"password": GOOD_PW, key: val})
        assert r.status_code == 403
    rej = world.audit.of("users.invite_rejected")
    assert [c["reason"] for c in rej] == ["role_tamper", "role_tamper"]
    assert all(c["severity"].value == "warning" for c in rej)
    (row,) = world.invites.rows.values()
    assert row.consumed_at is None and row.role == "viewer"  # tamper did not consume it
    assert world.client.post(f"/invites/{token}", json={"password": GOOD_PW}).status_code == 200
    again = world.client.post(f"/invites/{token}", json={"password": GOOD_PW})
    assert again.status_code == 404  # uniform "gone": no redeemed/expired oracle
    assert world.audit.of("users.invite_rejected")[-1]["reason"] == "redeemed"


async def test_expired_invite_respects_injected_clock(world: _World) -> None:
    _, token = await _owner_invite(world)
    world.clock.now += INVITE_TTL - timedelta(seconds=1)
    assert world.client.get(f"/invites/{token}").status_code == 200
    world.clock.now += timedelta(seconds=2)
    assert world.client.get(f"/invites/{token}").status_code == 404
    post = world.client.post(f"/invites/{token}", json={"password": GOOD_PW})
    assert post.status_code == 404
    assert [c["reason"] for c in world.audit.of("users.invite_rejected")] == ["expired"] * 2


async def test_manager_cannot_create_invite_even_after_step_up(world: _World) -> None:
    mgr = await _login(world, "manager", frozenset())
    first = world.client.post("/users", headers=_h(mgr), json=_BODY)
    assert first.status_code == 403  # step-up gate precedes RBAC on a dangerous route
    assert world.elevate(mgr).status_code == 200
    r = world.client.post("/users", headers=_h(mgr), json=_BODY)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"  # RBAC, server-side
    assert not world.invites.rows and not world.audit.of("users.invited")
