"""#2754: `SessionAuditPrincipalResolver` puts the session's last step-up instant on the verified
principal, read from the row `authenticate_access_token` already loaded (no further query), and
the age taken from it is right across the grace window and an idle lock (B16)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import GRACE_WINDOW
from tests.unit.auth.test_step_up import _HASHER, _T0, PASSWORD, _code, _pw_hash, _setup


def _request(bearer: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin/overview",
            "headers": [(b"authorization", f"Bearer {bearer}".encode())],
            "client": ("100.64.0.9", 51000),
        }
    )


class _Identity:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def user(self, user_id: str) -> dict[str, Any]:
        self.calls.append("user")
        return {"username": "owner", "status": "active", "roles": ["owner"]}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        self.calls.append("session_info")
        return {"permissions": ["admin:read"]}


class _Sessions:
    def __init__(self, record: object) -> None:
        self.record = record
        self.calls = 0

    async def authenticate_access_token(self, token: str, *, touch: bool = False) -> Any:
        self.calls += 1
        return self.record


def _row(**extra: object) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), **extra)


async def _resolve(record: object) -> AuditPrincipal:
    resolver = SessionAuditPrincipalResolver(lambda: _Sessions(record), _Identity())
    principal = await resolver.resolve(_request("tok"))
    assert principal is not None
    return principal


async def test_resolver_carries_the_step_up_instant_the_session_row_records() -> None:
    principal = await _resolve(_row(step_up_elevations={"keys": _T0 + GRACE_WINDOW}))
    assert principal.last_step_up_at == _T0


@pytest.mark.parametrize(
    "record",
    [
        _row(step_up_elevations={}),
        _row(step_up_elevations={"pending:keys": _T0 + GRACE_WINDOW}),
        _row(),  # a row that carries no step-up state at all
    ],
    ids=["no-elevations", "pending-challenge-only", "no-step-up-state"],
)
async def test_resolver_leaves_the_instant_none_when_the_row_records_no_step_up(
    record: SimpleNamespace,
) -> None:
    principal = await _resolve(record)
    assert principal.last_step_up_at is None
    assert principal.reauth_age_s(_T0) is None


async def test_resolver_reads_the_step_up_instant_with_no_further_query() -> None:
    sessions = _Sessions(_row(step_up_elevations={"keys": _T0 + GRACE_WINDOW}))
    identity = _Identity()
    resolver = SessionAuditPrincipalResolver(lambda: sessions, identity)
    principal = await resolver.resolve(_request("tok"))
    assert principal is not None and principal.last_step_up_at == _T0
    assert sessions.calls == 1
    assert identity.calls == ["user", "session_info"]


async def test_reauth_age_is_right_across_the_grace_window_and_an_idle_lock() -> None:
    svc, clock, seed, user, sessions = await _setup()
    session_service = SessionService(sessions, _HASHER, clock=clock)
    minted = await session_service.mint(str(user), idle_timeout_s=300)
    sid = str(minted.session_id)
    resolver = SessionAuditPrincipalResolver(lambda: session_service, _Identity())

    async def principal() -> AuditPrincipal:
        got = await resolver.resolve(_request(minted.access_token))
        assert got is not None
        return got

    # Before any step-up there is nothing to age.
    assert (await principal()).reauth_age_s(clock.now) is None

    # Inside the grace window the age is the time since the step-up, not since the request.
    await svc.step_up(str(user), sid, "keys", _code(seed, clock), PASSWORD)
    clock.now = _T0 + timedelta(seconds=90)
    assert (await principal()).reauth_age_s(clock.now) == 90

    # The window ends at 300 s; the step-up still happened, so the age keeps counting.
    clock.now = _T0 + GRACE_WINDOW + timedelta(seconds=1)
    after_window = await principal()
    assert after_window.last_step_up_at == _T0
    assert after_window.reauth_age_s(clock.now) == 301

    # Idle past the 300 s timeout: the session is locked, so there is no principal at all.
    clock.now += timedelta(seconds=301)
    assert await resolver.resolve(_request(minted.access_token)) is None

    # The password-only unlock drops the elevation (B16.7); it does not inherit the step-up.
    clock.now += timedelta(seconds=8)
    await session_service.unlock(sid, password=PASSWORD, password_hash=await _pw_hash())
    assert (await principal()).reauth_age_s(clock.now) is None

    # A step-up after the unlock is aged from its own instant, not from the one before the lock.
    clock.now += timedelta(seconds=10)
    await svc.step_up(str(user), sid, "users", _code(seed, clock), PASSWORD)
    clock.now += timedelta(seconds=30)
    assert (await principal()).reauth_age_s(clock.now) == 30
    await svc.stop()
