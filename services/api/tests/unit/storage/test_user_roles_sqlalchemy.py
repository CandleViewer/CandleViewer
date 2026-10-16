"""#2492: `SqlAlchemyUserRoleStore` over a fake unit of work (real-DB round trip and the
concurrent-demotion race: tests/integration/auth/test_user_roles_pg.py)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.repositories import owner_floor_sqlalchemy as f
from candleviewer.storage.repositories import user_roles_sqlalchemy as m

_UID, _ACTOR = uuid.uuid4(), uuid.uuid4()
_LOCKED_OWNERS = [f.LOCK_OWNERS, f.COUNT_OWNERS]


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Rel:
    """Fake UoW keyed by statement; records statements, audit calls and the commit."""

    def __init__(
        self, exists: bool = True, owners: int = 1, raise_at: Any = None, counted: int | None = None
    ) -> None:
        roles = [SimpleNamespace(_mapping={"roles": ["owner"]})] if exists else []
        self.rows: dict[Any, list[Any]] = {
            f.LOCK_USER: [("active",)] if exists else [],
            f.LOCK_OWNERS: [(uuid.uuid4(),)] * owners,
            f.ROLES: roles,
            f.COUNT_OWNERS: [(owners if counted is None else counted,)],
        }
        self.raise_at, self.sqlstate = raise_at, "23514"
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
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)

    def order(self) -> list[Any]:
        return [s for s, _ in self.ran]


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


async def _apply(rel: _Rel, audit_error: Exception | None = None) -> bool:
    async def audit(before: frozenset[str]) -> None:
        rel.ran.append(("AUDIT", before))
        if audit_error is not None:
            raise audit_error

    store = m.SqlAlchemyUserRoleStore(rel, owner_floor=_floor)  # type: ignore[arg-type]  # fake
    return await store.apply_roles(_UID, frozenset({"viewer"}), actor=_ACTOR, audit=audit)


async def test_reads_return_effective_roles_none_for_unknown_and_owner_count() -> None:
    store = m.SqlAlchemyUserRoleStore(_Rel(owners=2), owner_floor=_floor)  # type: ignore[arg-type]
    assert await store.get_roles(_UID) == frozenset({"owner"})
    assert await store.count_active_owners() == 2
    gone = m.SqlAlchemyUserRoleStore(_Rel(exists=False), owner_floor=_floor)  # type: ignore[arg-type]
    assert await gone.get_roles(_UID) is None


async def test_apply_roles_unknown_user_returns_false_without_writes_or_audit() -> None:
    rel = _Rel(exists=False)
    assert await _apply(rel) is False
    assert rel.order() == [f.LOCK_USER] and not rel.committed


async def test_apply_roles_last_owner_refused_under_lock_before_any_write_or_audit() -> None:
    rel = _Rel(owners=1)
    with pytest.raises(OwnerFloorError):
        await _apply(rel)
    assert rel.order() == [f.LOCK_USER, *_LOCKED_OWNERS, f.ROLES] and not rel.committed


async def test_apply_roles_floor_counts_after_the_lock_not_the_locked_rows() -> None:
    """E42-T04 AC6: two owner grants were locked, but an owner disabled by the transaction this
    one queued behind is no longer counted, so the demotion of the other is refused."""
    rel = _Rel(owners=2, counted=1)
    with pytest.raises(OwnerFloorError) as refused:
        await _apply(rel)
    assert refused.value.__context__ is None and not rel.committed


async def test_apply_roles_demoting_a_disabled_owner_counts_only_active_owners() -> None:
    """E42-T04: a disabled owner holds none of the counted grants (`counted_roles`), so the
    one other active owner meets the floor; the audit still gets the roles held before."""
    rel = _Rel(owners=1)
    rel.rows[f.LOCK_USER] = [("disabled",)]
    assert await _apply(rel) is True
    assert rel.committed and rel.ran[-1] == ("AUDIT", frozenset({"owner"}))


async def test_apply_roles_writes_ahead_audit_with_the_locked_set_then_commits() -> None:
    rel = _Rel(owners=2)
    assert await _apply(rel) is True
    writes = [m._DROP, m._GRANT, f.CONSTRAINTS_NOW, "AUDIT"]
    assert rel.order() == [f.LOCK_USER, *_LOCKED_OWNERS, f.ROLES, *writes] and rel.committed
    assert rel.ran[-1] == ("AUDIT", frozenset({"owner"}))
    assert rel.ran[5][1] == {"id": str(_UID), "roles": ["viewer"], "by": str(_ACTOR)}


async def test_apply_roles_refused_audit_write_rolls_the_change_back() -> None:
    rel = _Rel(owners=2)
    with pytest.raises(AuditUnavailable):
        await _apply(rel, AuditUnavailable("WAL unwritable"))
    assert not rel.committed


@pytest.mark.parametrize(
    ("status", "sqlstate", "raised"),
    [
        ("active", "23514", OwnerFloorError),
        ("active", "23505", IntegrityError),
        ("disabled", "23514", IntegrityError),  # not this change's floor: re-raised as is
    ],
)
async def test_apply_roles_trigger_check_before_audit_maps_only_the_floor(
    status: str, sqlstate: str, raised: type[Exception]
) -> None:
    rel = _Rel(owners=2, raise_at=f.CONSTRAINTS_NOW)
    rel.rows[f.LOCK_USER], rel.sqlstate = [(status,)], sqlstate
    with pytest.raises(raised):
        await _apply(rel)
    assert "AUDIT" not in rel.order() and not rel.committed
