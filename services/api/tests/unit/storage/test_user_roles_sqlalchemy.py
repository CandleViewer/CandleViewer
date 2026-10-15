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

from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.repositories import user_roles_sqlalchemy as m

_UID = uuid.uuid4()


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Rel:
    """Fake UoW keyed by statement; records the statements run and the commit."""

    def __init__(self, exists: bool = True, owners: int = 1, commit_error: str = "") -> None:
        roles = [SimpleNamespace(_mapping={"roles": ["owner"]})] if exists else []
        self.rows: dict[Any, list[Any]] = {
            m._LOCK_USER: [(1,)] if exists else [],
            m._LOCK_OWNERS: [(uuid.uuid4(),)] * owners,
            m._ROLES: roles,
            m._COUNT_OWNERS: [(owners,)],
        }
        self.commit_error, self.ran, self.committed = commit_error, list[Any](), False

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            self.ran.append((stmt, params))
            rows = self.rows.get(stmt, [])
            return SimpleNamespace(
                first=lambda: rows[0] if rows else None, all=lambda: rows, scalar_one=lambda: 2
            )

        async def commit() -> None:
            if self.commit_error:
                raise IntegrityError("COMMIT", None, _PgError(self.commit_error))
            self.committed = True

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)

    def writes(self) -> list[Any]:
        return [s for s, _ in self.ran if s in (m._DROP, m._GRANT)]


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


def _store(rel: _Rel) -> m.SqlAlchemyUserRoleStore:
    return m.SqlAlchemyUserRoleStore(rel, owner_floor=_floor)  # type: ignore[arg-type]  # fake


async def test_reads_return_effective_roles_none_for_unknown_and_owner_count() -> None:
    assert await _store(_Rel()).get_roles(_UID) == frozenset({"owner"})
    assert await _store(_Rel(exists=False)).get_roles(_UID) is None
    assert await _store(_Rel()).count_active_owners() == 2


async def test_apply_roles_unknown_user_returns_false_without_writes() -> None:
    rel = _Rel(exists=False)
    assert await _store(rel).apply_roles(_UID, frozenset({"viewer"})) is False
    assert rel.writes() == [] and not rel.committed


async def test_apply_roles_last_owner_refused_under_lock_before_any_write() -> None:
    rel = _Rel(owners=1)
    with pytest.raises(OwnerFloorError):
        await _store(rel).apply_roles(_UID, frozenset({"viewer"}))
    assert [s for s, _ in rel.ran] == [m._LOCK_USER, m._LOCK_OWNERS, m._ROLES]
    assert rel.writes() == [] and not rel.committed


async def test_apply_roles_replaces_the_set_in_one_locked_transaction() -> None:
    rel = _Rel(owners=2)
    assert await _store(rel).apply_roles(_UID, frozenset({"viewer", "manager"})) is True
    order = [m._LOCK_USER, m._LOCK_OWNERS, m._ROLES, m._DROP, m._GRANT]
    assert [s for s, _ in rel.ran] == order and rel.committed
    assert rel.ran[-1][1] == {"id": str(_UID), "roles": ["manager", "viewer"]}


@pytest.mark.parametrize(
    ("sqlstate", "raised"), [("23514", OwnerFloorError), ("23505", IntegrityError)]
)
async def test_apply_roles_commit_error_maps_only_the_floor_trigger(
    sqlstate: str, raised: type[Exception]
) -> None:
    with pytest.raises(raised):
        await _store(_Rel(owners=2, commit_error=sqlstate)).apply_roles(_UID, frozenset({"viewer"}))
