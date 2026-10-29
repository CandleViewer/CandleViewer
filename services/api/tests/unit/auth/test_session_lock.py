"""A session's lock by request (#4743, E09-S03-F1; 22 `authLock`, CMP-098 "Lock now"): a fact its
own row holds (`sessions.locked_at`, `0056_sessions_lock_state`), so every check that reads the
row refuses the session, on this process and after a restart, and only an unlock lifts it. The
lock never moves `last_seen_at` or the idle deadline (BQ-5). No DB, no network, no sleeps."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.errors import SessionIdleLocked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession, SessionRecord
from candleviewer.auth.session_service import SessionService

from .session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 29, 9, 0, 0, tzinfo=UTC)
_USER = "00000000-0000-4000-8000-000000004743"
_PW = "lock-canary-pw-4743"  # test-only literal, never a credential
_IDLE_S = 900
#: Well inside the idle timeout: only `locked_at` can lock the session here.
_EARLY = timedelta(seconds=60)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


_Svc = tuple[SessionService, FakeSessionRepository, _Clock]


def _svc(repo: FakeSessionRepository | None = None) -> _Svc:
    store, clock = repo if repo is not None else FakeSessionRepository(), _Clock()
    return SessionService(store, Hasher(), clock=clock), store, clock


async def _mint(svc: SessionService) -> MintedSession:
    return await svc.mint(_USER, idle_timeout_s=_IDLE_S)


def _row(repo: FakeSessionRepository, minted: MintedSession) -> SessionRecord:
    return repo.sessions[str(minted.session_id)]


def _locked_by_request(repo: FakeSessionRepository, minted: MintedSession, at: datetime) -> None:
    """The row as the lock leaves it (the lock unit's own tests are below)."""
    sid = str(minted.session_id)
    repo.sessions[sid] = repo.sessions[sid].model_copy(update={"locked_at": at})


# -- the stored fact ------------------------------------------------------------------------------


@pytest.mark.parametrize("locked_at", [_T0, _T0 + timedelta(days=365)], ids=["now", "any_value"])
def test_is_idle_locked_is_true_once_locked_at_is_set_before_the_deadline(
    locked_at: datetime,
) -> None:
    """Any value locks, with no clock comparison: a lock by request fails closed. The deadline
    itself does not move, and a revoked session is never "locked"."""
    row = SessionRecord(
        id=uuid.UUID(int=0xA1), user_id=uuid.UUID(_USER), refresh_token_hash="h",
        access_token_jti=None, issued_at=_T0, last_seen_at=_T0,
        expires_at=_T0 + timedelta(hours=12), revoked_at=None, revoked_reason=None, ip=None,
        user_agent=None, device_label=None, is_electron=False, mfa_satisfied_at=_T0,
        idle_timeout_s=_IDLE_S,
    )  # fmt: skip
    assert not row.is_idle_locked(now=_T0 + _EARLY)
    locked = row.model_copy(update={"locked_at": locked_at})
    assert locked.is_idle_locked(now=_T0 + _EARLY)
    assert locked.idle_deadline() == row.idle_deadline() == _T0 + timedelta(seconds=_IDLE_S)
    revoked = locked.model_copy(update={"revoked_at": _T0, "revoked_reason": "logout"})
    assert not revoked.is_idle_locked(now=_T0 + _EARLY)


async def test_require_active_refuses_a_lock_by_request_with_its_unmoved_deadline() -> None:
    svc, repo, clock = _svc()
    minted = await _mint(svc)
    _locked_by_request(repo, minted, _T0)
    clock.now += _EARLY
    with pytest.raises(SessionIdleLocked) as refused:
        await svc.require_active(str(minted.session_id))
    assert refused.value.idle_locked_at == _T0 + timedelta(seconds=_IDLE_S)  # the contract's
    assert (await svc.require_active(str(minted.session_id), allow_locked=True)).locked_at == _T0


async def test_touch_never_restamps_a_session_locked_by_request() -> None:
    """Extend is refused once locked, by the service's check and by the write's own condition."""
    svc, repo, clock = _svc()
    minted = await _mint(svc)
    clock.now += _EARLY
    _locked_by_request(repo, minted, clock.now)
    with pytest.raises(SessionIdleLocked):
        await svc.touch(str(minted.session_id))
    assert await repo.touch_last_seen(str(minted.session_id), now=clock.now) is None
    assert _row(repo, minted).last_seen_at == _T0


async def test_unlock_lifts_a_lock_by_request_clearing_locked_at_and_every_grant() -> None:
    """The password lifts it in the one write that re-stamps `last_seen_at` and clears every
    step-up grant, and stamps `unlocked_at`, which nothing clears."""
    svc, repo, clock = _svc()
    minted = await _mint(svc)
    sid = str(minted.session_id)
    elevations = {"keys": _T0 + timedelta(minutes=5)}
    await repo.save_step_up_state(sid, elevations=elevations, failures=1, readonly_until=None)
    clock.now += _EARLY
    _locked_by_request(repo, minted, clock.now)
    hashed = await Hasher().hash(_PW, {"m": 8, "t": 1, "p": 1})
    clock.now += _EARLY

    unlocked = await svc.unlock(sid, password=_PW, password_hash=hashed)

    at = clock.now
    assert (unlocked.locked_at, unlocked.unlocked_at, unlocked.last_seen_at) == (None, at, at)
    assert unlocked.step_up_elevations == {} and unlocked.step_up_failures == 1
    assert not unlocked.is_idle_locked(now=at)


async def test_refresh_of_a_session_locked_by_request_is_refused_idle_locked() -> None:
    svc, repo, clock = _svc()
    minted = await _mint(svc)
    _locked_by_request(repo, minted, _T0)
    clock.now += _EARLY
    with pytest.raises(SessionIdleLocked) as refused:
        await svc.refresh(minted.refresh_token)
    assert refused.value.idle_locked_at == _T0 + timedelta(seconds=_IDLE_S)
    assert not _row(repo, minted).is_revoked and len(repo.sessions) == 1  # nothing rotated


class _LockBeforeClaim(FakeSessionRepository):
    """A lock by request lands between `refresh()`'s read and its claim: the claim's row holds the
    lock, `presented` does not (on Postgres the two are separate statements)."""

    def __init__(self, at: datetime) -> None:
        super().__init__()
        self.at = at

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        if reason == "rotated":
            self.sessions[session_id] = self.sessions[session_id].model_copy(
                update={"locked_at": self.at}
            )
        return await super().revoke(session_id, reason=reason, now=now)


async def test_the_successor_carries_a_lock_that_landed_before_the_claim() -> None:
    """A rotation never lifts a lock: the successor is minted from the claim's row, locked."""
    svc, repo, clock = _svc(_LockBeforeClaim(_T0 + _EARLY))
    minted = await _mint(svc)
    clock.now += _EARLY * 2

    successor = (await svc.refresh(minted.refresh_token)).minted

    row = repo.sessions[str(successor.session_id)]
    assert row.locked_at == _T0 + _EARLY and row.is_idle_locked(now=clock.now)
    assert row.last_seen_at == _T0  # carried, never moved
    with pytest.raises(SessionIdleLocked):
        await svc.require_active(str(successor.session_id))
