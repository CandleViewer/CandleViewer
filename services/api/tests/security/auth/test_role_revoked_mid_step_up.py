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

#2593: the role is re-checked at the effect, in the change's own transaction: an action already
past its authorisation when the revoke lands is refused with the 403 a fresh request gets at entry
(never a challenge), nothing changed, one `rbac.denied` after the revoke; and an action that
committed first stands, the revoke ordered after its effect. The stores' fakes mirror the
Postgres re-read (`require_active_owner`); the real locks are
`tests/integration/auth/test_owner_actor_recheck_pg.py`'s, in CI.

SR-013 (#2101): a role change ends every live session of its target, and a step-up rotates the
caller's session. So A's requests after B's revoke are refused `401` on A's ended session (as
`SessionSnapshotResolver` refuses one, which the resolver here mirrors), never `403`; A signs in
again to see the entry refusal of a demoted owner. A step-up hands its caller the new bearer
(`World.step_up`). The #2593 re-check at the effect is reached by parking the action past its
step-up gate, at its effect, where B's revoke lands before the actor's re-read; the coordination
with #2593's own changes to this module is noted on #2101.
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
from candleviewer.auth.errors import AuthError
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, MfaMethodRecord
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.contract.rbac.rbac_harness import UserStore
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import FakeUserRepository, InMemoryOwnerReset, make_user
from tests.unit.auth.mfa_fakes import FakeMfaKeyring, FakeMfaRepository
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
    makes after RBAC and the step-up gate, so a hold there parks it past authorisation. A user in
    `disabled` holds no counted owner grant (#2593: the actor's re-read reads the user's status
    too, as `ACTOR_IS_ACTIVE_OWNER` does)."""

    def __init__(self, owners: tuple[uuid.UUID, uuid.UUID], viewer: uuid.UUID) -> None:
        super().__init__()
        self.initial_roles = {o: frozenset({"owner"}) for o in owners} | {
            viewer: frozenset({"viewer"})
        }
        self.roles = dict(self.initial_roles)
        self.disabled: set[uuid.UUID] = set()
        self.hold: _Hold | None = None
        #: Parks a role change at its effect, past the step-up gate, before the actor's re-read.
        self.effect_hold: _Hold | None = None

    async def apply_roles(self, user_id: uuid.UUID, roles: frozenset[str], **kw: Any) -> bool:
        if self.effect_hold is not None:
            await self.effect_hold.pause(user_id)
        return await super().apply_roles(user_id, roles, **kw)

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        if self.hold is not None:
            await self.hold.pause(user_id)
        return await super().get_roles(user_id)

    async def get_status(self, user_id: uuid.UUID) -> str | None:
        found = await super().get_status(user_id)
        return "disabled" if found is not None and user_id in self.disabled else found

    def is_active_owner(self, user_id: uuid.UUID) -> bool:
        return user_id not in self.disabled and super().is_active_owner(user_id)


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
    """Bearer -> principal, re-derived from the live role directory on every request (C-12.4),
    for a live session only, as `SessionSnapshotResolver` resolves it: an ended session (#2101: a
    role change ends its target's) has no principal, so the route answers `401`."""

    def __init__(self, directory: _Directory, sessions: Callable[[], Any]) -> None:
        self._directory, self._sessions = directory, sessions
        self.by_token: dict[str, uuid.UUID] = {}

    async def resolve(self, request: Request) -> PrincipalSnapshot | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        user_id = self.by_token.get(token.strip()) if scheme.lower() == "bearer" else None
        roles = None if user_id is None else self._directory.roles.get(user_id)
        if user_id is None or roles is None or user_id in self._directory.disabled:
            return None
        try:
            await self._sessions().authenticate_access_token(token.strip())
        except AuthError:
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


class _ParkedReset:
    """The owner TOTP reset's unit of work, which can park at its start, before the actor's
    re-read (#2593), as `_Directory.effect_hold` parks a role change."""

    def __init__(self, inner: InMemoryOwnerReset) -> None:
        self._inner = inner
        self.hold: _Hold | None = None

    async def reset_totp(self, target_user_id: str, **kw: Any) -> Any:
        if self.hold is not None:
            await self.hold.pause(target_user_id)
        return await self._inner.reset_totp(target_user_id, **kw)


@dataclass
class _Actor:
    """One user and the bearer it holds now: a granted step-up moves it (#2101)."""

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
        ids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        self.directory = _Directory((ids[0], ids[1]), ids[2])
        # #2593: the reset's actor re-read, against the same directory the role store keeps
        self.reset = _ParkedReset(
            InMemoryOwnerReset(
                self.users,
                self.mfa_repo,
                self.sessions_repo,
                active_owner=lambda actor: self.directory.is_active_owner(uuid.UUID(actor)),
            )
        )
        self.auth = AuthService(
            self.users,
            mfa_repository=self.mfa_repo,
            mfa_keyring=FakeMfaKeyring(os.urandom(32), os.urandom(32)),
            session_repository=self.sessions_repo,
            pepper=_PEPPER,
            clock=_Clock(),
            owner_reset=self.reset,
        )
        self.resolver = _Resolver(self.directory, lambda: self.auth.sessions)
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

    async def step_up(
        self, actor: _Actor, *, action_class: str | None = None, challenge_id: str | None = None
    ) -> httpx.Response:
        """`POST /auth/step-up` with password and a fresh TOTP code. With `challenge_id` the
        server elevates the class its own 403 challenged (#2725: required while it is live);
        `action_class` names a grace class when no challenge is live."""
        body: dict[str, Any] = {
            "code": generate_code(actor.seed, time_step_for(_T0.timestamp())),
            "password": PW,
        }
        if action_class is not None:
            body["action_class"] = action_class
        if challenge_id is not None:
            body["challenge_id"] = challenge_id
        answered = await self.call(actor, "POST", "/auth/step-up", json=body)
        if answered.status_code == 200:  # SR-013 (#2101): the client holds the rotated bundle
            await self._hold_bearer(actor, answered.json()["tokens"]["access_token"])
        return answered

    async def _hold_bearer(self, actor: _Actor, token: str) -> None:
        """*actor* moves, in place, to *token* and its SR-041 pair, as the client does."""
        session = await self.auth.sessions.peek_access_token(token)
        assert session is not None, "the bearer names no session"
        self.resolver.by_token[token] = actor.user_id
        actor.token, actor.session_id = token, session.id
        actor.headers.update(
            {"Authorization": f"Bearer {token}", **csrf_headers(self._codec, session.id)}
        )

    async def sign_in_again(self, actor: _Actor) -> None:
        """*actor* signs in again, after a role change ended its sessions (#2101)."""
        await self._hold_bearer(
            actor, (await self.auth.sessions.mint(str(actor.user_id))).access_token
        )

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


def _assert_refused_without_effect(
    w: World, action: _Action, response: httpx.Response, status: int = 403
) -> None:
    """Refused with nothing of the effect: `403 forbidden` at the effect (#2593), or `401
    unauthenticated` on a session the role change ended (SR-013, #2101)."""
    code = {403: "forbidden", 401: "unauthenticated"}[status]
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert action.untouched(w)
    for effect in action.effect_audit:
        assert not w.audit.find(effect, actor=w.owner_a.user_id)


def _ended(w: World, actor: _Actor) -> list[dict[str, Any]]:
    """#2101: the `auth.session_revoked` rows (B16, the session's own user as actor) of the
    role change that ended *actor*'s sessions."""
    rows = w.audit.find("auth.session_revoked", actor=actor.user_id)
    return [r for r in rows if r.get("reason") == "role_changed"]


async def _challenge(w: World, action: _Action) -> str:
    """A's first attempt, without an elevation: refused with the step-up challenge, whose id
    the step-up modal answers."""
    challenged = await w.act(w.owner_a, action)
    assert challenged.status_code == 403
    assert challenged.json()["code"] == "step_up_required"
    challenge_id: str = challenged.json()["challenge_id"]
    return challenge_id


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_role_revoked_between_step_up_challenge_and_completion_refuses_the_retry(
    world: World, action: _Action
) -> None:
    a, b, log = world.owner_a, world.owner_b, world.audit
    # B holds a live elevation, so its own revoke is not challenged.
    await world.elevate(b)
    challenge_id = await _challenge(world, action)

    revoked = await world.revoke_owner_role(b, a)
    assert revoked.status_code == 200, revoked.text

    # SR-013 (#2101): the role change ended every session of A, so A's next request is 401.
    session = await world.call(a, "GET", "/auth/session")
    assert session.status_code == 401

    # The step-up modal A had open cannot complete on the ended session, nor can the retry.
    completed = await world.step_up(a, challenge_id=challenge_id)
    assert (completed.status_code, completed.json()["code"]) == (401, "unauthenticated")
    retried = await world.act(a, action)

    _assert_refused_without_effect(world, action, retried, status=401)
    assert not log.find("auth.step_up_granted", actor=a.user_id)
    _in_order(
        log.find("auth.step_up_required", actor=a.user_id),
        _revocation_rows(world),
        _ended(world, a),
    )
    # A signs in again: the new session carries the new role set.
    await world.sign_in_again(a)
    fresh = await world.call(a, "GET", "/auth/session")
    assert fresh.json()["user"]["roles"] == ["viewer"]
    assert Permission.USERS_WRITE.value not in fresh.json()["permissions"]


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_role_revoked_while_the_step_up_is_verifying_refuses_the_retry(
    world: World, action: _Action
) -> None:
    a, b, log = world.owner_a, world.owner_b, world.audit
    await world.elevate(b)
    challenge_id = await _challenge(world, action)

    # Park A's step-up after the password check, inside the TOTP check, and revoke meanwhile.
    hold = _Hold(a.user_id)
    world.mfa_repo.hold = hold
    stepping = asyncio.create_task(world.step_up(a, challenge_id=challenge_id))
    await _until_parked(hold, stepping)
    revoked = await world.revoke_owner_role(b, a)
    assert revoked.status_code == 200, revoked.text
    hold.release()

    # SR-013 (#2101): the revoke ended A's session under the step-up, so its grant has no row
    # to land on: refused 401, nothing granted, and the retry is refused the same way.
    completed = await stepping
    assert (completed.status_code, completed.json()["code"]) == (401, "unauthenticated")
    retried = await world.act(a, action)

    _assert_refused_without_effect(world, action, retried, status=401)
    assert not log.find("auth.step_up_granted", actor=a.user_id)
    _in_order(
        log.find("auth.step_up_required", actor=a.user_id),
        _revocation_rows(world),
        _ended(world, a),
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

    # SR-013 (#2101): its session ended while it waited: 401, never authorised.
    _assert_refused_without_effect(world, action, response, status=401)
    assert not log.find("rbac.denied", actor=a.user_id)
    _in_order(
        log.find("auth.step_up_granted", actor=a.user_id),
        _revocation_rows(world),
        _ended(world, a),
    )


async def _park_at_the_effect(
    w: World, action: _Action
) -> tuple[asyncio.Task[httpx.Response], _Hold]:
    """A's request, parked at its effect: RBAC has authorised it and its step-up gate has let it
    in, but the change's own unit of work (the role store's, the reset's) has not re-read the
    actor yet (#2593), nor changed anything. Released by the caller."""
    hold = _Hold(w.target.user_id)
    w.directory.effect_hold = w.reset.hold = hold
    acting = asyncio.create_task(w.act(w.owner_a, action))
    await _until_parked(hold, acting)
    w.directory.effect_hold = w.reset.hold = None
    return acting, hold


async def _entry_refusal(w: World, action: _Action) -> dict[str, Any]:
    """What a fresh request from the demoted A gets at entry (the body the effect must match)."""
    fresh = await w.act(w.owner_a, action)
    assert fresh.status_code == 403, fresh.text
    body: dict[str, Any] = fresh.json()
    return body


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_role_revoked_after_the_action_was_authorised_is_refused_at_the_effect(
    world: World, action: _Action
) -> None:
    """#2593: the handler authorised A at entry; the revoke commits before the effect. The
    effect's own re-read refuses it: the entry's 403 byte for byte (never a challenge), none of
    the effect, and one `rbac.denied` after the revoke it raced."""
    a, b, log = world.owner_a, world.owner_b, world.audit
    await world.elevate(b)
    await world.elevate(a)

    acting, parked = await _park_at_the_effect(world, action)
    revoked = await world.revoke_owner_role(b, a)
    assert revoked.status_code == 200, revoked.text
    parked.release()
    response = await acting

    _assert_refused_without_effect(world, action, response)
    assert "challenge_id" not in response.json()
    denied = log.find("rbac.denied", actor=a.user_id)
    assert [r["reason"] for r in denied] == ["actor_role_revoked"]
    assert denied[0]["object_id"] == str(world.target.user_id)
    _in_order(log.find("auth.step_up_granted", actor=a.user_id), _revocation_rows(world), denied)
    # #2101: the revoke ended A's sessions, so the demoted A's fresh request needs a new one.
    await world.sign_in_again(a)
    assert response.json() == await _entry_refusal(world, action)


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_owner_disabled_after_the_action_was_authorised_is_refused_at_the_effect(
    world: World, action: _Action
) -> None:
    """#2593 (BQ-03): the owner grant stays, but A's user is disabled while A's action is in
    flight: the re-read reads the user's status too, so A is refused as a demoted owner is."""
    a, b, log = world.owner_a, world.owner_b, world.audit
    await world.elevate(b)
    await world.elevate(a)

    acting, parked = await _park_at_the_effect(world, action)
    world.directory.disabled.add(a.user_id)  # B's disable committed: A's grant row untouched
    parked.release()
    response = await acting

    _assert_refused_without_effect(world, action, response)
    assert "owner" in world.directory.roles[a.user_id]
    assert [r["reason"] for r in log.find("rbac.denied", actor=a.user_id)] == ["actor_role_revoked"]


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a.id)
async def test_action_that_committed_before_the_revoke_stands_and_the_revoke_follows_it(
    world: World, action: _Action
) -> None:
    """#2593, the other serial order: B's revoke is past its own authorisation but has not
    changed anything when A's action runs; A's effect commits whole, then B's revoke lands after
    it, and nothing of A's is refused."""
    a, b, log = world.owner_a, world.owner_b, world.audit
    await world.elevate(b)
    await world.elevate(a)

    hold = _Hold(a.user_id)  # B's handler reads its target's roles (A's) before its change
    world.directory.hold = hold
    revoking = asyncio.create_task(world.revoke_owner_role(b, a))
    await _until_parked(hold, revoking)
    world.directory.hold = None
    response = await world.act(a, action)
    hold.release()
    revoked = await revoking

    assert response.status_code == 200, response.text
    assert revoked.status_code == 200, revoked.text
    assert action.applied(world)
    effect_rows = [row for name in action.effect_audit for row in log.find(name, actor=a.user_id)]
    assert len(effect_rows) == len(action.effect_audit)
    assert not log.find("rbac.denied", actor=a.user_id)
    _in_order(effect_rows, _revocation_rows(world))
