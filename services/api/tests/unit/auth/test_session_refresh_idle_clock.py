"""#4012: a token refresh is no user activity, so it never restarts the idle clock.

`refresh()` mints the successor with the presented session's `last_seen_at` (from the claim's row),
so a tab whose only requests are its access-token refreshes (about every 11 minutes against the
15-minute default) still locks after its idle timeout, and its next refresh is refused
`SessionIdleLocked` (the route answers `401 session_idle_locked`, #3986 G2). An interactive request
still re-stamps `last_seen_at`, and the clock then runs from it. No DB, no network, fixed clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.errors import SessionIdleLocked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession, SessionRecord
from candleviewer.auth.session_service import DEFAULT_IDLE_TIMEOUT_S, SessionService

from .session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 21, 9, 0, 0, tzinfo=UTC)
_USER = "00000000-0000-4000-8000-0000000004b2"
#: The web client's refresh cadence: the 12-minute access token, refreshed a minute early.
_CADENCE = timedelta(minutes=11)
_IDLE = timedelta(seconds=DEFAULT_IDLE_TIMEOUT_S)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


def _svc() -> tuple[SessionService, FakeSessionRepository, _Clock]:
    repo, clock = FakeSessionRepository(), _Clock()
    return SessionService(repo, Hasher(), clock=clock), repo, clock


async def test_refreshes_alone_never_move_the_idle_clock() -> None:
    svc, repo, clock = _svc()
    session: MintedSession = await svc.mint(_USER)

    clock.now += _CADENCE  # the first refresh: 11 minutes idle, within the 15
    session = (await svc.refresh(session.refresh_token)).minted
    assert repo.sessions[str(session.session_id)].last_seen_at == _T0  # carried, not re-stamped

    clock.now += _CADENCE  # 22 minutes since the last activity: the session is idle-locked
    with pytest.raises(SessionIdleLocked):
        await svc.refresh(session.refresh_token)


async def test_an_interactive_request_still_extends_the_session() -> None:
    svc, repo, clock = _svc()
    session = await svc.mint(_USER)
    clock.now += _CADENCE
    session = (await svc.refresh(session.refresh_token)).minted  # last activity is still T0

    clock.now += timedelta(minutes=3)  # 14 minutes in, the user acts with the fresh token
    await svc.authenticate_access_token(session.access_token, touch=True)
    active = clock.now
    clock.now += timedelta(seconds=60)
    session = (await svc.refresh(session.refresh_token)).minted
    assert repo.sessions[str(session.session_id)].last_seen_at == active

    clock.now = active + _IDLE + timedelta(seconds=1)  # the clock runs from the interactive request
    with pytest.raises(SessionIdleLocked):
        await svc.refresh(session.refresh_token)


async def test_a_sign_in_starts_the_idle_clock_at_its_own_time() -> None:
    svc, repo, clock = _svc()
    clock.now += timedelta(hours=1)
    session = await svc.mint(_USER)
    assert repo.sessions[str(session.session_id)].last_seen_at == clock.now


class _TouchBeforeClaim(FakeSessionRepository):
    """An interactive request lands between refresh()'s read and its claim: the claim's row
    holds the newer stamp, `presented` the older one."""

    def __init__(self, at: datetime) -> None:
        super().__init__()
        self.at = at

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        if reason == "rotated":
            await self.touch_last_seen(session_id, now=self.at)
        return await super().revoke(session_id, reason=reason, now=now)


async def test_the_successor_carries_the_claims_stamp_not_the_read_one() -> None:
    clock = _Clock()
    touched = _T0 + timedelta(minutes=5)
    repo = _TouchBeforeClaim(touched)
    svc = SessionService(repo, Hasher(), clock=clock)
    session = await svc.mint(_USER)
    clock.now += timedelta(minutes=6)

    successor = (await svc.refresh(session.refresh_token)).minted

    assert repo.sessions[str(successor.session_id)].last_seen_at == touched  # not _T0
