"""#2911: a session is minted or rotated only for an `active` user, and a disabled user's live
session is refused and revoked on its next use (SR-029, E42-T04's in-flight refresh window).

On the fakes: `FakeSessionRepository.user_statuses` plays `users.status`, read with the session
row and checked in the same step as the insert, like the real repository under the user-row
lock. The Postgres side is `tests/integration/auth/test_disabled_user_sessions_pg.py`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest

from candleviewer.auth.errors import SessionRevoked, UserNotActive
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import SessionService

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_WAIT_S = 5.0  # bounds every wait on the parked refresh: a regression fails instead of hanging
_NOT_ACTIVE = [UserStatus.DISABLED, UserStatus.LOCKED, UserStatus.INVITED, None]


def _service(
    repo: FakeSessionRepository, published: list[tuple[str, str]] | None = None
) -> SessionService:
    async def publish(session_id: str, reason: str) -> None:
        if published is not None:
            published.append((session_id, reason))

    return SessionService(
        repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW, publish_revocation=publish
    )


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


@pytest.mark.parametrize("status", _NOT_ACTIVE)
async def test_mint_refuses_a_user_who_is_not_active(status: UserStatus | None) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    repo.user_statuses[user] = status

    with pytest.raises(UserNotActive):
        await _service(repo).mint(user)

    assert repo.sessions == {}


async def test_mint_for_an_active_user_still_stores_the_session() -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    repo.user_statuses[user] = UserStatus.ACTIVE

    minted = await _service(repo).mint(user)

    assert list(repo.sessions) == [str(minted.session_id)]


@pytest.mark.parametrize("status", _NOT_ACTIVE)
async def test_refresh_refuses_a_user_who_is_not_active_before_the_claim(
    status: UserStatus | None,
) -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.user_statuses[user] = status

    with pytest.raises(UserNotActive) as refused:
        await service.refresh(minted.refresh_token)

    assert refused.value.status == (None if status is None else status.value)
    presented = repo.sessions[str(minted.session_id)]
    assert presented.revoked_at is None  # not claimed: nothing changed
    assert list(repo.sessions) == [str(minted.session_id)] and repo.rotation_next == {}


async def test_refresh_of_an_active_user_still_rotates() -> None:
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)

    outcome = await service.refresh(minted.refresh_token)

    assert repo.sessions[str(minted.session_id)].revoked_reason == "rotated"
    assert repo.rotation_next == {str(minted.session_id): str(outcome.minted.session_id)}


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

    with pytest.raises(UserNotActive):
        await asyncio.wait_for(refresh, _WAIT_S)
    assert swept == ()  # the claimed session was no longer live, and no successor existed yet
    assert await repo.find_live_by_user(user) == ()
    assert repo.rotation_next == {}


@pytest.mark.parametrize("status", [UserStatus.DISABLED, None])
async def test_require_active_revokes_a_disabled_users_live_session(
    status: UserStatus | None,
) -> None:
    """Fail closed: refused as revoked with `user_disabled`, the row revoked and the id
    published, so the hub ends its sockets with `bye user_disabled` + 4403 (§9.5)."""
    repo, published = FakeSessionRepository(), list[tuple[str, str]]()
    service = _service(repo, published)
    user, bystander = str(uuid.uuid4()), str(uuid.uuid4())
    minted, kept = await service.mint(user), await service.mint(bystander)
    repo.user_statuses[user] = status

    with pytest.raises(SessionRevoked) as refused:
        await service.authenticate_access_token(minted.access_token, touch=True)

    sid = str(minted.session_id)
    assert refused.value.reason == "user_disabled"
    assert repo.sessions[sid].revoked_reason == "user_disabled"
    assert published == [(sid, "user_disabled")]
    assert (await service.require_active(str(kept.session_id))).id == kept.session_id


@pytest.mark.parametrize("status", [UserStatus.LOCKED, UserStatus.INVITED])
async def test_require_active_keeps_a_locked_or_invited_users_live_session(
    status: UserStatus,
) -> None:
    """The issue keeps `locked` and `invited` as they are for a live session: such a session
    cannot be rotated (above), so it ends at its access token's expiry."""
    repo, user = FakeSessionRepository(), str(uuid.uuid4())
    service = _service(repo)
    minted = await service.mint(user)
    repo.user_statuses[user] = status

    assert (await service.require_active(str(minted.session_id))).id == minted.session_id
