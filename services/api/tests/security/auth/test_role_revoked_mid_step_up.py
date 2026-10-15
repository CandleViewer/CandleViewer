"""E09-Q06 charter gap (#2100): the role that authorised a step-up-gated action is revoked mid-flow.

Drives the REAL `create_app()` (production middleware, routers, RBAC enforcement, CSRF guard) with
the real `AuthService` (sessions, step-up, B16 session chart, MFA) over in-memory fakes. Owner A is
the actor, owner B revokes A's role, T is the target of A's action. Two owners are needed because
the owner floor refuses to demote the last one. The only step-up-gated routes mounted today are the
owner-only `users` class (`api/step_up.py` `DANGEROUS_ROUTES`), so `owner` is the role that
authorises the action; the same interleavings apply to any role once a route gated for it is
mounted.

Each interleaving is forced with an `asyncio.Event` hold on the exact collaborator the handler
awaits (no sleeps, fixed clock, no network: C-13.5, C-13.7). The audit stand-in refuses an
unregistered action exactly like `AuditWriter.emit`, so every asserted row is one production could
write, and it stamps each row with its position in the log: "in order" means ascending `seq`.

Not asserted here: whether a role change also rotates the session id (SR-013, #2101). These tests
pin authority and audit order, so they keep the session the step-up started on.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Request

import candleviewer.app as appmod
import candleviewer.auth as auth_pkg
from candleviewer.audit.actions import validate_action
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, MfaMethodRecord
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.contract.rbac.rbac_harness import UserStore
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

PW = "pw-canary-2100"
_PEPPER = "pepper-2100"
_T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
#: Hard deadline on every hold so a regression fails fast instead of hanging the lane.
_HOLD_DEADLINE_S = 10.0


class _Clock:
    def __call__(self) -> datetime:
        return _T0


class _Hold:
    """One-shot rendezvous on a collaborator a handler awaits: the first call whose key matches
    parks in `pause()` and sets `reached`; the test releases it once the interleaved request ran."""

    def __init__(self, on: str | uuid.UUID) -> None:
        self._on = str(on)
        self.reached = asyncio.Event()
        self._released = asyncio.Event()
        self._spent = False

    async def pause(self, key: str | uuid.UUID) -> None:
        if self._spent or str(key) != self._on:
            return
        self._spent = True
        self.reached.set()
        async with asyncio.timeout(_HOLD_DEADLINE_S):
            await self._released.wait()

    def release(self) -> None:
        self._released.set()


async def _until_parked(hold: _Hold, request: asyncio.Task[httpx.Response]) -> None:
    """Wait until `request` is parked on `hold`; fail, not hang, if it ended without reaching it."""
    watcher = asyncio.create_task(hold.reached.wait())
    await asyncio.wait(
        {request, watcher}, timeout=_HOLD_DEADLINE_S, return_when=asyncio.FIRST_COMPLETED
    )
    watcher.cancel()
    assert hold.reached.is_set(), f"the request ended without reaching the hold: {request}"


class _MfaRepository(FakeMfaRepository):
    """Can park the TOTP check of a step-up (`find_active_totp_methods`)."""

    def __init__(self) -> None:
        super().__init__()
        self.hold: _Hold | None = None

    async def find_active_totp_methods(self, user_id: str) -> tuple[MfaMethodRecord, ...]:
        if self.hold is not None:
            await self.hold.pause(user_id)
        return await super().find_active_totp_methods(user_id)


class _Directory(UserStore):
    """The role store: two owners and a viewer. `get_roles` is the first store call a handler
    makes after RBAC and the step-up gate, so a hold there parks it past authorisation."""

    def __init__(self, owners: tuple[uuid.UUID, uuid.UUID], viewer: uuid.UUID) -> None:
        super().__init__()
        self.initial_roles = {o: frozenset({"owner"}) for o in owners} | {
            viewer: frozenset({"viewer"})
        }
        self.roles = dict(self.initial_roles)
        self.hold: _Hold | None = None

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        if self.hold is not None:
            await self.hold.pause(user_id)
        return await super().get_roles(user_id)


def _role_permissions() -> dict[str, frozenset[Permission]]:
    """The checked-in RBAC vocabulary the identity migration seeds (owner holds every code)."""
    seed = json.loads((Path(auth_pkg.__file__).parent / "rbac_seed.json").read_text("utf-8"))
    out = {
        role: frozenset(Permission(code) for code in codes)
        for role, codes in seed["role_permissions"].items()
        if codes != ["*"]
    }
    out["owner"] = frozenset(Permission)
    return out


_PERMISSIONS = _role_permissions()


def _permissions(roles: frozenset[str]) -> frozenset[Permission]:
    return frozenset().union(*(_PERMISSIONS[r] for r in roles))


class _Resolver:
    """Bearer -> principal, re-derived from the live role directory on every request (C-12.4)."""

    def __init__(self, directory: _Directory) -> None:
        self._directory = directory
        self.by_token: dict[str, uuid.UUID] = {}

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        user_id = self.by_token.get(token.strip()) if scheme.lower() == "bearer" else None
        roles = None if user_id is None else self._directory.roles.get(user_id)
        if user_id is None or roles is None:
            return None
        return PrincipalSnapshot(user_id, roles, _permissions(roles))


class _Identity:
    """`GET /auth/session` identity: roles and permissions straight from the live directory."""

    def __init__(self, directory: _Directory) -> None:
        self._directory = directory

    async def user(self, user_id: str) -> dict[str, Any]:
        roles = self._directory.roles[uuid.UUID(user_id)]
        return {"id": user_id, "username": user_id, "roles": sorted(roles), "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        roles = self._directory.roles[uuid.UUID(user_id)]
        return {"permissions": sorted(p.value for p in _permissions(roles)), "account_scope": []}


class _AuditLog:
    """Stand-in for the started `AuditWriter`."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)
        self.rows.append({"seq": len(self.rows), "action": action, **kw})

    def find(
        self, action: str, *, actor: uuid.UUID, obj: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        return [
            r
            for r in self.rows
            if r["action"] == action
            and str(r.get("actor_user_id")) == str(actor)
            and (obj is None or r.get("object_id") == str(obj))
        ]


@dataclass(frozen=True)
class _Actor:
    user_id: uuid.UUID
    token: str
    session_id: uuid.UUID
    seed: bytes
    headers: dict[str, str]


class World:
    """The composed app plus the three actors and the holds the interleavings need."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self.users = FakeUserRepository()
        self.mfa_repo = _MfaRepository()
        self.sessions_repo = FakeSessionRepository()
        self.audit = _AuditLog()
        self.auth = AuthService(
            self.users,
            mfa_repository=self.mfa_repo,
            totp_encryption_key=os.urandom(32),
            recovery_code_hmac_key=os.urandom(32),
            session_repository=self.sessions_repo,
            pepper=_PEPPER,
            clock=_Clock(),
        )
        ids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        self.directory = _Directory((ids[0], ids[1]), ids[2])
        self.resolver = _Resolver(self.directory)
        self.client: httpx.AsyncClient
        self.owner_a: _Actor
        self.owner_b: _Actor
        self.target: _Actor
        self._ids = ids

    async def open(self) -> httpx.AsyncClient:
        self._monkeypatch.setattr(appmod, "build_auth_service", lambda *_a, **_k: self.auth)
        self._monkeypatch.setattr(
            appmod, "build_identity_provider", lambda _s: _Identity(self.directory)
        )
        app = appmod.create_app(principal_resolver=self.resolver, user_role_store=self.directory)
        ctx = app.state.app_context
        await self.auth.start(ctx)
        ctx.audit._writer = self.audit
        self._codec = app.state.csrf_codec
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        self.client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        pw_hash = await Hasher(pepper=_PEPPER).hash(PW)
        self.owner_a = await self._enrol("owner-a", self._ids[0], pw_hash)
        self.owner_b = await self._enrol("owner-b", self._ids[1], pw_hash)
        self.target = await self._enrol("target", self._ids[2], pw_hash, extra_sessions=1)
        return self.client

    async def _enrol(
        self, name: str, user_id: uuid.UUID, pw_hash: str, *, extra_sessions: int = 0
    ) -> _Actor:
        mfa = self.auth.mfa
        res = await mfa.enroll(
            str(user_id), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name=name
        )
        assert res.secret_base32 is not None
        seed = base64.b32decode(res.secret_base32 + "=" * (-len(res.secret_base32) % 8))
        await mfa.confirm_enrollment(
            str(user_id),
            method_id=str(res.method_id),
            code=generate_code(seed, time_step_for(_T0.timestamp()) - 1),
        )
        self.users.add(
            make_user(
                username=name, email=f"{name}@example.test", password_hash=pw_hash
            ).model_copy(update={"id": user_id})
        )
        minted = await self.auth.sessions.mint(str(user_id))
        for _ in range(extra_sessions):
            await self.auth.sessions.mint(str(user_id))
        self.resolver.by_token[minted.access_token] = user_id
        headers = {
            "Authorization": f"Bearer {minted.access_token}",
            **csrf_headers(self._codec, minted.session_id),
        }
        return _Actor(user_id, minted.access_token, minted.session_id, seed, headers)

    async def call(self, actor: _Actor, method: str, path: str, **kw: Any) -> httpx.Response:
        return await self.client.request(method, path, headers=actor.headers, **kw)

    async def step_up(self, actor: _Actor, *, action_class: str | None = None) -> httpx.Response:
        """`POST /auth/step-up` with password and a fresh TOTP code. Without `action_class` the
        server elevates the class its own last 403 challenged."""
        body: dict[str, Any] = {
            "code": generate_code(actor.seed, time_step_for(_T0.timestamp())),
            "password": PW,
        }
        if action_class is not None:
            body["action_class"] = action_class
        return await self.call(actor, "POST", "/auth/step-up", json=body)

    async def elevate(self, actor: _Actor) -> None:
        """Hold a live `users` elevation, as after a completed step-up."""
        done = await self.step_up(actor, action_class="users")
        assert done.status_code == 200, done.text

    async def revoke_owner_role(self, by: _Actor, of: _Actor) -> httpx.Response:
        """The Owner revokes `of`'s role: `PUT /users/{of}/roles` demoting to viewer."""
        return await self.call(by, "PUT", f"/users/{of.user_id}/roles", json={"roles": ["viewer"]})

    async def act(self, actor: _Actor, action: _Action) -> httpx.Response:
        return await self.call(actor, action.method, action.path(self), json=action.body)

    def hold_authentication(self, hold: _Hold) -> None:
        """Park a request in the session lookup, i.e. in flight but not yet authorised."""
        real = self.auth.sessions.authenticate_access_token

        async def parked(token: str, **kw: Any) -> Any:
            await hold.pause(token)
            return await real(token, **kw)

        self._monkeypatch.setattr(self.auth.sessions, "authenticate_access_token", parked)

    def live_target_methods(self) -> int:
        return sum(
            1
            for m in self.mfa_repo.methods.values()
            if m.user_id == self.target.user_id and m.confirmed_at and m.revoked_at is None
        )

    def live_target_sessions(self) -> int:
        return sum(
            1
            for s in self.sessions_repo.sessions.values()
            if s.user_id == self.target.user_id and s.revoked_at is None
        )


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    w = World(monkeypatch)
    client = await w.open()
    try:
        yield w
    finally:
        await client.aclose()
        await w.auth.stop(0.0)


@dataclass(frozen=True)
class _Action:
    """One mounted step-up-gated action, with the probes that tell "all of it" from "none of it"."""

    id: str
    method: str
    path: Callable[[World], str]
    body: dict[str, Any]
    #: Audit actions a completed run writes (acting owner as actor), one row each.
    effect_audit: tuple[str, ...]
    applied: Callable[[World], bool]
    untouched: Callable[[World], bool]


_CHANGE_ROLES = _Action(
    id="change_roles",
    method="PUT",
    path=lambda w: f"/users/{w.target.user_id}/roles",
    body={"roles": ["viewer", "manager"]},
    effect_audit=("roles.grant",),
    applied=lambda w: w.directory.roles[w.target.user_id] == {"viewer", "manager"},
    untouched=lambda w: w.directory.roles[w.target.user_id] == {"viewer"},
)
#: Two effects (TOTP methods, then every session of the target) that must stand or fall together.
_RESET_TOTP = _Action(
    id="reset_totp",
    method="POST",
    path=lambda w: f"/users/{w.target.user_id}/mfa/reset",
    body={"acknowledge_unknown_positions": True},
    effect_audit=("auth.mfa_reset_by_owner",),
    applied=lambda w: w.live_target_methods() == 0 and w.live_target_sessions() == 0,
    untouched=lambda w: w.live_target_methods() == 1 and w.live_target_sessions() == 2,
)
ACTIONS = (_CHANGE_ROLES, _RESET_TOTP)


def _in_order(*groups: list[dict[str, Any]]) -> None:
    """Every row of each group precedes every row of the next group in the audit log."""
    for group in groups:
        assert group, "an expected audit row is missing"
    for earlier, later in pairwise(groups):
        assert max(r["seq"] for r in earlier) < min(r["seq"] for r in later)


def _revocation_rows(w: World) -> list[dict[str, Any]]:
    """B's audit rows for taking A's owner role away: one grant (viewer), one revoke (owner)."""
    a, b = w.owner_a.user_id, w.owner_b.user_id
    rows = w.audit.find("roles.revoke", actor=b, obj=a) + w.audit.find(
        "roles.grant", actor=b, obj=a
    )
    assert sorted(r["action"] for r in rows) == ["roles.grant", "roles.revoke"]
    return rows


def _assert_refused_without_effect(w: World, action: _Action, response: httpx.Response) -> None:
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert action.untouched(w)
    for effect in action.effect_audit:
        assert not w.audit.find(effect, actor=w.owner_a.user_id)


async def _challenge(w: World, action: _Action) -> None:
    """A's first attempt, without an elevation: refused with the step-up challenge."""
    challenged = await w.act(w.owner_a, action)
    assert challenged.status_code == 403
    assert challenged.json()["code"] == "step_up_required"


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_role_revoked_between_step_up_challenge_and_completion_refuses_the_retry(
    world: World, action: _Action
) -> None:
    a, b, log = world.owner_a, world.owner_b, world.audit
    # B holds a live elevation, so its own revoke is not challenged.
    await world.elevate(b)
    await _challenge(world, action)

    revoked = await world.revoke_owner_role(b, a)
    assert revoked.status_code == 200, revoked.text

    # A's very next request already reports the new role set.
    session = await world.call(a, "GET", "/auth/session")
    assert session.status_code == 200
    assert session.json()["user"]["roles"] == ["viewer"]
    assert Permission.USERS_WRITE.value not in session.json()["permissions"]

    # The step-up modal A had open still completes: password and code are right.
    completed = await world.step_up(a)
    assert completed.status_code == 200, completed.text
    retried = await world.act(a, action)

    _assert_refused_without_effect(world, action, retried)
    _in_order(
        log.find("auth.step_up_required", actor=a.user_id),
        _revocation_rows(world),
        log.find("auth.step_up_granted", actor=a.user_id),
        log.find("rbac.denied", actor=a.user_id),
    )


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_role_revoked_while_the_step_up_is_verifying_refuses_the_retry(
    world: World, action: _Action
) -> None:
    a, b, log = world.owner_a, world.owner_b, world.audit
    await world.elevate(b)
    await _challenge(world, action)

    # Park A's step-up after the password check, inside the TOTP check, and revoke meanwhile.
    hold = _Hold(a.user_id)
    world.mfa_repo.hold = hold
    stepping = asyncio.create_task(world.step_up(a))
    await _until_parked(hold, stepping)
    revoked = await world.revoke_owner_role(b, a)
    assert revoked.status_code == 200, revoked.text
    hold.release()

    # The step-up proves who A is; it grants no authority, so it may complete after the revoke.
    completed = await stepping
    assert completed.status_code == 200, completed.text
    retried = await world.act(a, action)

    _assert_refused_without_effect(world, action, retried)
    _in_order(
        log.find("auth.step_up_required", actor=a.user_id),
        _revocation_rows(world),
        log.find("auth.step_up_granted", actor=a.user_id),
        log.find("rbac.denied", actor=a.user_id),
    )


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_role_revoked_while_the_action_awaits_authorisation_is_refused(
    world: World, action: _Action
) -> None:
    a, b, log = world.owner_a, world.owner_b, world.audit
    await world.elevate(b)
    # A holds a live elevation, so only RBAC stands between A and the effect.
    await world.elevate(a)

    # Park A's request in its session lookup: in flight, but nobody has authorised it yet.
    hold = _Hold(a.token)
    world.hold_authentication(hold)
    acting = asyncio.create_task(world.act(a, action))
    await _until_parked(hold, acting)
    revoked = await world.revoke_owner_role(b, a)
    assert revoked.status_code == 200, revoked.text
    hold.release()
    response = await acting

    _assert_refused_without_effect(world, action, response)
    _in_order(
        log.find("auth.step_up_granted", actor=a.user_id),
        _revocation_rows(world),
        log.find("rbac.denied", actor=a.user_id),
    )


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_role_revoked_after_the_action_was_authorised_leaves_an_atomic_effect_in_order(
    world: World, action: _Action
) -> None:
    """The handler authorised A at entry; the revoke lands before the effect. The ticket allows
    "refused or completed atomically", so this pins the invariants and not which of the two the
    handler picks: all of the effect or none of it, the response agreeing with the state, and
    nothing A's request audits ahead of the revoke it raced."""
    a, b, log = world.owner_a, world.owner_b, world.audit
    await world.elevate(b)
    await world.elevate(a)

    # Park A in the handler's first role-store read: RBAC has authorised it and the step-up gate
    # has let it in, but nothing has been changed yet.
    hold = _Hold(world.target.user_id)
    world.directory.hold = hold
    acting = asyncio.create_task(world.act(a, action))
    await _until_parked(hold, acting)
    revoked = await world.revoke_owner_role(b, a)
    assert revoked.status_code == 200, revoked.text
    hold.release()
    response = await acting

    applied, untouched = action.applied(world), action.untouched(world)
    assert applied != untouched, "partially applied effect"
    assert response.status_code in (200, 403)
    assert (response.status_code == 200) == applied
    effect_rows = [row for name in action.effect_audit for row in log.find(name, actor=a.user_id)]
    assert len(effect_rows) == (len(action.effect_audit) if applied else 0)
    last_revocation_row = max(r["seq"] for r in _revocation_rows(world))
    caused_by_a = effect_rows + log.find("rbac.denied", actor=a.user_id)
    assert all(r["seq"] > last_revocation_row for r in caused_by_a)
