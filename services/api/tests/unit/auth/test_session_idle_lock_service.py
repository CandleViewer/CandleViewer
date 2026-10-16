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
from prometheus_client import REGISTRY

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import (
    SessionIdleLocked,
    SessionNotLocked,
    SessionRevoked,
    StepUpRequired,
    UnlockPasswordInvalid,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD
from candleviewer.auth.session_chart import SessionChart
from candleviewer.auth.session_service import (
    ACCESS_TOKEN_TTL,
    MAX_UNLOCK_ATTEMPTS,
    PasswordCheck,
    SessionService,
    UnlockOutcome,
    is_idle_locked_session,
)
from candleviewer.auth.step_up import StepUpChallenge, StepUpService
from tests.conftest import RecordingAuditSink

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


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_the_revoking_wrong_password_counts_the_revocation_as_revoke_does() -> None:
    """The fifth wrong password revokes through the repository, not `revoke()`, so it counts
    what `revoke()` counts: `auth_session_revocations_total{reason}` up, `auth_sessions_active`
    down (the runbook lists the reason for that counter)."""
    svc, _repo, clock = _svc()
    sid = await _locked(svc, clock)
    revocations = _sample("auth_session_revocations_total", reason="unlock_attempts_exceeded")
    active = _sample("auth_sessions_active")
    for _ in range(MAX_UNLOCK_ATTEMPTS - 1):
        with pytest.raises(UnlockPasswordInvalid):
            await svc.unlock(sid, password=_PW, check=_check(False))
    with pytest.raises(SessionRevoked):
        await svc.unlock(sid, password=_PW, check=_check(False))
    counted = _sample("auth_session_revocations_total", reason="unlock_attempts_exceeded")
    assert counted == revocations + 1
    assert _sample("auth_sessions_active") == active - 1


async def test_a_session_revoked_meanwhile_is_not_counted_again_by_the_revoking_password() -> None:
    """Another request ended the session while the fifth password was checked, and its
    `revoke()` counted it: the repository reports no change, so this call counts nothing."""
    svc, _repo, clock = _svc()
    sid = await _locked(svc, clock)
    checks = 0

    async def check(_password: str) -> bool:
        nonlocal checks
        checks += 1
        if checks == MAX_UNLOCK_ATTEMPTS:
            await svc.revoke(sid, reason="logout")
        return False

    unlock = _sample("auth_session_revocations_total", reason="unlock_attempts_exceeded")
    logout = _sample("auth_session_revocations_total", reason="logout")
    active = _sample("auth_sessions_active")
    for _ in range(MAX_UNLOCK_ATTEMPTS - 1):
        with pytest.raises(UnlockPasswordInvalid):
            await svc.unlock(sid, password=_PW, check=check)
    with pytest.raises(SessionRevoked):
        await svc.unlock(sid, password=_PW, check=check)
    assert _sample("auth_session_revocations_total", reason="unlock_attempts_exceeded") == unlock
    assert _sample("auth_session_revocations_total", reason="logout") == logout + 1
    assert _sample("auth_sessions_active") == active - 1  # `revoke()`'s, once


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


async def test_unlock_of_a_session_that_is_not_locked_checks_no_password() -> None:
    """#2300: whoever calls the service, unlock is never a password check (an oracle) nor
    activity on an unlocked session: `SessionNotLocked` before the check is awaited."""
    svc, repo, clock = _svc()
    minted = await svc.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    sid = str(minted.session_id)
    clock.now = _T0 + _IDLE - timedelta(seconds=1)
    checked: list[str] = []
    decided: list[UnlockOutcome] = []

    async def check(candidate: str) -> bool:
        checked.append(candidate)
        return True

    async def ahead(outcome: UnlockOutcome) -> None:
        decided.append(outcome)

    with pytest.raises(SessionNotLocked):
        await svc.unlock(sid, password=_PW, check=check, write_ahead=ahead)
    assert checked == [] and decided == []
    row = await repo.find_by_id(sid)
    assert row is not None and row.last_seen_at == _T0


async def test_touch_never_lifts_a_lock_that_engages_between_the_check_and_the_write() -> None:
    """B16.7 (activity never lifts a lock): the deadline passes after `require_active` let
    the request in; the conditional write refuses the locked row, which is refused as such."""
    svc, repo, _clock = _svc()
    minted = await svc.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    deadline = _T0 + _IDLE
    reads = iter([deadline - timedelta(seconds=1)])  # the check's read; every later one: D
    racing = SessionService(repo, Hasher(), clock=lambda: next(reads, deadline))
    with pytest.raises(SessionIdleLocked) as locked:
        await racing.touch(str(minted.session_id))
    assert locked.value.idle_locked_at == deadline
    row = await repo.find_by_id(str(minted.session_id))
    assert row is not None and row.last_seen_at == _T0


async def test_observe_brings_the_chart_up_to_the_row_and_records_nothing_else(
    b16_audit: RecordingAuditSink,
) -> None:
    """`SessionChart.observe` (the unlock route's first B16 step): builds and hydrates the
    chart, records `IDLE_DEADLINE` once while the row is locked, and sends no other event."""
    svc, repo, clock = _svc()
    minted = await svc.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    row = await repo.find_by_id(str(minted.session_id))
    assert row is not None
    sid, chart = str(row.id), SessionChart()
    try:
        await chart.observe(row, clock.now)
        assert chart.in_state(sid, "active") and b16_audit.calls == []
        clock.now += _IDLE
        for _ in range(2):
            await chart.observe(row, clock.now)
        assert b16_audit.actions() == ["auth.idle_locked"]
        assert chart.in_state(sid, "idle_locked")
    finally:
        await chart.stop()


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
        assert (await svc.verify_password(str(user.id), _PW)).ok
        verdicts = [
            await svc.verify_password(str(user.id), "wrong") for _ in range(LOCKOUT_THRESHOLD)
        ]
        assert not any(v.ok for v in verdicts)
        locked_until = users.users[str(user.id)].locked_until
        assert locked_until is not None
        # Only the failure that locked the account reports it (SR-016: the caller audits it).
        assert [v.locked_until for v in verdicts] == [None] * (LOCKOUT_THRESHOLD - 1) + [
            locked_until
        ]
        locked = await svc.verify_password(str(user.id), _PW)  # fails like a wrong one
        assert (locked.ok, locked.locked_until) == (False, None)
        assert not (await svc.verify_password(str(uuid.uuid4()), _PW)).ok  # unknown account
    finally:
        await svc.stop()


async def test_a_failed_revoke_at_the_cap_keeps_the_count_so_the_next_failure_revokes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2389 gap I: the counter is cleared only once the revoke committed."""
    svc, repo, clock = _svc()
    sid = await _locked(svc, clock)
    for _ in range(MAX_UNLOCK_ATTEMPTS - 1):
        with pytest.raises(UnlockPasswordInvalid):
            await svc.unlock(sid, password=_PW, check=_check(False))
    real_revoke = repo.revoke

    async def broken(session_id: str, **kw: object) -> object:
        raise ConnectionError("db down")

    monkeypatch.setattr(repo, "revoke", broken)
    with pytest.raises(ConnectionError):
        await svc.unlock(sid, password=_PW, check=_check(False))
    monkeypatch.setattr(repo, "revoke", real_revoke)
    with pytest.raises(SessionRevoked):
        await svc.unlock(sid, password=_PW, check=_check(False))
    row = await repo.find_by_id(sid)
    assert row is not None and row.revoked_reason == "unlock_attempts_exceeded"


async def test_allow_locked_access_refuses_a_locked_session_past_its_lifetime() -> None:
    """#2389 gap J: a read allowed while locked answers an expired session as it answers a
    revoked one, even while it is idle-locked and its access token still lives."""
    svc, _repo, clock = _svc()
    minted = await svc.mint(_USER, idle_timeout_s=300, expires_at=_T0 + timedelta(minutes=10))
    clock.now = _T0 + timedelta(minutes=10)  # locked since minute 5; the 12 min token lives
    with pytest.raises(SessionRevoked) as expired:
        await svc.require_active(str(minted.session_id), allow_locked=True)
    assert expired.value.reason == "expired"


async def test_require_active_allowing_the_lock_still_refuses_a_revoked_session() -> None:
    """`allow_locked` waives the idle lock and nothing else: `GET /auth/session` re-reads its
    session through it, so a session revoked after the route's own check is refused."""
    svc, _repo, clock = _svc()
    sid = await _locked(svc, clock)
    await svc.revoke(sid, reason="logout")
    with pytest.raises(SessionRevoked) as revoked:
        await svc.require_active(sid, allow_locked=True)
    assert revoked.value.reason == "logout"


async def test_step_up_grants_of_an_idle_locked_row_authorise_nothing() -> None:
    """#2300 / #2290 rule 4d: void from the lock itself, enforced from the row (C-2.21)."""
    repo, clock = FakeSessionRepository(), _Clock()
    sessions = SessionService(repo, Hasher(), clock=clock)
    minted = await sessions.mint(_USER, idle_timeout_s=int(_IDLE.total_seconds()))
    sid = str(minted.session_id)
    until = _T0 + timedelta(minutes=10)
    fingerprint = "ab" * 32  # the request a no-grace grant is bound to (#2304)
    pending = StepUpChallenge(uuid.uuid4(), "users", until).key()  # a #2304 challenge
    once = StepUpChallenge(uuid.uuid4(), "killswitch", until, fingerprint).key("once:")
    grants = {"keys": until, once: until, pending: until}
    await repo.save_step_up_state(sid, elevations=grants, failures=0, readonly_until=None)
    svc = StepUpService(
        FakeMfaRepository(),
        repo,
        TotpEncryptor(os.urandom(32)),
        FakeUserRepository(),
        Hasher(),
        clock=clock,
    )
    try:
        assert await svc.remaining_grace(sid, "keys") is not None  # live: the grant counts
        assert await svc.pending_action_class(sid) == "users"
        clock.now = _T0 + _IDLE
        assert await svc.remaining_grace(sid, "keys") is None
        assert await svc.pending_action_class(sid) is None
        with pytest.raises(StepUpRequired):
            await svc.require_elevation(sid, "keys")
        with pytest.raises(StepUpRequired):
            await svc.consume_single_use(sid, "killswitch", fingerprint=fingerprint)
        row = await repo.find_by_id(sid)
        assert row is not None and set(row.step_up_elevations) == set(grants)  # read-only
    finally:
        await svc.stop()
