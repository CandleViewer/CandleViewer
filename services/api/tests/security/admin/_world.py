"""The world of the E42-X03 admin RBAC suite (#1026).

The REAL `create_app()` with the real `AuthService` (sessions, MFA, step-up and its B16 chart) over
the in-memory auth fakes, a fake clock that moves only when a test moves it, and the admin backends
the route matrix wires (`tests/contract/rbac/rbac_harness.py`), so every admin and users route
reaches its own guard. No Postgres, no network (C-13.5), no sleeps (C-13.7).

The actors are the matrix's (owner, manager_with_grant, manager_without_grant, viewer,
unauthenticated) under the matrix's user ids, so the matrix's user, grant and disable stores apply.
Each signed-in actor has a minted session, its SR-041 CSRF pair and its own TOTP seed. Elevation is
real session state, decided by the production `StepUpService`:

- none: the session never stepped up;
- fresh: the session holds a live grace window for every grace class an admin or users route
  demands, each opened by `POST /auth/step-up` naming its class; a route of a no-grace class is
  sent, challenged, stepped up for that challenge, and sent again unchanged (#2304);
- stale: as fresh, then the clock passes every window (`GRACE_WINDOW`); a no-grace grant passes its
  `SINGLE_USE_WINDOW` before its request is sent again.

The audit stand-in refuses an unregistered action as `AuditWriter.emit` does, so every asserted
record is one production could write.
"""

from __future__ import annotations

import base64
import contextlib
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import candleviewer.app as appmod
from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.audit.actions import validate_action
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import normalise_permission
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.contract.rbac import rbac_harness as matrix
from tests.csrf_helpers import csrf_headers
from tests.security.auth._stack import Clock, RegistryAudit
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_invite_service import FakeRepo as FakeInviteRepository

PW = "pw-canary-x03-admin"  # test-only literal, never a credential
_PEPPER = "x03-admin-test-pepper"
#: A TOTP code is single use within its time step, so each step-up of one user takes the next step.
TOTP_STEP = timedelta(seconds=30)
ORIGIN = matrix.WS_ORIGIN
UNAUTHENTICATED = "unauthenticated"
SIGNED_IN = tuple(a for a in matrix.ACTORS if a != UNAUTHENTICATED)


def _actor_of(user_id: object) -> str:
    return next(a for a in SIGNED_IN if str(matrix.user_id_of(a)) == str(user_id))


class AuditLog(RegistryAudit):
    """The audit stand-in (`_stack.RegistryAudit`) that also takes a keyed record, as the writer's
    `emit_keyed` does: a view-as context's end is written that way (#3085)."""

    async def emit_keyed(self, action: str, name: str, **kw: Any) -> None:
        validate_action(action)
        self.records.append({"action": action, "name": name, **kw})


class Identity:
    """The identity provider the admin guard reads (`SessionAuditPrincipalResolver`): each matrix
    actor's role, and that role's permissions from the contract."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec

    async def user(self, user_id: str) -> dict[str, Any]:
        actor = _actor_of(user_id)
        role = matrix.ROLE_OF[actor]
        return {"id": user_id, "username": actor, "roles": [role], "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        actor = _actor_of(user_id)
        return {
            "permissions": sorted(matrix.actor_permissions(actor, self._spec)),
            "account_scope": [str(g) for g in matrix.actor_grants(actor)],
        }

    async def names(self, user_id: str) -> tuple[str, str | None]:
        """`SqlAlchemyIdentityProvider.names`, which `getViewAs` reads: the username, and no
        display name."""
        return str((await self.user(user_id))["username"]), None


class TokenResolver:
    """The `SnapshotResolver` of the users routers: a minted bearer to its actor's principal."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self._spec = spec
        self.by_token: dict[str, str] = {}

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        actor = self.by_token.get(token.strip()) if scheme.lower() == "bearer" else None
        if actor is None:
            return None
        perms = frozenset(Permission(p) for p in matrix.actor_permissions(actor, self._spec))
        grants = tuple(AccountGrant(g, True, True, False) for g in matrix.actor_grants(actor))
        role = frozenset({matrix.ROLE_OF[actor]})
        return PrincipalSnapshot(matrix.user_id_of(actor), role, perms, grants)


@dataclass(frozen=True)
class Actor:
    name: str
    user_id: uuid.UUID
    session_id: uuid.UUID
    seed: bytes
    headers: dict[str, str]


@dataclass
class AdminWorld:
    app: FastAPI
    client: TestClient
    auth: AuthService
    clock: Clock
    audit: AuditLog
    spec: dict[str, Any]
    roles: matrix.UserStore
    access: matrix.AccessStore
    actors: dict[str, Actor] = field(default_factory=dict)
    #: cell id -> what the cell observed, so each test of a cell reads one request.
    observed: dict[str, Any] = field(default_factory=dict)

    def headers(self, actor: str) -> dict[str, str]:
        if actor == UNAUTHENTICATED:  # a well-formed pair bound to no session (#2090)
            return csrf_headers(self.app.state.csrf_codec)
        return self.actors[actor].headers

    def send(
        self,
        actor: str,
        method: str,
        path: str,
        request: Mapping[str, Any],
        *,
        source_ip: str = "127.0.0.1",
    ) -> httpx.Response:
        """One request as `actor`. An unsafe method without a JSON body sends `{}`, as the route
        matrix does. `source_ip` gives the unauthenticated caller a loopback source of its own,
        so the per-IP refusal throttle (#2090) never turns a cell into a 429."""
        client = self.client
        if source_ip != "127.0.0.1":
            client = TestClient(
                self.app,
                client=(source_ip, 50000),
                raise_server_exceptions=False,
                headers={"origin": ORIGIN},
            )
        body = request.get("json")
        if body is None and method in ("POST", "PUT", "PATCH"):
            body = {}
        sent: httpx.Response = client.request(
            method,
            path,
            params=request.get("params"),
            json=body,
            headers={**self.headers(actor), **request.get("headers", {})},
        )
        return sent

    def code(self, actor: str) -> str:
        return generate_code(self.actors[actor].seed, time_step_for(self.clock.now.timestamp()))

    def step_up(
        self, actor: str, *, action_class: str | None = None, challenge_id: str | None = None
    ) -> httpx.Response:
        """`POST /auth/step-up` with the password and the current TOTP code. A grace class may be
        named with no live challenge; a no-grace class answers the challenge it names."""
        body: dict[str, Any] = {"code": self.code(actor), "password": PW}
        if action_class is not None:
            body["action_class"] = action_class
        if challenge_id is not None:
            body["challenge_id"] = challenge_id
        answer: httpx.Response = self.client.post(
            "/auth/step-up", headers=self.headers(actor), json=body
        )
        return answer

    def tick(self, by: timedelta = TOTP_STEP) -> None:
        self.clock.now += by

    def elevate(self, classes: Iterable[str]) -> None:
        """Every signed-in actor opens a grace window for each class, one TOTP step per class."""
        for action_class in classes:
            for actor in SIGNED_IN:
                done = self.step_up(actor, action_class=action_class)
                assert done.status_code == 200, (actor, action_class, done.text)
            self.tick()


def denials(permission: str) -> float:
    """`authz_denied_total{permission}` on the process registry (SR-125); cells assert deltas."""
    labels = {"permission": normalise_permission(permission)}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


async def _enrol(
    world: AdminWorld,
    users: FakeUserRepository,
    resolver: TokenResolver,
    actor: str,
    pw_hash: str,
) -> Actor:
    """A matrix actor as a real user: a confirmed TOTP method, the password, one minted session."""
    uid = matrix.user_id_of(actor)
    mfa = world.auth.mfa
    req = MfaEnrollRequest(method=MfaMethodKind.TOTP, label="")
    res = await mfa.enroll(str(uid), req, account_name=actor)
    b32 = res.secret_base32
    assert b32 is not None
    seed = base64.b32decode(b32 + "=" * (-len(b32) % 8))
    step = time_step_for(world.clock.now.timestamp()) - 1  # the step before the step-ups' own
    await mfa.confirm_enrollment(
        str(uid), method_id=str(res.method_id), code=generate_code(seed, step)
    )
    user = make_user(username=actor, email=f"{actor}@example.test", password_hash=pw_hash)
    users.add(user.model_copy(update={"id": uid}))
    minted = await world.auth.sessions.mint(str(uid))
    resolver.by_token[minted.access_token] = actor
    csrf = csrf_headers(world.app.state.csrf_codec, minted.session_id)
    headers = {"Authorization": f"Bearer {minted.access_token}", **csrf}
    return Actor(actor, uid, uuid.UUID(str(minted.session_id)), seed, headers)


@contextlib.contextmanager
def open_admin_world(mp: pytest.MonkeyPatch) -> Iterator[AdminWorld]:
    """Build the world; `mp` holds every patch, and the caller undoes it."""
    clock = Clock()
    spec = matrix.load_contract()
    users = FakeUserRepository()
    auth = AuthService(
        users,
        mfa_repository=FakeMfaRepository(),
        totp_encryption_key=bytes(range(32)),  # fixed test keys (determinism)
        recovery_code_hmac_key=bytes(range(32, 64)),
        session_repository=FakeSessionRepository(),
        invite_repository=FakeInviteRepository(),
        pepper=_PEPPER,
        clock=clock,
    )
    audit = AuditLog()
    resolver = TokenResolver(spec)
    roles, access = matrix.UserStore(), matrix.AccessStore()
    purge = matrix._PurgeBackend()  # records every call; never plans or runs a purge
    mp.setenv("CV_ALLOWED_ORIGINS", ORIGIN)
    mp.setattr(appmod, "build_auth_service", lambda *_a, **_k: auth)
    mp.setattr(appmod, "build_identity_provider", lambda _s: Identity(spec))
    mp.setattr(appmod, "build_retention_manager", lambda *_a, **_k: purge)
    mp.setattr(appmod, "build_admin_backups", lambda *_a, **_k: BackupCatalogue(matrix._Backups()))
    mp.setattr(appmod, "build_backup_downloads", matrix._backup_downloads)
    app = appmod.create_app(
        principal_resolver=resolver,
        user_role_store=roles,
        account_access_store=access,
        user_disable=matrix.user_disable_service(audit),
        auth_clock=clock,
    )
    ctx = app.state.app_context
    ctx.audit._writer = audit  # the lazy emitters resolve the writer per call
    ctx.audit._query = matrix._AuditQuery()  # the lifespan is not started; as the matrix does
    client = TestClient(
        app, client=("127.0.0.1", 50000), raise_server_exceptions=False, headers={"origin": ORIGIN}
    )
    with client:
        portal = client.portal
        assert portal is not None
        portal.call(auth.start, ctx)
        world = AdminWorld(app, client, auth, clock, audit, spec, roles, access)
        pw_hash = portal.call(Hasher(pepper=_PEPPER).hash, PW)
        for actor in SIGNED_IN:
            world.actors[actor] = portal.call(_enrol, world, users, resolver, actor, pw_hash)
        try:
            yield world
        finally:
            portal.call(auth.stop, 1.0)
