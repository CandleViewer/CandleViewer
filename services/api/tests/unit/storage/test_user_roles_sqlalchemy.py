"""#2492: `SqlAlchemyUserRoleStore` over a fake unit of work (real-DB round trip and the
concurrent-demotion race: tests/integration/auth/test_user_roles_pg.py)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories import user_roles_sqlalchemy as m

_UID, _ACTOR = uuid.uuid4(), uuid.uuid4()


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Rel:
    """Fake UoW keyed by statement; records statements, audit calls and the commit."""

    def __init__(self, exists: bool = True, owners: int = 1, raise_at: Any = None) -> None:
        roles = [SimpleNamespace(_mapping={"roles": ["owner"]})] if exists else []
        self.rows: dict[Any, list[Any]] = {
            m._LOCK_USER: [(1,)] if exists else [],
            m._LOCK_OWNERS: [(uuid.uuid4(),)] * owners,
            m._ROLES: roles,
            m._COUNT_OWNERS: [(owners,)],
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
                first=lambda: rows[0] if rows else None, all=lambda: rows, scalar_one=lambda: 2
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
    store = m.SqlAlchemyUserRoleStore(_Rel(), owner_floor=_floor)  # type: ignore[arg-type]
    assert await store.get_roles(_UID) == frozenset({"owner"})
    assert await store.count_active_owners() == 2
    gone = m.SqlAlchemyUserRoleStore(_Rel(exists=False), owner_floor=_floor)  # type: ignore[arg-type]
    assert await gone.get_roles(_UID) is None


async def test_apply_roles_unknown_user_returns_false_without_writes_or_audit() -> None:
    rel = _Rel(exists=False)
    assert await _apply(rel) is False
    assert rel.order() == [m._LOCK_USER] and not rel.committed


async def test_apply_roles_last_owner_refused_under_lock_before_any_write_or_audit() -> None:
    rel = _Rel(owners=1)
    with pytest.raises(OwnerFloorError):
        await _apply(rel)
    assert rel.order() == [m._LOCK_USER, m._LOCK_OWNERS, m._ROLES] and not rel.committed


async def test_apply_roles_writes_ahead_audit_with_the_locked_set_then_commits() -> None:
    rel = _Rel(owners=2)
    assert await _apply(rel) is True
    writes = [m._DROP, m._GRANT, m._CONSTRAINTS_NOW, "AUDIT"]
    assert rel.order() == [m._LOCK_USER, m._LOCK_OWNERS, m._ROLES, *writes] and rel.committed
    assert rel.ran[-1] == ("AUDIT", frozenset({"owner"}))
    assert rel.ran[4][1] == {"id": str(_UID), "roles": ["viewer"], "by": str(_ACTOR)}


async def test_apply_roles_refused_audit_write_rolls_the_change_back() -> None:
    rel = _Rel(owners=2)
    with pytest.raises(AuditUnavailable):
        await _apply(rel, AuditUnavailable("WAL unwritable"))
    assert not rel.committed


@pytest.mark.parametrize(
    ("sqlstate", "raised"), [("23514", OwnerFloorError), ("23505", IntegrityError)]
)
async def test_apply_roles_trigger_check_before_audit_maps_only_the_floor(
    sqlstate: str, raised: type[Exception]
) -> None:
    rel = _Rel(owners=2, raise_at=m._CONSTRAINTS_NOW)
    rel.sqlstate = sqlstate
    with pytest.raises(raised):
        await _apply(rel)
    assert "AUDIT" not in rel.order() and not rel.committed


async def test_apply_roles_hung_audit_is_bounded_and_rolls_back() -> None:
    """#2510: a hung WAL append under the user and owner locks times out; nothing commits."""
    rel = _Rel(owners=2)

    async def hang(before: frozenset[str]) -> None:
        await asyncio.Event().wait()

    fake: Any = rel  # a fake unit of work, not a SqlAlchemyRelationalRepository
    store = m.SqlAlchemyUserRoleStore(fake, owner_floor=_floor, audit_timeout_s=0.01)
    with pytest.raises(WriteAheadTimeout):
        await store.apply_roles(_UID, frozenset({"viewer"}), actor=_ACTOR, audit=hang)
    assert not rel.committed and 0 < m.WRITE_AHEAD_TIMEOUT_S <= 5
