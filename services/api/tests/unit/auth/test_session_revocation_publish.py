"""#2272: every session revoke path publishes each revoked session id to the injected
revocation sink, after the row update (23-ws-protocol.md §9.5). A refresh-token rotation
publishes nothing: the client re-`auth`s its socket in place (§4.1).

The call-site scan enumerates every `SessionRepository` revoke in production code. A new
revoke path without a driver below fails it, so no path can skip the publish unnoticed.
"""

from __future__ import annotations

import ast
import os
import uuid
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

import candleviewer
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import RefreshReuseDetected, SessionRevoked, UnlockPasswordInvalid
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import (
    ABSOLUTE_LIFETIME,
    MAX_UNLOCK_ATTEMPTS,
    SessionService,
)
from candleviewer.auth.step_up import GRACE_WINDOW, StepUpService

from .auth_fakes import FakeUserRepository
from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
_PKG = Path(candleviewer.__file__).resolve().parent
#: Cheapest valid Argon2id cost: unlock verifies a password per attempt.
_FAST_ARGON2 = {"m": 8, "t": 1, "p": 1}
_PASSWORD = "correct horse battery staple"  # a test fixture string, not a credential
#: Label of a call site whose `reason=` is the caller's (`SessionService.revoke(_all)`).
_CALLER = "<caller>"

Calls = set[tuple[str, str]]


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Sink:
    """Records each publish and whether the row was already revoked at that moment."""

    def __init__(self, repo: FakeSessionRepository) -> None:
        self.repo = repo
        self.calls: list[tuple[str, str]] = []
        self.row_revoked_first: list[bool] = []

    async def __call__(self, session_id: str, reason: str) -> None:
        row = self.repo.sessions.get(session_id)
        self.row_revoked_first.append(row is not None and row.revoked_at is not None)
        self.calls.append((session_id, reason))


class _World:
    def __init__(self) -> None:
        self.clock = _Clock()
        self.repo = FakeSessionRepository()
        self.sink = _Sink(self.repo)
        self.hasher = Hasher(pepper=os.urandom(16).hex())
        self.user = str(uuid.uuid4())
        self.sessions = SessionService(
            self.repo, self.hasher, clock=self.clock, publish_revocation=self.sink
        )
        self.step_up = StepUpService(
            FakeMfaRepository(),
            self.repo,
            TotpEncryptor(os.urandom(32)),
            FakeUserRepository(),
            self.hasher,
            clock=self.clock,
            publish_revocation=self.sink,
        )

    async def mint(self, user: str | None = None) -> str:
        return str((await self.sessions.mint(user or self.user)).session_id)


@pytest.fixture
async def world() -> AsyncIterator[_World]:
    w = _World()
    yield w
    await w.step_up.stop()


# -- one driver per revoke call site: returns the publishes the path must make ----------------


async def _refresh_reuse(w: _World) -> Calls:
    first = await w.sessions.mint(w.user)
    second = await w.sessions.refresh(first.refresh_token)
    with pytest.raises(RefreshReuseDetected):
        await w.sessions.refresh(first.refresh_token)
    # The rotated-out id too: a socket that has not re-`auth`ed yet still runs on it.
    family = (str(first.session_id), str(second.minted.session_id))
    return {(sid, "rotation_reuse") for sid in family}


async def _refresh_expired(w: _World) -> Calls:
    minted = await w.sessions.mint(w.user)
    w.clock.now += ABSOLUTE_LIFETIME
    with pytest.raises(SessionRevoked):
        await w.sessions.refresh(minted.refresh_token)
    return {(str(minted.session_id), "expired")}


async def _refresh_rotation(w: _World) -> Calls:
    minted = await w.sessions.mint(w.user)
    await w.sessions.refresh(minted.refresh_token)
    return set()  # AC: rotation never closes the socket (§4.1 in-place re-auth)


async def _require_active_expired(w: _World) -> Calls:
    sid = await w.mint()
    w.clock.now += ABSOLUTE_LIFETIME
    with pytest.raises(SessionRevoked):
        await w.sessions.require_active(sid)
    return {(sid, "expired")}


async def _unlock_attempts_exceeded(w: _World) -> Calls:
    sid = await w.mint()
    password_hash = await w.hasher.hash(_PASSWORD, _FAST_ARGON2)
    for _ in range(MAX_UNLOCK_ATTEMPTS - 1):
        with pytest.raises(UnlockPasswordInvalid):
            await w.sessions.unlock(sid, password="wrong", password_hash=password_hash)
    assert w.sink.calls == []  # a wrong password alone revokes nothing
    with pytest.raises(SessionRevoked):
        await w.sessions.unlock(sid, password="wrong", password_hash=password_hash)
    return {(sid, "unlock_attempts_exceeded")}


async def _revoke(w: _World) -> Calls:
    sid = await w.mint()
    await w.sessions.revoke(sid, reason="user_revoked")
    return {(sid, "user_revoked")}


async def _revoke_all(w: _World) -> Calls:
    mine = {await w.mint(), await w.mint()}
    await w.mint(str(uuid.uuid4()))  # another user's session is not touched
    await w.sessions.revoke_all(w.user, reason="logout_all")
    return {(sid, "logout_all") for sid in mine}


async def _owner_totp_reset(w: _World) -> Calls:
    owner = str(uuid.uuid4())
    actor = await w.mint(owner)
    await w.repo.save_step_up_state(
        actor, elevations={"users": w.clock.now + GRACE_WINDOW}, failures=0, readonly_until=None
    )
    targets = {await w.mint(), await w.mint()}
    await w.step_up.reset_totp(actor_session_id=actor, actor_user_id=owner, target_user_id=w.user)
    return {(sid, "mfa_reset_by_owner") for sid in targets}


#: (enclosing `Class.method`, `reason=`) of each revoke call site -> its driver.
_PATHS: dict[tuple[str, str], Callable[[_World], Awaitable[Calls]]] = {
    ("SessionService.refresh", "rotation_reuse"): _refresh_reuse,
    ("SessionService.refresh", "expired"): _refresh_expired,
    ("SessionService.refresh", "rotated"): _refresh_rotation,
    ("SessionService.require_active", "expired"): _require_active_expired,
    ("SessionService.unlock", "unlock_attempts_exceeded"): _unlock_attempts_exceeded,
    ("SessionService.revoke", _CALLER): _revoke,
    ("SessionService.revoke_all", _CALLER): _revoke_all,
    ("StepUpService.reset_totp", "mfa_reset_by_owner"): _owner_totp_reset,
}


class _RevokeSites(ast.NodeVisitor):
    """Collects `(Class.method, reason)` for every `<repo>.revoke(...)` or
    `<repo>.revoke_all_for_user(...)` call. Only the repository takes `now=`, which tells
    these apart from the services' own `revoke(...)` and the B16 chart's `revoke(...)`."""

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.sites: set[tuple[str, str]] = set()

    def _scoped(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scoped

    def visit_Call(self, node: ast.Call) -> None:
        func, kwargs = node.func, {k.arg: k.value for k in node.keywords if k.arg}
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"revoke", "revoke_all_for_user"}
            and "now" in kwargs
        ):
            reason = kwargs.get("reason")
            label = reason.value if isinstance(reason, ast.Constant) else _CALLER
            self.sites.add((".".join(self.scope), str(label)))
        self.generic_visit(node)


def _revoke_call_sites() -> set[tuple[str, str]]:
    visitor = _RevokeSites()
    for path in sorted(_PKG.rglob("*.py")):
        with warnings.catch_warnings():  # escape-sequence noise from unrelated modules
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor.visit(tree)
    return visitor.sites


def test_every_session_revoke_call_site_has_a_publish_driver() -> None:
    sites = _revoke_call_sites()
    assert sites == set(_PATHS), (
        "session revoke call sites changed; give each new one a driver in _PATHS proving it "
        f"publishes (#2272). New: {sorted(sites - set(_PATHS))}; "
        f"gone: {sorted(set(_PATHS) - sites)}"
    )


@pytest.mark.parametrize("path", sorted(_PATHS), ids=lambda p: f"{p[0]}:{p[1]}")
async def test_revoke_path_publishes_each_revoked_session_after_the_row_update(
    world: _World, path: tuple[str, str]
) -> None:
    expected = await _PATHS[path](world)

    assert sorted(world.sink.calls) == sorted(expected)
    assert all(world.sink.row_revoked_first), "published before the row was revoked"


async def test_revoke_of_an_already_revoked_session_publishes_nothing_again(
    world: _World,
) -> None:
    sid = await world.mint()
    await world.sessions.revoke(sid, reason="logout")

    assert await world.sessions.revoke(sid, reason="user_revoked") is None
    assert world.sink.calls == [(sid, "logout")]


async def test_failed_publish_neither_skips_the_other_sessions_nor_undoes_the_revoke(
    world: _World,
) -> None:
    first, second = await world.mint(), await world.mint()
    published: list[str] = []

    async def flaky(session_id: str, reason: str) -> None:
        if session_id == first:
            raise RuntimeError("hub unavailable")
        published.append(session_id)

    service = SessionService(world.repo, world.hasher, clock=world.clock, publish_revocation=flaky)

    with capture_logs() as logs:
        revoked = await service.revoke_all(world.user, reason="logout_all")

    assert {str(r.id) for r in revoked} == {first, second}
    assert all(world.repo.sessions[sid].revoked_at is not None for sid in (first, second))
    assert published == [second]
    failed = [e for e in logs if e["event"] == "auth.session_revocation_publish_failed"]
    assert [(e["log_level"], e["session_id"], e["reason"]) for e in failed] == [
        ("error", first, "logout_all")
    ]


async def test_auth_service_publishes_through_the_sink_attached_after_start() -> None:
    clock, repo = _Clock(), FakeSessionRepository()
    auth = AuthService(
        FakeUserRepository(),
        mfa_repository=FakeMfaRepository(),
        session_repository=repo,
        clock=clock,
    )
    ctx: Any = None  # no settings: not a live environment, so process-local keys are used
    await auth.start(ctx)
    sink = _Sink(repo)
    auth.attach_revocation_sink(sink)
    owner, target = str(uuid.uuid4()), str(uuid.uuid4())
    actor = str((await auth.sessions.mint(owner)).session_id)
    await repo.save_step_up_state(
        actor, elevations={"users": clock.now + GRACE_WINDOW}, failures=0, readonly_until=None
    )
    session = str((await auth.sessions.mint(target)).session_id)
    other = str((await auth.sessions.mint(target)).session_id)

    await auth.sessions.revoke(session, reason="user_revoked")
    await auth.step_up.reset_totp(
        actor_session_id=actor, actor_user_id=owner, target_user_id=target
    )
    await auth.stop(grace_s=1.0)

    assert sink.calls == [(session, "user_revoked"), (other, "mfa_reset_by_owner")]


async def test_auth_service_without_an_attached_sink_still_revokes() -> None:
    repo = FakeSessionRepository()
    auth = AuthService(session_repository=repo, clock=_Clock())
    ctx: Any = None
    await auth.start(ctx)
    sid = str((await auth.sessions.mint(str(uuid.uuid4()))).session_id)

    assert await auth.sessions.revoke(sid, reason="logout") is not None
    assert repo.sessions[sid].revoked_at is not None
