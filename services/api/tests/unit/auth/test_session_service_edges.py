"""Edge branches of `SessionService` / `PerIpLoginThrottle` (PR #1638 review:
auth/* per-file coverage floor). No I/O; fake clock."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.auth import session_service
from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionNotFound,
    SessionRevoked,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, SessionService
from candleviewer.auth.throttle import PerIpLoginThrottle

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW

    def __call__(self) -> datetime:
        return self.now


def _svc() -> tuple[SessionService, FakeSessionRepository, _Clock]:
    repo, clock = FakeSessionRepository(), _Clock()
    return SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=clock), repo, clock


def test_default_clock_is_tz_aware_utc() -> None:
    assert session_service._utc_now().tzinfo is UTC  # module default clock


async def test_peek_refresh_is_read_only() -> None:
    svc, repo, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    before = dict(repo.sessions)
    peeked = await svc.peek_refresh(m.refresh_token)
    assert peeked is not None
    assert peeked.id == m.session_id
    assert repo.sessions == before
    assert await svc.peek_refresh("unknown") is None


async def test_reuse_error_carries_every_family_session_id() -> None:
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    nxt = await svc.refresh(m.refresh_token)
    with pytest.raises(RefreshReuseDetected) as info:
        await svc.refresh(m.refresh_token)
    assert set(info.value.revoked_session_ids) == {
        str(m.session_id),
        str(nxt.minted.session_id),
    }


async def test_refresh_of_non_rotated_revoked_session_is_session_revoked() -> None:
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    await svc.revoke(str(m.session_id), reason="logout")
    with pytest.raises(SessionRevoked):
        await svc.refresh(m.refresh_token)


async def test_access_token_lookups_reject_unknown_expired_and_revoked() -> None:
    svc, _, clock = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    with pytest.raises(SessionNotFound):
        await svc.authenticate_access_token("nope")
    await svc.revoke(str(m.session_id), reason="logout")
    with pytest.raises(SessionRevoked):
        await svc.authenticate_access_token(m.access_token)
    clock.now = _NOW + ACCESS_TOKEN_TTL + timedelta(seconds=1)
    with pytest.raises(SessionNotFound):
        await svc.authenticate_access_token(m.access_token)


async def test_require_active_and_unlock_unknown_session_is_not_found() -> None:
    svc, _, _ = _svc()
    with pytest.raises(SessionNotFound):
        await svc.require_active(str(uuid.uuid4()))
    with pytest.raises(SessionNotFound):
        await svc.unlock(str(uuid.uuid4()), password="x", password_hash="y")


async def test_revoke_of_already_revoked_session_returns_none() -> None:
    svc, _, _ = _svc()
    m = await svc.mint(str(uuid.uuid4()))
    assert await svc.revoke(str(m.session_id), reason="logout") is not None
    assert await svc.revoke(str(m.session_id), reason="logout") is None


def test_throttle_retry_after_is_zero_when_not_blocked_and_rounds_up() -> None:
    box = [0.0]
    t = PerIpLoginThrottle(max_attempts=1, window_s=10.0, clock=lambda: box[0])
    assert t.retry_after_s("ip") == 0
    t.record_failure("ip")
    box[0] = 2.5
    assert t.retry_after_s("ip") == 8


def test_throttle_bounded_map_drops_oldest_key() -> None:
    t = PerIpLoginThrottle(max_attempts=1, window_s=10.0, clock=lambda: 0.0, max_tracked_ips=2)
    for ip in ("a", "b", "c"):
        t.record_failure(ip)
    assert not t.is_blocked("a")
    assert t.is_blocked("b")
    assert t.is_blocked("c")


class _YieldingRepository(FakeSessionRepository):
    async def find_by_id(self, session_id: str):  # type: ignore[no-untyped-def]  # test double
        found = await super().find_by_id(session_id)
        await asyncio.sleep(0)  # both callers hold a stale copy before either revokes
        return found


async def test_require_active_racing_expiry_revokes_never_accepts() -> None:
    """#2273: the loser of the expiry-revoke race must not accept the session."""
    repo, clock = _YieldingRepository(), _Clock()
    svc = SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=clock)
    deadline = _NOW + timedelta(minutes=5)
    m = await svc.mint(str(uuid.uuid4()), expires_at=deadline)
    clock.now = deadline
    results = await asyncio.gather(
        svc.require_active(str(m.session_id)),
        svc.require_active(str(m.session_id)),
        return_exceptions=True,
    )
    assert all(isinstance(r, SessionRevoked) for r in results)


@settings(max_examples=50, deadline=None)
@given(offset=st.integers(min_value=-5, max_value=5))
def test_require_active_never_returns_absolute_expired_session(offset: int) -> None:
    async def run() -> None:
        repo, clock = _YieldingRepository(), _Clock()
        svc = SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=clock)
        deadline = _NOW + timedelta(minutes=5)
        m = await svc.mint(str(uuid.uuid4()), expires_at=deadline)
        clock.now = deadline + timedelta(seconds=offset)
        results = await asyncio.gather(
            svc.require_active(str(m.session_id)),
            svc.require_active(str(m.session_id)),
            return_exceptions=True,
        )
        for r in results:
            if offset >= 0:
                assert isinstance(r, SessionRevoked)
            elif not isinstance(r, BaseException):
                assert not r.is_absolute_expired(now=clock.now)

    asyncio.run(run())
