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

`refresh()` checks the stored revocation and the expiry before the user's status, and the status
before the idle lock, so it revokes a disabled user's session where `require_active` does (#3331).
`refresh_refused_as_locked`, the read-only twin of its lock refusal that `POST /auth/refresh`
answers before its write-ahead record (#3331, G2 of #2712), agrees with it on every row.

One level up, `authenticate_access_token` checks the token's life before `require_active`: a
disabled user's expired token is refused as expired, so a socket-only client's row stays live until
its refresh revokes it (#3331; U45, `e09-auth-rbac.md`).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionIdleLocked,
    SessionNotFound,
    SessionRevoked,
    UserDisabled,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import (
    ACCESS_TOKEN_TTL,
    SessionService,
    refresh_refused_as_locked,
)

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
    """What one `require_active` or `refresh()` call did that a client or an operator can see."""

    refusal: str  # `SessionRevoked:<reason>`, `SessionIdleLocked` or `UserDisabled`
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


def _condition(
    repo: FakeSessionRepository,
    sid: str,
    *,
    expired: bool = False,
    revoked_as: str | None = None,
    revoked_without_reason: bool = False,
    idle: bool = False,
) -> None:
    """Set the given conditions on the row of *sid*. `revoked_without_reason` is a revoked row
    with no stored `revoked_reason`."""
    row: dict[str, Any] = {}
    if expired:
        row["expires_at"] = _NOW - timedelta(seconds=1)
    if idle:
        row["last_seen_at"] = _NOW - timedelta(hours=1)
    if revoked_as is not None or revoked_without_reason:
        row.update(revoked_at=_NOW - timedelta(minutes=1), revoked_reason=revoked_as)
    repo.sessions[sid] = repo.sessions[sid].model_copy(update=row)


async def _require_active(
    *,
    refresh: bool = False,
    expired: bool = False,
    revoked_as: str | None = None,
    revoked_without_reason: bool = False,
    disabled: bool = False,
    idle: bool = False,
) -> _Effects:
    """Mint a live session, set the given conditions on its row (`_condition`), and call
    `require_active`, or with *refresh* `refresh()` with its token."""
    repo, pushed = _RevokeSpy(), list[tuple[str, str]]()

    async def publish(session_id: str, reason: str) -> None:
        pushed.append((session_id, reason))

    service = SessionService(
        repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW, publish_revocation=publish
    )
    user = str(uuid.uuid4())
    minted = await service.mint(user)
    sid = str(minted.session_id)
    _condition(
        repo,
        sid,
        expired=expired,
        revoked_as=revoked_as,
        revoked_without_reason=revoked_without_reason,
        idle=idle,
    )
    if disabled:
        repo.user_statuses[user] = UserStatus.DISABLED
    breach, idle_locks = _sample(_BREACH), _sample(_IDLE_LOCKS)

    with pytest.raises((SessionRevoked, SessionIdleLocked, UserDisabled)) as refused:
        if refresh:
            await service.refresh(minted.refresh_token)
        else:
            await service.require_active(sid)

    error = refused.value
    assert {session_id for session_id, _ in pushed} <= {sid}
    return _Effects(
        refusal=(
            f"SessionRevoked:{error.reason}"
            if isinstance(error, SessionRevoked)
            else type(error).__name__
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


_REVOKED_AT_REFRESH = _Effects(
    "UserDisabled", "user_disabled", ("user_disabled",), ("user_disabled",), breach=1
)


@pytest.mark.parametrize(
    ("row", "effects"),
    [
        pytest.param({"expired": True}, _revoked_now("expired"), id="expiry_before_status"),
        pytest.param({"idle": True}, _REVOKED_AT_REFRESH, id="status_before_idle_lock"),
        pytest.param(
            {"revoked_as": "logout"},
            _Effects("SessionRevoked:logout", "logout"),
            id="revoked_before_status",
        ),
    ],
)
async def test_refresh_order_pins_the_backstop(row: dict[str, Any], effects: _Effects) -> None:
    """#3331: a refresh of a disabled user's session revokes and counts where `require_active`
    does. An expired one is revoked as `expired` and counts no breach, an idle-locked one is
    revoked as `user_disabled` and counts one (never left locked), and a revoked one keeps its
    stored reason and is not revoked again."""
    assert await _require_active(refresh=True, disabled=True, **row) == effects


@pytest.mark.parametrize("idle", [False, True], ids=["unlocked", "idle"])
@pytest.mark.parametrize(
    "status", [UserStatus.ACTIVE, UserStatus.DISABLED, None], ids=["active", "disabled", "gone"]
)
@pytest.mark.parametrize("expired", [False, True], ids=["live", "expired"])
@pytest.mark.parametrize(
    "revoked_as", [None, "rotated", "logout"], ids=["unrevoked", "rotated", "logout"]
)
async def test_refresh_refused_as_locked_exactly_when_refresh_refuses_as_locked(
    revoked_as: str | None, expired: bool, status: UserStatus | None, idle: bool
) -> None:
    """#3331: on all 36 rows, the predicate on the row as `peek_refresh` reads it is true
    exactly when `refresh()` raises `SessionIdleLocked`, so the route's early lock answer never
    hides a reuse, a revocation, an expiry or a disabled user."""
    repo = FakeSessionRepository()
    service = SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=lambda: _NOW)
    user = str(uuid.uuid4())
    minted = await service.mint(user)
    _condition(repo, str(minted.session_id), expired=expired, revoked_as=revoked_as, idle=idle)
    repo.user_statuses[user] = status
    presented = await service.peek_refresh(minted.refresh_token)
    assert presented is not None

    try:
        await service.refresh(minted.refresh_token)
    except SessionIdleLocked:
        locked = True
    except (RefreshReuseDetected, SessionRevoked, UserDisabled):
        locked = False
    else:
        locked = False  # rotated

    assert refresh_refused_as_locked(presented, now=_NOW) is locked


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
