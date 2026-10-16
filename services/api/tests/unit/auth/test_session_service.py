"""Unit tests for `candleviewer.auth.session_service.SessionService`,
E09-S03 (US-ONB-004/009). Each test name maps to a ticket Gherkin scenario.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth import session_service
from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionIdleLocked,
    SessionNotFound,
    SessionRevoked,
    UnlockPasswordInvalid,
)
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, Hasher
from candleviewer.auth.session_service import (
    ABSOLUTE_LIFETIME,
    DEFAULT_IDLE_TIMEOUT_S,
    MAX_IDLE_TIMEOUT_S,
    SessionService,
    clamp_idle_timeout_s,
)

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


def _hasher() -> Hasher:
    return Hasher(pepper=os.urandom(16).hex())


def _service(repo: FakeSessionRepository, clock: _MutableClock) -> SessionService:
    return SessionService(repo, _hasher(), clock=clock)


# -- mint --------------------------------------------------------------


async def test_mint_creates_a_fresh_session_id_and_refresh_token() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    user_id = str(uuid.uuid4())

    minted = await service.mint(user_id)

    assert minted.session_id is not None
    assert (minted.expires_at - minted.issued_at) == ABSOLUTE_LIFETIME
    stored = repo.sessions[str(minted.session_id)]
    assert stored.refresh_token_hash != minted.refresh_token  # never stored raw
    assert stored.idle_timeout_s == DEFAULT_IDLE_TIMEOUT_S


def test_clamp_idle_timeout_s_enforces_5_to_60_minutes() -> None:
    assert clamp_idle_timeout_s(60) == 300
    assert clamp_idle_timeout_s(999_999) == 3600
    assert clamp_idle_timeout_s(900) == 900


# -- idle lock -----------------------------------------------------------


async def test_idle_lock_preserves_the_data_feed() -> None:
    """ "Idle lock preserves the data feed": after the idle timeout, the
    session is refused (locked) but NOT revoked — no re-snapshot/teardown
    signal is produced (a `SessionRevoked` never fires)."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=900)

    clock.advance(timedelta(minutes=15, seconds=1))

    with pytest.raises(SessionIdleLocked):
        await service.require_active(str(minted.session_id))

    stored = repo.sessions[str(minted.session_id)]
    assert stored.revoked_at is None  # WS subscriptions intact, not torn down


async def test_touch_before_idle_deadline_resets_the_clock() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=900)

    clock.advance(timedelta(minutes=10))
    await service.touch(str(minted.session_id))
    clock.advance(timedelta(minutes=10))  # 20 min total, but touch reset at 10

    # Still active: only 10 min since the touch.
    session = await service.require_active(str(minted.session_id))
    assert session.revoked_at is None


# -- absolute expiry -------------------------------------------------------


async def test_absolute_expiry_disarms_trading_by_revoking() -> None:
    """ "Absolute expiry disarms trading": session older than 12h is fully
    revoked (not merely idle-locked) — the caller maps `SessionRevoked` to
    the full-sign-out + WS-4401 path and disarms one-click trading."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()))

    clock.advance(ABSOLUTE_LIFETIME + timedelta(seconds=1))

    with pytest.raises(SessionRevoked):
        await service.require_active(str(minted.session_id))

    stored = repo.sessions[str(minted.session_id)]
    assert stored.revoked_at is not None
    assert stored.revoked_reason == "expired"


# -- order entry refusal while locked --------------------------------------


async def test_order_entry_refused_while_idle_locked_regardless_of_client() -> None:
    """ "Order entry is refused while locked": the server-side check is the
    source of truth, independent of anything the client believes."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=300)

    clock.advance(timedelta(minutes=5, seconds=1))

    with pytest.raises(SessionIdleLocked):
        await service.require_active(str(minted.session_id))


# -- unlock ------------------------------------------------------------


async def test_unlock_restores_context_with_password_only() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    hasher = _hasher()
    service = SessionService(repo, hasher, clock=clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=300)
    clock.advance(timedelta(minutes=5, seconds=1))

    password_hash = await hasher.hash("correct horse battery staple", DEFAULT_ARGON2_PARAMS)
    unlocked = await service.unlock(
        str(minted.session_id),
        password="correct horse battery staple",
        password_hash=password_hash,
    )
    assert unlocked.revoked_at is None
    # No longer idle-locked: last_seen_at was just re-stamped.
    active = await service.require_active(str(minted.session_id))
    assert active.id == unlocked.id


async def test_unlock_wrong_password_is_refused() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    hasher = _hasher()
    service = SessionService(repo, hasher, clock=clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=300)
    clock.advance(timedelta(minutes=5, seconds=1))

    password_hash = await hasher.hash("correct horse battery staple", DEFAULT_ARGON2_PARAMS)
    with pytest.raises(UnlockPasswordInvalid):
        await service.unlock(str(minted.session_id), password="wrong", password_hash=password_hash)
    # A single wrong guess does not revoke the session (distinct from a
    # terminal `SessionRevoked` — it is still idle-locked, not dead).
    stored = repo.sessions[str(minted.session_id)]
    assert stored.revoked_at is None


async def test_unlock_throttles_after_five_consecutive_wrong_passwords() -> None:
    """Review finding (PR #1628, low): unlock attempts must be throttled.
    The 5th consecutive wrong password revokes the session outright."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    hasher = _hasher()
    service = SessionService(repo, hasher, clock=clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=300)
    clock.advance(timedelta(minutes=5, seconds=1))

    password_hash = await hasher.hash("correct horse battery staple", DEFAULT_ARGON2_PARAMS)
    for _ in range(4):
        with pytest.raises(UnlockPasswordInvalid):
            await service.unlock(
                str(minted.session_id), password="wrong", password_hash=password_hash
            )

    with pytest.raises(SessionRevoked) as excinfo:
        await service.unlock(str(minted.session_id), password="wrong", password_hash=password_hash)
    assert excinfo.value.reason == "unlock_attempts_exceeded"
    stored = repo.sessions[str(minted.session_id)]
    assert stored.revoked_at is not None


async def test_unlock_success_resets_the_wrong_password_counter() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    hasher = _hasher()
    service = SessionService(repo, hasher, clock=clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=300)
    clock.advance(timedelta(minutes=5, seconds=1))

    password_hash = await hasher.hash("correct horse battery staple", DEFAULT_ARGON2_PARAMS)
    for _ in range(3):
        with pytest.raises(UnlockPasswordInvalid):
            await service.unlock(
                str(minted.session_id), password="wrong", password_hash=password_hash
            )

    await service.unlock(
        str(minted.session_id),
        password="correct horse battery staple",
        password_hash=password_hash,
    )
    assert session_service.MAX_UNLOCK_ATTEMPTS > 1
    assert service._unlock_failures.get(str(minted.session_id)) is None


async def test_unlock_after_absolute_expiry_fails_and_becomes_full_signin() -> None:
    """ "if the absolute lifetime elapses while locked, unlocking fails and
    becomes a full sign-in" — `unlock()` raises rather than re-minting."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    hasher = _hasher()
    service = SessionService(repo, hasher, clock=clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=300)
    clock.advance(ABSOLUTE_LIFETIME + timedelta(seconds=1))

    password_hash = await hasher.hash("correct horse battery staple", DEFAULT_ARGON2_PARAMS)
    with pytest.raises(SessionRevoked):
        await service.unlock(
            str(minted.session_id),
            password="correct horse battery staple",
            password_hash=password_hash,
        )


# -- revoke one session --------------------------------------------------


async def test_revoke_one_session_leaves_others_of_the_same_user_untouched() -> None:
    """ "Revoke one session": two active sessions, revoking one leaves the
    other unaffected (own-session isolation)."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    user_id = str(uuid.uuid4())
    a = await service.mint(user_id)
    b = await service.mint(user_id)

    revoked = await service.revoke(str(a.session_id), reason="admin")

    assert revoked is not None
    assert revoked.revoked_reason == "admin"
    still_live = repo.sessions[str(b.session_id)]
    assert still_live.revoked_at is None


async def test_sign_out_everywhere_revokes_all_but_can_exclude_current() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    user_id = str(uuid.uuid4())
    a = await service.mint(user_id)
    b = await service.mint(user_id)

    revoked = await service.revoke_all(
        user_id, reason="logout", except_session_id=str(a.session_id)
    )

    assert {str(r.id) for r in revoked} == {str(b.session_id)}
    assert repo.sessions[str(a.session_id)].revoked_at is None
    assert repo.sessions[str(b.session_id)].revoked_at is not None


# -- refresh rotation / reuse detection ------------------------------------


async def test_refresh_rotates_the_token_and_revokes_the_old_session() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()))

    outcome = await service.refresh(minted.refresh_token)

    assert outcome.previous_session_id == minted.session_id
    old = repo.sessions[str(minted.session_id)]
    assert old.revoked_reason == "rotated"
    new = repo.sessions[str(outcome.minted.session_id)]
    assert new.revoked_at is None


async def test_refresh_token_reuse_kills_the_entire_family() -> None:
    """ "Refresh-token reuse kills the family": presenting an
    already-rotated refresh token revokes the entire family transitively."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()))
    outcome = await service.refresh(minted.refresh_token)

    # Attacker replays the original (now-rotated) refresh token.
    with pytest.raises(RefreshReuseDetected):
        await service.refresh(minted.refresh_token)

    old = repo.sessions[str(minted.session_id)]
    new = repo.sessions[str(outcome.minted.session_id)]
    # The already-dead presented session keeps its original `rotated`
    # reason (already unusable — revocation is idempotent, INV-B16-d);
    # the live successor is the one that must now be shut down too.
    assert old.revoked_reason == "rotated"
    assert new.revoked_reason == "rotation_reuse"


async def test_refresh_preserves_the_original_absolute_expiry() -> None:
    """Review finding (PR #1628, high): refresh() must not reset the 12 h
    absolute lifetime — the successor keeps the presented session's own
    `expires_at`, so repeated refreshing cannot outlive the original cap."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=MAX_IDLE_TIMEOUT_S)
    original_expires_at = minted.expires_at

    clock.advance(timedelta(minutes=30))
    outcome = await service.refresh(minted.refresh_token)
    assert outcome.minted.expires_at == original_expires_at

    # #2300: a refresh is not activity, so the chain stays unlocked only through extend.
    await service.touch(str(outcome.minted.session_id))
    clock.advance(timedelta(minutes=30))
    outcome2 = await service.refresh(outcome.minted.refresh_token)
    assert outcome2.minted.expires_at == original_expires_at

    # Confirms the cap is real: once `now` passes the original deadline,
    # even a session that was refreshed along the way is expired.
    clock.advance(ABSOLUTE_LIFETIME)
    with pytest.raises(SessionRevoked) as excinfo:
        await service.refresh(outcome2.minted.refresh_token)
    assert excinfo.value.reason == "expired"


async def test_concurrent_refresh_of_the_same_token_only_mints_one_successor() -> None:
    """Review finding (PR #1628, medium): rotation claims the presented
    session by revoking it first and checking the result, so two
    "simultaneous" refreshes of the same token cannot both mint a
    successor — the second observes its `revoke()` return `None` (already
    claimed) and is treated as reuse instead of silently minting twice."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()))

    # Simulate two callers racing on the same token by directly exercising
    # the repository-level claim the second `refresh()` call would make:
    # the first revoke() succeeds, the second (idempotent) revoke() of the
    # same already-revoked row returns None.
    first_claim = await repo.revoke(str(minted.session_id), reason="rotated", now=clock())
    assert first_claim is not None
    second_claim = await repo.revoke(str(minted.session_id), reason="rotated", now=clock())
    assert second_claim is None

    # End-to-end: a second refresh() call against the now-rotated token
    # raises reuse rather than minting another successor.
    with pytest.raises(RefreshReuseDetected):
        await service.refresh(minted.refresh_token)
    live_sessions = [s for s in repo.sessions.values() if s.revoked_at is None]
    assert len(live_sessions) == 0


async def test_refresh_unknown_token_raises_session_not_found() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)

    with pytest.raises(SessionNotFound):
        await service.refresh("no-such-token")


async def test_refresh_while_idle_locked_is_refused_without_revoking() -> None:
    """ "The lock does not refresh tokens in the background": a refresh call
    against an idle-locked session is refused, not silently granted, and
    the session is not torn down by the attempt."""
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=300)
    clock.advance(timedelta(minutes=5, seconds=1))

    with pytest.raises(SessionIdleLocked):
        await service.refresh(minted.refresh_token)

    stored = repo.sessions[str(minted.session_id)]
    assert stored.revoked_at is None


# -- introspection / listing ----------------------------------------------


async def test_list_sessions_marks_the_current_one() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    user_id = str(uuid.uuid4())
    a = await service.mint(user_id)
    await service.mint(user_id)

    views = await service.list_sessions(user_id, current_session_id=str(a.session_id))

    current = [v for v in views if v.current]
    assert len(current) == 1
    assert current[0].id == a.session_id


async def test_introspect_returns_idle_deadline() -> None:
    repo = FakeSessionRepository()
    clock = _MutableClock(_NOW)
    service = _service(repo, clock)
    minted = await service.mint(str(uuid.uuid4()), idle_timeout_s=900)

    info = await service.introspect(str(minted.session_id))

    assert info.idle_deadline == minted.issued_at + timedelta(seconds=900)
