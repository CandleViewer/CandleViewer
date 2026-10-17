"""E42-T04 S3 (#965): `SqlAlchemyUserLifecycleStore` over a fake unit of work (the real-DB
transaction, rollback and owner-race cases: tests/integration/admin/test_user_lifecycle_pg.py)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories import owner_floor_sqlalchemy as f
from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as m
from candleviewer.storage.repositories.user_lifecycle import (
    GrantLevel,
    UserSelfTargetError,
    UserStatusChange,
)

_UID, _ACTOR = uuid.uuid4(), uuid.uuid4()
_S1, _S2 = sorted((uuid.uuid4(), uuid.uuid4()))
_A, _B = sorted((uuid.uuid4(), uuid.uuid4()))
_NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
#: Ends a hang if the store stops bounding its audit hook; never reached when it does.
_GUARD_S = 5.0


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _DriverUUID(uuid.UUID):
    """Stands in for asyncpg's `uuid.UUID` subclass."""


class _Rel:
    """Fake UoW keyed by statement; records statements, the audit call and the commit."""

    def __init__(
        self,
        status: str | None = "active",
        roles: Sequence[str] = ("manager",),
        owners: int = 2,
        sessions: Sequence[uuid.UUID] = (_S2, _S1),
        grants: Sequence[tuple[uuid.UUID, bool]] = ((_A, True), (_B, False)),
        raise_at: Any = None,
        sqlstate: str = "23514",
        commit_error: BaseException | None = None,
    ) -> None:
        found = status is not None
        self.rows: dict[Any, list[Any]] = {
            f.LOCK_USER: [(status,)] if found else [],
            f.ROLES: [SimpleNamespace(_mapping={"roles": list(roles)})] if found else [],
            f.LOCK_OWNERS: [(uuid.uuid4(),)] * 2,  # the floor reads the fresh count, not these
            f.COUNT_OWNERS: [(owners,)],
            m._REVOKE_SESSIONS: [(_DriverUUID(str(s)),) for s in sessions],
            m._LIVE_GRANTS: [(_DriverUUID(str(a)), trade) for a, trade in grants],
        }
        self.raise_at, self.sqlstate, self.commit_error = raise_at, sqlstate, commit_error
        self.ran, self.committed = list[Any](), False

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            self.ran.append((stmt, params))
            if stmt is self.raise_at:
                raise IntegrityError("SET CONSTRAINTS", None, _PgError(self.sqlstate))
            rows = self.rows.get(stmt, [])
            return SimpleNamespace(
                first=lambda: rows[0] if rows else None,
                all=lambda: rows,
                scalar_one=lambda: rows[0][0],
            )

        async def commit() -> None:
            if self.commit_error is not None:
                raise self.commit_error
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)

    def order(self) -> list[Any]:
        return [s for s, _ in self.ran]


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


def _store(rel: Any, timeout_s: float = m.AUDIT_TIMEOUT_S) -> m.SqlAlchemyUserLifecycleStore:
    """`rel` is the fake unit of work, typed `Any` in place of the real repository."""
    return m.SqlAlchemyUserLifecycleStore(rel, owner_floor=_floor, audit_timeout_s=timeout_s)


def _hook(rel: _Rel, error: BaseException | None = None) -> Any:
    async def audit(change: UserStatusChange) -> None:
        rel.ran.append(("AUDIT", change))
        if error is not None:
            raise error

    return audit


async def _disable(rel: _Rel, error: BaseException | None = None) -> UserStatusChange | None:
    return await _store(rel).disable(_UID, actor=_ACTOR, now=_NOW, audit=_hook(rel, error))


_LOCKED = [f.LOCK_USER, f.ROLES, f.LOCK_OWNERS, f.COUNT_OWNERS]
_CASCADE = [m._DISABLE, m._REVOKE_SESSIONS, m._LIVE_GRANTS, m._REVOKE_GRANTS]


async def test_disable_statement_order_lock_user_lock_owners_dml_constraints_audit_commit() -> None:
    rel = _Rel()
    change = await _disable(rel)
    assert rel.order() == [*_LOCKED, *_CASCADE, f.CONSTRAINTS_NOW, "AUDIT"] and rel.committed
    revoking: dict[uuid.UUID, GrantLevel] = {_A: "trade", _B: "read"}
    expected = UserStatusChange(
        _UID, "active", "disabled", frozenset({"manager"}), (_S1, _S2), revoking
    )
    assert change == rel.ran[-1][1] == expected
    assert change is not None  # the ids are plain `uuid.UUID`s, not the driver's subclass
    assert all(type(i) is uuid.UUID for i in (*change.revoked_session_ids, *change.revoked_grants))
    assert rel.ran[5][1] == {"id": str(_UID), "now": _NOW, "reason": "user_disabled"}
    assert rel.ran[7][1] == {"id": str(_UID), "revoked": [str(_A), str(_B)]}


async def test_disable_with_no_session_or_grant_revokes_none_and_audits_once() -> None:
    """AC5's first disable: nothing to revoke, so the grant revoke binds an empty array."""
    rel = _Rel(sessions=(), grants=())
    change = await _disable(rel)
    assert rel.order() == [*_LOCKED, *_CASCADE, f.CONSTRAINTS_NOW, "AUDIT"] and rel.committed
    assert change is not None and change.changed and change == rel.ran[-1][1]
    assert (change.revoked_session_ids, change.revoked_grants) == ((), {})
    assert rel.ran[7][1] == {"id": str(_UID), "revoked": []}


async def test_disable_self_target_refused_before_any_statement() -> None:
    rel = _Rel()
    with pytest.raises(UserSelfTargetError):
        await _store(rel).disable(_UID, actor=_UID, now=_NOW, audit=_hook(rel))
    assert rel.ran == [] and not rel.committed


async def test_disable_unknown_user_returns_none_without_writes_or_audit() -> None:
    rel = _Rel(status=None)
    assert await _disable(rel) is None
    assert rel.order() == [f.LOCK_USER] and not rel.committed


async def test_disable_already_disabled_user_is_noop_without_owner_lock_writes_or_audit() -> None:
    rel = _Rel(status="disabled")
    change = await _disable(rel)
    assert change == UserStatusChange(_UID, "disabled", "disabled", frozenset({"manager"}))
    assert not change.changed
    assert rel.order() == [f.LOCK_USER, f.ROLES] and not rel.committed


async def test_disable_last_active_owner_refused_under_lock_before_any_write_or_audit() -> None:
    """Two owner grants are locked, but the count read after the lock sees one active owner."""
    rel = _Rel(roles=("owner",), owners=1)
    with pytest.raises(OwnerFloorError) as refused:
        await _disable(rel)
    assert refused.value.__context__ is None  # the locked count, not the trigger
    assert rel.order() == _LOCKED and not rel.committed


@pytest.mark.parametrize("status", ["invited", "locked"])
async def test_disable_owner_who_is_not_active_is_not_held_to_the_floor(status: str) -> None:
    rel = _Rel(status=status, roles=("owner",), owners=1)
    change = await _disable(rel)
    assert change is not None and change.before == status and rel.committed


async def test_disable_audit_hook_raise_rolls_the_change_back() -> None:
    rel = _Rel()
    with pytest.raises(AuditUnavailable):
        await _disable(rel, AuditUnavailable("WAL unwritable"))
    assert rel.order()[-1] == "AUDIT" and not rel.committed


async def test_disable_audit_hook_that_never_returns_times_out_and_rolls_back() -> None:
    """The row locks are released in bounded time; the guard only ends a regression's hang."""
    rel, gate = _Rel(), asyncio.Event()

    async def stuck(change: UserStatusChange) -> None:
        rel.ran.append(("AUDIT", change))
        await gate.wait()

    store = _store(rel, timeout_s=0)
    call = asyncio.create_task(store.disable(_UID, actor=_ACTOR, now=_NOW, audit=stuck))
    done, _ = await asyncio.wait({call}, timeout=_GUARD_S)
    gate.set()
    assert call in done, "the audit hook was not bounded"
    with pytest.raises(WriteAheadTimeout):  # typed: rolled back, nothing changed
        call.result()
    assert rel.order()[-1] == "AUDIT" and not rel.committed


async def test_disable_commit_timeout_is_raised_as_is_with_the_outcome_unknown() -> None:
    """Only the hook's bound is `WriteAheadTimeout`; a commit's `TimeoutError` is not one."""
    rel = _Rel(commit_error=TimeoutError("commit lost"))
    with pytest.raises(TimeoutError) as raised:
        await _disable(rel)
    assert type(raised.value) is TimeoutError and rel.order()[-1] == "AUDIT"


@pytest.mark.parametrize(
    ("role", "sqlstate", "raised"),
    [
        ("owner", "23514", OwnerFloorError),
        ("owner", "23505", IntegrityError),
        ("manager", "23514", IntegrityError),  # not this change's floor: re-raised as is
    ],
)
async def test_disable_trigger_check_before_audit_maps_only_the_floor(
    role: str, sqlstate: str, raised: type[Exception]
) -> None:
    rel = _Rel(roles=(role,), raise_at=f.CONSTRAINTS_NOW, sqlstate=sqlstate)
    with pytest.raises(raised):
        await _disable(rel)
    assert "AUDIT" not in rel.order() and not rel.committed
