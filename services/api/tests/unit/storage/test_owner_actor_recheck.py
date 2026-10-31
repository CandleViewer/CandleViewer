"""#2593: the actor of an owner-only write is re-read at the effect, in the write's own unit of
work, after the owner lock and before any write or answer (`require_active_owner`). Offline over a
fake unit of work keyed by statement identity: the order of the statements and where the
write-ahead hooks run. The stores the role, admin, lifecycle, account-access and view-as tests
cover are not repeated here; Postgres (the real locks, the two serial orders of a revoke and an
in-flight write): tests/integration/auth/test_owner_actor_recheck_pg.py, in CI."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.auth.models import SessionRecord
from candleviewer.storage.errors import ACTOR_ROLE_REVOKED, ActorNotAuthorised
from candleviewer.storage.repositories import invites_sqlalchemy as inv
from candleviewer.storage.repositories import owner_floor_sqlalchemy as f
from candleviewer.storage.repositories import owner_totp_reset_sqlalchemy as reset
from candleviewer.storage.repositories import sessions_sqlalchemy as sess

_ACTOR, _TARGET, _SESSION = uuid.UUID(int=0xA), uuid.UUID(int=0xB), uuid.UUID(int=0xC)
_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
_DIGEST = "0" * 64  # a stand-in hash: the stores bind it, nothing reads it
#: The owner lock, the count after it and the actor's fresh re-read, in that order.
_OWNER_LOCK = [f.LOCK_OWNERS, f.COUNT_OWNERS, f.ACTOR_IS_ACTIVE_OWNER]


def _session_row(**over: Any) -> Any:
    fields: dict[str, Any] = {
        "id": str(_SESSION),
        "user_id": str(_TARGET),
        "refresh_token_hash": "h",
        "access_token_jti": None,
        "issued_at": _NOW,
        "last_seen_at": _NOW,
        "expires_at": _NOW,
        "revoked_at": None,
        "revoked_reason": None,
        "ip": None,
        "user_agent": None,
        "device_label": None,
        "is_electron": False,
        "mfa_satisfied_at": _NOW,
        "idle_timeout_s": 900,
        "step_up_elevations": "{}",
        "step_up_failures": 0,
        "readonly_until": None,
        "view_as_context_id": None,
        "view_as_target_user_id": None,
        "view_as_started_at": None,
        "view_as_expires_at": None,
        "view_as_ended_at": None,
        "view_as_end_recorded_at": None,
        "view_as_cleared_at": None,
        "view_as_end_reason": None,
        "locked_at": None,
        "unlocked_at": None,
    }
    return SimpleNamespace(_mapping=fields | over)


class _Result(list[Any]):
    """A result's rows, iterable as SQLAlchemy's `Result` is."""

    def first(self) -> Any:
        return self[0] if self else None

    def all(self) -> list[Any]:
        return list(self)

    def scalar_one(self) -> Any:
        return self[0][0]


class _Rel:
    """Fake unit of work: each statement answers the rows `rows` gives it; records the order,
    the hooks (as strings) and the commit."""

    def __init__(self, *, actor_owner: bool = True, target: bool = True) -> None:
        self.rows: dict[Any, list[Any]] = {
            f.LOCK_USER: [("active",)] if target else [],
            f.COUNT_OWNERS: [(2,)],
            f.ACTOR_IS_ACTIVE_OWNER: [(1,)] if actor_owner else [],
        }
        self.ran: list[Any] = []
        self.params: list[Any] = []
        self.committed = False

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            self.ran.append(stmt)
            self.params.append(params)
            return _Result(self.rows.get(stmt, []))

        async def commit() -> None:
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _hook(rel: _Rel, name: str = "AUDIT") -> Any:
    async def hook(*_args: Any) -> None:
        rel.ran.append(name)

    return hook


# -- the helper -------------------------------------------------------------------------------


async def test_require_active_owner_locks_then_reads_the_actor_afresh_and_answers_the_count() -> (
    None
):
    rel = _Rel()
    async with rel.unit_of_work() as uow:
        assert await f.require_active_owner(uow.session, str(_ACTOR)) == 2
    assert rel.ran == _OWNER_LOCK and rel.params[-1] == {"id": str(_ACTOR)}


async def test_require_active_owner_refuses_an_actor_with_no_active_owner_grant() -> None:
    rel = _Rel(actor_owner=False)
    async with rel.unit_of_work() as uow:
        with pytest.raises(ActorNotAuthorised) as refused:
            await f.require_active_owner(uow.session, str(_ACTOR))
    assert refused.value.actor_id == str(_ACTOR) and str(_ACTOR) not in str(refused.value)
    assert refused.value.code == "STORAGE_ACTOR_NOT_AUTHORISED"


def test_the_actor_statement_is_the_owner_counts_predicate_for_one_user() -> None:
    """A demoted, disabled, deleted or expired owner reads no row: the predicate of
    `COUNT_OWNERS` (the trigger's), narrowed to the actor, read after the lock, never the locked
    id set."""
    sql = str(f.ACTOR_IS_ACTIVE_OWNER)
    for clause in (
        "r.name = 'owner'",
        "u.deleted_at IS NULL",
        "u.status = 'active'",
        "(ur.expires_at IS NULL OR ur.expires_at > now())",
        "ur.user_id = CAST(:id AS uuid)",
    ):
        assert clause in sql
    assert "FOR UPDATE" not in sql
    assert ACTOR_ROLE_REVOKED == "actor_role_revoked"


# -- the owner TOTP reset: one unit of work ----------------------------------------------------


def _reset_store(rel: _Rel) -> reset.SqlAlchemyOwnerTotpReset:
    return reset.SqlAlchemyOwnerTotpReset(rel, lambda **kw: SessionRecord.model_validate(kw))  # type: ignore[arg-type]  # fake


async def test_the_reset_locks_rechecks_then_writes_and_records_ahead_of_the_commit() -> None:
    rel = _Rel()
    rel.rows[reset._REVOKE_METHODS] = [(uuid.uuid4(),), (uuid.uuid4(),)]
    rel.rows[sess.REVOKE_ALL_SQL] = [_session_row()]
    counts: list[tuple[int, int]] = []

    async def audit(methods: int, sessions: int, /) -> None:
        rel.ran.append("AUDIT")
        counts.append((methods, sessions))

    done = await _reset_store(rel).reset_totp(
        str(_TARGET), actor_user_id=str(_ACTOR), now=_NOW, reason="mfa_reset_by_owner", audit=audit
    )
    assert rel.ran == [
        f.LOCK_USER,
        *_OWNER_LOCK,
        reset._REQUIRE_MFA,
        reset._REVOKE_METHODS,
        sess.REVOKE_ALL_SQL,
        "AUDIT",
    ]
    assert rel.committed and counts == [(2, 1)]
    assert done is not None and done[0] == 2 and [s.id for s in done[1]] == [_SESSION]
    assert rel.params[-1] == {
        "u": str(_TARGET),
        "reason": "mfa_reset_by_owner",
        "now": _NOW,
        "except_id": None,
    }


@pytest.mark.parametrize("target", [True, False], ids=["target", "gone"])
async def test_the_reset_by_an_actor_no_longer_an_owner_writes_and_records_nothing(
    target: bool,
) -> None:
    rel = _Rel(actor_owner=False, target=target)
    with pytest.raises(ActorNotAuthorised):
        await _reset_store(rel).reset_totp(
            str(_TARGET), actor_user_id=str(_ACTOR), now=_NOW, reason="r", audit=_hook(rel)
        )
    assert rel.ran == [f.LOCK_USER, *_OWNER_LOCK] and not rel.committed


async def test_the_reset_of_a_target_gone_under_the_lock_is_none_and_writes_nothing() -> None:
    rel = _Rel(target=False)
    got = await _reset_store(rel).reset_totp(
        str(_TARGET), actor_user_id=str(_ACTOR), now=_NOW, reason="r", audit=_hook(rel)
    )
    assert got is None and rel.ran == [f.LOCK_USER, *_OWNER_LOCK] and not rel.committed


async def test_a_refused_reset_record_commits_nothing() -> None:
    rel = _Rel()

    async def refused(_methods: int, _sessions: int, /) -> None:
        raise OSError("audit down")

    with pytest.raises(OSError, match="audit down"):
        await _reset_store(rel).reset_totp(
            str(_TARGET), actor_user_id=str(_ACTOR), now=_NOW, reason="r", audit=refused
        )
    assert not rel.committed


# -- an Owner's revoke of one session ----------------------------------------------------------


def _sessions(rel: _Rel) -> sess.SqlAlchemySessionRepository:
    return sess.SqlAlchemySessionRepository(rel, lambda **kw: SessionRecord.model_validate(kw))  # type: ignore[arg-type]  # fake


async def _revoke(rel: _Rel) -> Any:
    return await _sessions(rel).revoke_by_owner(
        str(_SESSION),
        user_id=str(_TARGET),
        actor_user_id=str(_ACTOR),
        reason="admin",
        now=_NOW,
        write_ahead=_hook(rel),
        audit_timeout_s=1.0,
    )


async def test_the_owner_revoke_locks_rechecks_records_ahead_then_revokes() -> None:
    rel = _Rel()
    rel.rows[sess._LOCK_LIVE_OF_USER_SQL] = [_session_row()]
    rel.rows[sess._REVOKE_SQL] = [_session_row(revoked_at=_NOW, revoked_reason="admin")]
    revoked = await _revoke(rel)
    assert rel.ran == [
        f.LOCK_USER,
        *_OWNER_LOCK,
        sess._LOCK_LIVE_OF_USER_SQL,
        "AUDIT",
        sess._REVOKE_SQL,
    ]
    assert rel.committed and revoked.revoked_reason == "admin"
    assert rel.params[4] == {"id": str(_SESSION), "u": str(_TARGET)}  # that user's session only


async def test_the_owner_revoke_by_an_actor_no_longer_an_owner_records_and_revokes_nothing() -> (
    None
):
    rel = _Rel(actor_owner=False)
    rel.rows[sess._LOCK_LIVE_OF_USER_SQL] = [_session_row()]
    with pytest.raises(ActorNotAuthorised):
        await _revoke(rel)
    assert rel.ran == [f.LOCK_USER, *_OWNER_LOCK] and not rel.committed


async def test_the_owner_revoke_of_a_session_no_longer_live_is_none_unrecorded() -> None:
    rel = _Rel()
    assert await _revoke(rel) is None
    assert rel.ran == [f.LOCK_USER, *_OWNER_LOCK, sess._LOCK_LIVE_OF_USER_SQL]
    assert not rel.committed


# -- the invite writes --------------------------------------------------------------------------


def _invites(rel: _Rel) -> inv.SqlAlchemyInviteRepository:
    return inv.SqlAlchemyInviteRepository(rel, lambda **kw: kw)  # type: ignore[arg-type]  # fake


async def test_an_invite_create_by_an_actor_no_longer_an_owner_creates_nothing() -> None:
    rel = _Rel(actor_owner=False)
    with pytest.raises(ActorNotAuthorised):
        await _invites(rel).create_user_with_invite(
            user_id=_TARGET,
            invite_id=uuid.uuid4(),
            email="t@example.invalid",
            username="t",
            display_name=None,
            role="viewer",
            placeholder_password_hash=_DIGEST,
            invited_by=_ACTOR,
            token_hash=_DIGEST,
            expires_at=_NOW,
            audit=_hook(rel),
        )
    assert rel.ran == _OWNER_LOCK and not rel.committed


async def test_an_invite_create_rechecks_the_actor_before_its_first_write() -> None:
    rel = _Rel()
    await _invites(rel).create_user_with_invite(
        user_id=_TARGET,
        invite_id=uuid.uuid4(),
        email="t@example.invalid",
        username="t",
        display_name=None,
        role="viewer",
        placeholder_password_hash=_DIGEST,
        invited_by=_ACTOR,
        token_hash=_DIGEST,
        expires_at=_NOW,
        audit=_hook(rel),
    )
    assert rel.ran[:4] == [*_OWNER_LOCK, inv.INSERT_INVITED_USER]
    assert rel.ran[-1] == "AUDIT" and rel.committed


async def test_a_reissue_by_an_actor_no_longer_an_owner_mints_nothing() -> None:
    """Refused before the invited-user read: no answer tells a revoked actor whether the user is
    still invited, and no token is minted."""
    rel = _Rel(actor_owner=False)
    with pytest.raises(ActorNotAuthorised):
        await _invites(rel).reissue(
            _TARGET,
            invite_id=uuid.uuid4(),
            token_hash=_DIGEST,
            invited_by=_ACTOR,
            expires_at=_NOW,
            now=_NOW,
            audit=_hook(rel),
        )
    assert rel.ran == [f.LOCK_USER, *_OWNER_LOCK] and not rel.committed


@pytest.mark.parametrize("pending", [True, False], ids=["pending", "none"])
async def test_an_invite_revoke_by_an_actor_no_longer_an_owner_revokes_nothing(
    pending: bool,
) -> None:
    rel = _Rel(actor_owner=False)
    if pending:
        rel.rows[inv._REVOKE] = [SimpleNamespace(role="viewer")]
    with pytest.raises(ActorNotAuthorised):
        await _invites(rel).revoke_open(_TARGET, actor=_ACTOR, now=_NOW, audit=_hook(rel))
    assert rel.ran == [f.LOCK_USER, *_OWNER_LOCK] and not rel.committed


async def test_an_invite_revoke_rechecks_the_actor_first() -> None:
    rel = _Rel()
    rel.rows[inv._REVOKE] = [SimpleNamespace(role="viewer")]
    assert await _invites(rel).revoke_open(_TARGET, actor=_ACTOR, now=_NOW, audit=_hook(rel))
    assert rel.ran == [f.LOCK_USER, *_OWNER_LOCK, inv._REVOKE, "AUDIT"] and rel.committed
