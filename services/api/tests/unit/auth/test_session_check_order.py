"""#3029 item 2: the order of the checks in `SessionService.require_active` (absolute expiry,
revoked, the user's status of #2911, idle lock) is behaviour. One test per pair of conditions that
a reordering would answer differently pins it:

- expiry before status: an expired session of a disabled user is revoked as `expired`, not counted
  as a breach.
- revoked before status: a revoked session is refused with the reason it was revoked for and is
  not revoked again, so the retry after a disable's sweep counts nothing.
- status before idle lock: an idle-locked session of a disabled user is revoked, not left locked.
- expiry before idle lock: an expired row is idle too; it is revoked as `expired`, not reported
  as locked.
- expiry before revoked: an expired row that is also revoked, with no reason stored (the column is
  nullable and has no CHECK, 21-database-schema.md), is refused as `expired`, not `revoked`, and
  is not revoked again. With a stored reason either order raises that reason, so this is the one
  case that tells the two apart.

Every one of the other 23 orders changes the outcome of at least one of them.

One level up, `authenticate_access_token` checks the token's life before `require_active`: a
disabled user's expired token is refused as expired, which is how a socket-only client's row stays
live (U45, `e09-auth-rbac.md`).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import SessionIdleLocked, SessionNotFound, SessionRevoked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, SessionService

from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_BREACH = "auth_disabled_user_sessions_revoked_total"
_IDLE_LOCKS = "auth_idle_locks_total"


class _RevokeSpy(FakeSessionRepository):
    """Records the reason of every `revoke` it is asked for, whether or not it changes the row."""

    def __init__(self) -> None:
        super().__init__()
        self.revoke_reasons: list[str] = []

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        self.revoke_reasons.append(reason)
        return await super().revoke(session_id, reason=reason, now=now)


@dataclass(frozen=True)
class _Effects:
    """What one `require_active` call did that a client or an operator can see."""

    refusal: str  # `SessionRevoked:<reason>` or `SessionIdleLocked`
    stored_reason: str | None = None  # `revoked_reason` on the row afterwards
    revokes: tuple[str, ...] = ()  # the reason of each `revoke` the repository was asked for
    published: tuple[str, ...] = ()  # the reason of each revocation pushed to the sockets
    breach: float = 0  # change of the SR-029 breach counter
    idle_locks: float = 0  # change of the idle-lock counter


def _revoked_now(reason: str, *, breach: float = 0) -> _Effects:
    """This call revoked the row as *reason*, and published it."""
    return _Effects(f"SessionRevoked:{reason}", reason, (reason,), (reason,), breach)


def _sample(name: str) -> float:
    return REGISTRY.get_sample_value(name) or 0.0


async def _require_active(
    *,
    expired: bool = False,
    revoked_as: str | None = None,
    revoked_without_reason: bool = False,
    disabled: bool = False,
    idle: bool = False,
) -> _Effects:
    """Mint a live session, set the given conditions on its row, and call `require_active`.
    `revoked_without_reason` is a revoked row with no stored `revoked_reason`."""
    repo, pushed = _RevokeSpy(), list[tuple[str, str]]()

    async def publish(session_id: str, reason: str) -> None:
        pushed.append((session_id, reason))

    service = SessionService(
        repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW, publish_revocation=publish
    )
    user = str(uuid.uuid4())
    sid = str((await service.mint(user)).session_id)
    row: dict[str, Any] = {}
    if expired:
        row["expires_at"] = _NOW - timedelta(seconds=1)
    if idle:
        row["last_seen_at"] = _NOW - timedelta(hours=1)
    if revoked_as is not None or revoked_without_reason:
        row.update(revoked_at=_NOW - timedelta(minutes=1), revoked_reason=revoked_as)
    repo.sessions[sid] = repo.sessions[sid].model_copy(update=row)
    if disabled:
        repo.user_statuses[user] = UserStatus.DISABLED
    breach, idle_locks = _sample(_BREACH), _sample(_IDLE_LOCKS)

    with pytest.raises((SessionRevoked, SessionIdleLocked)) as refused:
        await service.require_active(sid)

    error = refused.value
    assert {session_id for session_id, _ in pushed} <= {sid}
    return _Effects(
        refusal=(
            f"SessionRevoked:{error.reason}"
            if isinstance(error, SessionRevoked)
            else "SessionIdleLocked"
        ),
        stored_reason=repo.sessions[sid].revoked_reason,
        revokes=tuple(repo.revoke_reasons),
        published=tuple(reason for _, reason in pushed),
        breach=_sample(_BREACH) - breach,
        idle_locks=_sample(_IDLE_LOCKS) - idle_locks,
    )


async def test_an_idle_locked_session_moves_the_idle_lock_counter_only() -> None:
    """The control for the rows below: it shows that this file sees the idle-lock counter move."""
    assert await _require_active(idle=True) == _Effects("SessionIdleLocked", idle_locks=1)


async def test_an_expired_session_of_a_disabled_user_is_revoked_as_expired() -> None:
    assert await _require_active(expired=True, disabled=True) == _revoked_now("expired")


@pytest.mark.parametrize("stored", ["logout", "user_disabled"])
async def test_a_revoked_session_of_a_disabled_user_keeps_its_stored_reason(stored: str) -> None:
    """`user_disabled` is the retry after a disable's sweep; `logout` shows the stored reason
    wins over the status. Neither revokes again, counts or publishes."""
    effects = await _require_active(revoked_as=stored, disabled=True)

    assert effects == _Effects(f"SessionRevoked:{stored}", stored)


async def test_an_idle_locked_session_of_a_disabled_user_is_revoked_not_left_locked() -> None:
    assert await _require_active(disabled=True, idle=True) == _revoked_now(
        "user_disabled", breach=1
    )


async def test_an_expired_idle_locked_session_is_revoked_as_expired_not_reported_locked() -> None:
    assert await _require_active(expired=True, idle=True) == _revoked_now("expired")


async def test_an_expired_session_revoked_with_no_stored_reason_is_refused_as_expired() -> None:
    """Expiry is checked before the revocation: the refusal is `expired`, not `revoked`, and
    nothing revokes the row again, counts or publishes."""
    assert await _require_active(expired=True, revoked_without_reason=True) == _Effects(
        "SessionRevoked:expired"
    )


async def test_an_expired_access_token_of_a_disabled_user_is_refused_before_the_backstop() -> None:
    """Refused as expired, not revoked as `user_disabled`: no revoke is asked for, so nothing is
    published, and the breach counter does not move."""
    repo, now = _RevokeSpy(), [_NOW]
    service = SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: now[0])
    user = str(uuid.uuid4())
    minted = await service.mint(user)
    repo.user_statuses[user] = UserStatus.DISABLED
    now[0] = _NOW + ACCESS_TOKEN_TTL
    breach = _sample(_BREACH)

    with pytest.raises(SessionNotFound, match="access token expired"):
        await service.authenticate_access_token(minted.access_token)

    assert repo.sessions[str(minted.session_id)].revoked_at is None
    assert repo.revoke_reasons == [] and _sample(_BREACH) == breach
