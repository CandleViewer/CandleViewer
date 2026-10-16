"""`SessionService` / `StepUpService` changes for the idle-lock routes (#2300).

`unlock(check=..., write_ahead=...)` (C-2.9: the record precedes the change; a failure counts
even when its record cannot be written), refresh is not activity, authentication never is,
`is_idle_locked_session`, `SessionIdleLocked.idle_locked_at` and `verify_password` on login's
lockout counters. No DB, no network, fixed clock.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import (
    SessionIdleLocked,
    SessionRevoked,
    UnlockPasswordInvalid,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD
from candleviewer.auth.session_service import (
    ACCESS_TOKEN_TTL,
    MAX_UNLOCK_ATTEMPTS,
    PasswordCheck,
    SessionService,
    UnlockOutcome,
    is_idle_locked_session,
)
from candleviewer.auth.step_up import StepUpService

from .auth_fakes import FakeUserRepository, make_user
from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)
_IDLE = timedelta(seconds=300)
_USER = "00000000-0000-4000-8000-0000000000b1"
_PW = "service-canary-pw-2300"  # test-only literal, never a credential


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _AuditDown(Exception):
    """Stands in for the router's audit failure; `unlock()` must not swallow it."""


def _svc() -> tuple[SessionService, FakeSessionRepository, _Clock]:
    repo, clock = FakeSessionRepository(), _Clock()
    return SessionService(repo, Hasher(), clock=clock), repo, clock


async def _locked(svc: SessionService, clock: _Clock) -> str:
    minted = await svc.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    clock.now += _IDLE
    return str(minted.session_id)


def _check(ok: bool) -> PasswordCheck:
    async def check(_password: str) -> bool:
        return ok

    return check


async def test_unlock_hands_the_decision_to_write_ahead_before_lifting_the_lock() -> None:
    svc, repo, clock = _svc()
    sid = await _locked(svc, clock)
    seen: list[tuple[UnlockOutcome, datetime]] = []

    async def ahead(outcome: UnlockOutcome) -> None:
        row = await repo.find_by_id(sid)
        assert row is not None
        seen.append((outcome, row.last_seen_at))

    unlocked = await svc.unlock(sid, password=_PW, check=_check(True), write_ahead=ahead)
    assert seen == [(UnlockOutcome.UNLOCKED, _T0)]  # recorded while the row was still locked
    assert unlocked.last_seen_at == clock.now


async def test_a_failing_write_ahead_leaves_the_lock_in_place() -> None:
    svc, repo, clock = _svc()
    sid = await _locked(svc, clock)

    async def down(_outcome: UnlockOutcome) -> None:
        raise _AuditDown

    with pytest.raises(_AuditDown):
        await svc.unlock(sid, password=_PW, check=_check(True), write_ahead=down)
    row = await repo.find_by_id(sid)
    assert row is not None and row.is_idle_locked(now=clock.now)


async def test_a_wrong_password_counts_even_when_its_record_cannot_be_written() -> None:
    svc, repo, clock = _svc()
    sid = await _locked(svc, clock)
    outcomes: list[UnlockOutcome] = []

    async def down(outcome: UnlockOutcome) -> None:
        outcomes.append(outcome)
        raise _AuditDown

    for _ in range(MAX_UNLOCK_ATTEMPTS):
        with pytest.raises(_AuditDown):
            await svc.unlock(sid, password=_PW, check=_check(False), write_ahead=down)
    assert outcomes == [UnlockOutcome.FAILED] * (MAX_UNLOCK_ATTEMPTS - 1) + [UnlockOutcome.REVOKED]
    row = await repo.find_by_id(sid)
    assert row is not None and not row.is_revoked  # never revoked without its record

    async def up(outcome: UnlockOutcome) -> None:
        outcomes.append(outcome)

    with pytest.raises(SessionRevoked) as revoked:
        await svc.unlock(sid, password=_PW, check=_check(False), write_ahead=up)
    assert revoked.value.reason == "unlock_attempts_exceeded"
    assert outcomes[-1] is UnlockOutcome.REVOKED
    row = await repo.find_by_id(sid)
    assert row is not None and row.revoked_reason == "unlock_attempts_exceeded"


async def test_a_wrong_password_below_the_cap_is_refused_and_recorded_as_failed() -> None:
    svc, _repo, clock = _svc()
    sid = await _locked(svc, clock)
    outcomes: list[UnlockOutcome] = []

    async def ahead(outcome: UnlockOutcome) -> None:
        outcomes.append(outcome)

    with pytest.raises(UnlockPasswordInvalid):
        await svc.unlock(sid, password=_PW, check=_check(False), write_ahead=ahead)
    assert outcomes == [UnlockOutcome.FAILED]


async def test_unlock_needs_a_password_hash_or_a_check() -> None:
    svc, _repo, clock = _svc()
    sid = await _locked(svc, clock)
    with pytest.raises(TypeError):
        await svc.unlock(sid, password=_PW)


async def test_refresh_is_not_activity_the_successor_keeps_the_idle_deadline() -> None:
    svc, repo, clock = _svc()
    minted = await svc.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    clock.now += timedelta(seconds=200)
    outcome = await svc.refresh(minted.refresh_token)
    successor = await repo.find_by_id(str(outcome.minted.session_id))
    assert successor is not None
    assert (successor.last_seen_at, successor.issued_at) == (_T0, clock.now)
    clock.now = _T0 + _IDLE
    with pytest.raises(SessionIdleLocked) as locked:
        await svc.refresh(outcome.minted.refresh_token)
    assert locked.value.idle_locked_at == _T0 + _IDLE


async def test_authenticating_a_request_never_re_stamps_last_seen_at() -> None:
    svc, repo, clock = _svc()
    minted = await svc.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    clock.now += timedelta(seconds=100)
    await svc.authenticate_access_token(minted.access_token)
    await svc.authenticate_access_token(minted.access_token, allow_locked=True)
    row = await repo.find_by_id(str(minted.session_id))
    assert row is not None and row.last_seen_at == _T0
    clock.now = _T0 + _IDLE
    with pytest.raises(SessionIdleLocked) as locked:
        await svc.authenticate_access_token(minted.access_token)
    assert locked.value.idle_locked_at == _T0 + _IDLE
    assert svc.now() == clock.now


async def test_is_idle_locked_session_holds_only_for_an_otherwise_accepted_session() -> None:
    svc, repo, clock = _svc()
    minted = await svc.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    row = await repo.find_by_id(str(minted.session_id))
    assert row is not None
    assert not is_idle_locked_session(row, now=_T0 + _IDLE - timedelta(seconds=1))
    assert is_idle_locked_session(row, now=_T0 + _IDLE)
    assert not is_idle_locked_session(row, now=_T0 + ACCESS_TOKEN_TTL)  # token gone: 401
    assert not is_idle_locked_session(row, now=row.expires_at)  # past the 12 h lifetime
    revoked = await svc.revoke(str(minted.session_id), reason="logout")
    assert revoked is not None and not is_idle_locked_session(revoked, now=_T0 + _IDLE)


async def _step_up(users: FakeUserRepository) -> StepUpService:
    return StepUpService(
        FakeMfaRepository(),
        FakeSessionRepository(),
        TotpEncryptor(os.urandom(32)),
        users,
        Hasher(),
        clock=_Clock(),
    )


async def test_verify_password_uses_the_login_lockout_counters() -> None:
    users = FakeUserRepository()
    hashed = await Hasher().hash(_PW, {"m": 8, "t": 1, "p": 1})
    user = make_user(password_hash=hashed)
    users.add(user)
    svc = await _step_up(users)
    try:
        assert await svc.verify_password(str(user.id), _PW)
        for _ in range(LOCKOUT_THRESHOLD):
            assert not await svc.verify_password(str(user.id), "wrong")
        assert users.users[str(user.id)].locked_until is not None
        assert not await svc.verify_password(str(user.id), _PW)  # locked: fails like a wrong one
        assert not await svc.verify_password(str(uuid.uuid4()), _PW)  # unknown account
    finally:
        await svc.stop()
