"""In-process `create_app()` harness for the E09-X02 HTTP/WS abuse cases (#2144).

Real `AuthService` (login, MFA, sessions, step-up, invites) over the in-memory fakes, a fixed
clock shared with the WS gateway, a fake identity provider, and an audit writer that refuses an
unregistered action exactly like `AuditWriter.emit` (`validate_action`), so every asserted audit
row is one production would write. Loopback client (mesh allow-list), no network, no sleeps.
"""

from __future__ import annotations

import base64
import contextlib
import functools
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.audit.actions import validate_action
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.ws.gateway import make_ws_router
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_invite_service import FakeRepo as FakeInviteRepository

ORIGIN = "https://app.example.test"
PW = "pw-canary-x02-abuse"  # test-only literal, never a credential
INVITE_PW = "correct horse battery"  # an invitee's new password (SR-028 policy)
_PEPPER = "x02-test-pepper"
T0 = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)
#: The exchange account a WS test's manager holds until the test revokes the grant.
GRANTED_ACCOUNT = uuid.UUID("00000000-0000-4000-8000-00000000acc1")


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class RegistryAudit:
    """Stand-in for the started `AuditWriter`: records every emission and, like the real
    writer, raises `UnknownAuditAction` for an action that is not registered."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)
        self.records.append({"action": action, **kw})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["action"] == action]


class Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "u", "roles": ["viewer"], "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": [], "account_scope": []}


class Grants:
    """WS principal source standing in for the identity store: a manager with `orders:read`
    on `GRANTED_ACCOUNT` until `granted` is cleared."""

    def __init__(self) -> None:
        self.granted = True

    async def load(self, uid: uuid.UUID) -> PrincipalSnapshot:
        grants = (AccountGrant(GRANTED_ACCOUNT, True, True, False),) if self.granted else ()
        perms = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ})
        return PrincipalSnapshot(uid, frozenset({"manager"}), perms, grants)


class Resolver:
    """Bearer -> principal for the owner routes (stands in for the identity store)."""

    def __init__(self) -> None:
        self.by_token: dict[str, PrincipalSnapshot] = {}

    def resolve(self, request: Any) -> PrincipalSnapshot | None:
        header = str(request.headers.get("authorization", ""))
        return self.by_token.get(header.removeprefix("Bearer "))


class Stack:
    def __init__(
        self,
        client: TestClient,
        auth: AuthService,
        users: FakeUserRepository,
        clock: Clock,
        resolver: Resolver,
    ) -> None:
        self.client = client
        self.auth = auth
        self.users = users
        self.clock = clock
        self.resolver = resolver
        self.audit = RegistryAudit()
        self.state: Any = cast(FastAPI, client.app).state
        self.state.app_context.audit._writer = self.audit  # the lazy emitters resolve it per call

    def call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        assert self.client.portal is not None
        return self.client.portal.call(functools.partial(fn, *args, **kwargs))

    def code(self, seed: bytes, offset: int = 0) -> str:
        return generate_code(seed, time_step_for(self.clock.now.timestamp()) + offset)

    def add_user(self, username: str) -> tuple[uuid.UUID, bytes]:
        """An active user with `PW` and a confirmed TOTP method; returns (id, seed)."""
        hashed = self.call(Hasher(pepper=_PEPPER).hash, PW)
        user = make_user(username=username, email=f"{username}@example.test", password_hash=hashed)
        self.users.add(user)
        mfa = self.auth.mfa
        req = MfaEnrollRequest(method=MfaMethodKind.TOTP, label="")
        res = self.call(mfa.enroll, str(user.id), req, account_name=username)
        b32 = str(res.secret_base32)
        seed = base64.b32decode(b32 + "=" * (-len(b32) % 8))
        self.call(
            mfa.confirm_enrollment,
            str(user.id),
            method_id=str(res.method_id),
            code=self.code(seed, -1),
        )
        return user.id, seed

    def sign_in(self, username: str, seed: bytes, carried: dict[str, str] | None = None) -> Any:
        """Password step then MFA step (both carrying *carried* headers); the MFA reply."""
        self.client.cookies.clear()
        body = {"identifier": username, "password": PW}
        pw = self.client.post("/auth/login", headers=carried, json=body)
        assert pw.status_code == 200, pw.text
        step = {"mfa_token": pw.json()["mfa_token"], "method": "totp", "code": self.code(seed)}
        mfa = self.client.post("/auth/mfa/verify", headers=carried, json=step)
        assert mfa.status_code == 200, mfa.text
        self.clock.now += timedelta(seconds=30)  # next TOTP step: codes are single-use
        return mfa

    def principal(
        self, username: str, role: str, *perms: Permission
    ) -> tuple[dict[str, str], bytes]:
        """(bearer + SR-041 headers, TOTP seed) of a new signed-in user whose principal on the
        owner routes is *role* with *perms*."""
        uid, seed = self.add_user(username)
        minted = self.call(self.auth.sessions.mint, str(uid))
        snapshot = PrincipalSnapshot(uid, frozenset({role}), frozenset(perms))
        self.resolver.by_token[minted.access_token] = snapshot
        csrf = csrf_headers(self.state.csrf_codec, minted.session_id)
        return {"Authorization": f"Bearer {minted.access_token}", **csrf}, seed

    def step_up(self, headers: dict[str, str], seed: bytes) -> Any:
        body = {"code": self.code(seed), "password": PW}
        return self.client.post("/auth/step-up", headers=headers, json=body)

    def scraped(self, name: str, **labels: str) -> float:
        """Sum of the samples of *name* on the app's scraped registry whose labels include
        *labels* (0.0 when the series is not served there at all)."""
        total = 0.0
        for family in self.state.app_context.metrics.collect():
            for sample in family.samples:
                if sample.name == name and labels.items() <= sample.labels.items():
                    total += sample.value
        return total


@contextlib.contextmanager
def open_stack(monkeypatch: pytest.MonkeyPatch, **create_app_kwargs: Any) -> Iterator[Stack]:
    clock = Clock()
    monkeypatch.setenv("CV_ALLOWED_ORIGINS", ORIGIN)
    users = FakeUserRepository()
    auth = AuthService(
        users,
        pepper=_PEPPER,
        mfa_repository=FakeMfaRepository(),
        totp_encryption_key=bytes(range(32)),  # fixed test keys (determinism)
        recovery_code_hmac_key=bytes(range(32, 64)),
        session_repository=FakeSessionRepository(),
        invite_repository=FakeInviteRepository(),
        clock=clock,
    )
    monkeypatch.setattr(appmod, "build_auth_service", lambda *_a, **_k: auth)
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _s: Identity())
    # The gateway checks token expiry on its wall clock (#2259): share the injected clock.
    wall = functools.partial(make_ws_router, wall_ms=lambda: int(clock.now.timestamp() * 1000))
    monkeypatch.setattr(appmod, "make_ws_router", wall)
    resolver = Resolver()
    create_app_kwargs.setdefault("principal_resolver", resolver)
    app = appmod.create_app(auth_clock=clock, **create_app_kwargs)
    client = TestClient(
        app, base_url=ORIGIN, client=("127.0.0.1", 50000), raise_server_exceptions=False
    )
    with client:
        stack = Stack(client, auth, users, clock, resolver)
        stack.call(auth.start, stack.state.app_context)
        try:
            yield stack
        finally:
            stack.call(auth.stop, 1.0)
