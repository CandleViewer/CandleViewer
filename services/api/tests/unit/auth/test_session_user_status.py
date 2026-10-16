"""#2911: no session is minted or rotated for a disabled (or deleted) user (SR-029, E42-T04's
in-flight refresh window). `locked` and `invited` users are not refused: login refuses `disabled`
only, and the issue keeps the other two as they are.

On the fakes: `FakeSessionRepository.user_statuses` plays `users.status`, read with the session
row and checked in the same step as the insert, like the real repository under the user-row
lock. The Postgres side is `tests/integration/auth/test_disabled_user_sessions_pg.py`; the 401s
are `tests/unit/api/test_sessions_router.py` and `tests/unit/api/test_auth_router.py`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest

from candleviewer.auth.errors import UserDisabled
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import SessionService

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_WAIT_S = 5.0  # bounds every wait on the parked refresh: a regression fails instead of hanging
#: Refused: `disabled`, or the user row gone (absent or soft-deleted).
_REFUSED = [pytest.param(UserStatus.DISABLED, id="disabled"), pytest.param(None, id="gone")]
#: Not refused: `active`, and `locked` / `invited` as #2911 keeps them.
_KEPT = [UserStatus.ACTIVE, UserStatus.LOCKED, UserStatus.INVITED]


def _service(repo: FakeSessionRepository) -> SessionService:
    return SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW)


class _ParkedMint(FakeSessionRepository):
    """Parks the mint's insert once armed: the refresh has claimed the presented session and
    has not minted its successor, so a disable can run in between."""

    def __init__(self) -> None:
        super().__init__()
        self.armed = False
        self.parked = asyncio.Event()
        self.release = asyncio.Event()

    async def create_session(self, session: SessionRecord) -> SessionRecord | None:
        if self.armed:
            self.parked.set()
            await self.release.wait()
        return await super().create_session(session)


@pytest.mark.parametrize("status", _REFUSED)
async def test_mint_refuses_a_disabled_user(status: UserStatus | None) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    repo.user_statuses[user] = status

    with pytest.raises(UserDisabled):
        await _service(repo).mint(user)

    assert repo.sessions == {}


@pytest.mark.parametrize("status", _KEPT)
async def test_mint_still_stores_the_session_of_a_user_who_is_not_disabled(
    status: UserStatus,
) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    repo.user_statuses[user] = status

    minted = await _service(repo).mint(user)

    assert list(repo.sessions) == [str(minted.session_id)]


@pytest.mark.parametrize("status", _REFUSED)
async def test_refresh_refuses_a_disabled_user(status: UserStatus | None) -> None:
    """Refused before the claim: the presented session is untouched and nothing is minted."""
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.user_statuses[user] = status

    with pytest.raises(UserDisabled) as refused:
        await service.refresh(minted.refresh_token)

    assert refused.value.status == (None if status is None else status.value)
    presented = repo.sessions[str(minted.session_id)]
    assert presented.revoked_at is None  # not claimed: nothing changed
    assert list(repo.sessions) == [str(minted.session_id)] and repo.rotation_next == {}


@pytest.mark.parametrize("status", _KEPT)
async def test_refresh_still_rotates_for_a_user_who_is_not_disabled(status: UserStatus) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.user_statuses[user] = status

    outcome = await service.refresh(minted.refresh_token)

    assert repo.sessions[str(minted.session_id)].revoked_reason == "rotated"
    assert repo.rotation_next == {str(minted.session_id): str(outcome.minted.session_id)}
    assert repo.sessions[str(outcome.minted.session_id)].revoked_at is None


async def test_refresh_parked_between_claim_and_mint_across_a_disable_mints_nothing() -> None:
    """The window of #2911: the refresh claims while the user is active; the disable (status,
    its own revoke and the post-commit sweep) lands before the mint; the mint is refused."""
    repo, user = _ParkedMint(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.armed = True

    refresh = asyncio.create_task(service.refresh(minted.refresh_token))
    await asyncio.wait_for(repo.parked.wait(), _WAIT_S)
    repo.user_statuses[user] = UserStatus.DISABLED
    swept = await service.revoke_all(user, reason="user_disabled")
    repo.release.set()

    with pytest.raises(UserDisabled):
        await asyncio.wait_for(refresh, _WAIT_S)
    assert swept == ()  # the claimed session was no longer live, and no successor existed yet
    assert await repo.find_live_by_user(user) == ()
    assert repo.rotation_next == {}
