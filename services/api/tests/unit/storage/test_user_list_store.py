"""#5478: `SqlAlchemyUserAdminStore.list_users` over a fake unit of work that answers
`_LIST_USERS` by identity (the `_Db` pattern of `test_user_admin_store.py`); Postgres runs the
statement in `tests/integration/admin/test_user_list_pg.py`.

`_LIST_USERS` is one literal, no text built from input (CI's registry Semgrep rule
`avoid-sqlalchemy-text`), so its parts are pinned here: `read_user`'s select list exactly, the
predicates, the order and the limit. A `q` reaches it only as a bound pattern whose LIKE
metacharacters are escaped (`like_pattern`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Final

import pytest

from candleviewer.storage.repositories import identity_sqlalchemy as identity
from candleviewer.storage.repositories import users_sqlalchemy as m
from candleviewer.storage.repositories.user_list import UserListFilter, like_pattern

_A, _B = uuid.UUID(int=0xA), uuid.UUID(int=0xB)
_T = datetime(2026, 10, 19, 12, 0, 0, 123456, tzinfo=UTC)


def _sql(stmt: Any) -> str:
    return " ".join(str(stmt.text).split())


def _select_list(stmt: Any) -> str:
    return _sql(stmt).split("SELECT ", 1)[1].split(" FROM users u ", 1)[0]


class _Db:
    """The unit of work: answers `_LIST_USERS`, and nothing else, with its first `limit` `rows`,
    and keeps what each read bound; `error` is what the read raises, as a driver would."""

    def __init__(self, *rows: dict[str, Any]) -> None:
        self.rows, self.bound = list(rows), list[dict[str, Any]]()
        self.error: Exception | None = None

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any]) -> Any:
            assert stmt is m._LIST_USERS, stmt
            self.bound.append(params)
            if self.error is not None:
                raise self.error
            found = [SimpleNamespace(_mapping=row) for row in self.rows[: params["limit"]]]
            return SimpleNamespace(all=lambda: found)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def _row(uid: uuid.UUID, **fields: Any) -> dict[str, Any]:
    """A row of `_LIST_USERS`' select list, as the driver answers it."""
    name = f"u{uid.hex[-4:]}"
    return {
        "id": str(uid), "username": name, "email": f"{name}@example.invalid", "display_name": None,
        "status": "active", "mfa_required": True, "last_login_at": None, "created_at": _T,
        "updated_at": _T, "roles": ["manager"], "mfa_enabled": 0, **fields,
    }  # fmt: skip


def _rel(db: _Db) -> Any:
    """The fake unit of work, in place of the store's relational repository."""
    return db


def _no_floor(_current: frozenset[str], _new: frozenset[str], _owners: int) -> None:
    return None


def _query(**fields: Any) -> UserListFilter:
    base: dict[str, Any] = {"status": None, "role": None, "pattern": None, "after": None}
    return UserListFilter(**(base | {"limit": 101} | fields))


async def _list(db: _Db, query: UserListFilter) -> list[dict[str, Any]]:
    return await m.SqlAlchemyUserAdminStore(_rel(db), owner_floor=_no_floor).list_users(query)


def test_list_users_statement_selects_exactly_the_user_read_models_columns() -> None:
    """The list answers what `getUser` answers: the select list is `_USER_SQL`'s, part for part,
    and never `password_hash` or any other column of `users`."""
    assert _select_list(m._LIST_USERS) == _select_list(identity._USER_SQL)
    assert "password" not in _sql(m._LIST_USERS) and "last_login_ip" not in _sql(m._LIST_USERS)


#: `_LIST_USERS` after `FROM users u`, whitespace normalised: each predicate with its `NULL` guard,
#: the connectors between them, the order and the limit. It changes only with the statement, as the
#: Postgres file does.
_WHERE: Final = (
    "WHERE u.deleted_at IS NULL"
    " AND (CAST(:status AS text) IS NULL OR u.status::text = CAST(:status AS text))"
    " AND (CAST(:role AS text) IS NULL OR EXISTS ( SELECT 1 FROM user_roles ur"
    " JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id"
    " AND r.name::text = CAST(:role AS text)"
    " AND (ur.expires_at IS NULL OR ur.expires_at > now())))"
    " AND (CAST(:pattern AS text) IS NULL"
    " OR u.username::text ILIKE CAST(:pattern AS text) ESCAPE '\\'"
    " OR u.email::text ILIKE CAST(:pattern AS text) ESCAPE '\\')"
    " AND (CAST(:after_at AS timestamptz) IS NULL"
    " OR (u.created_at, u.id) > (CAST(:after_at AS timestamptz), CAST(:after_id AS uuid)))"
    " ORDER BY u.created_at, u.id LIMIT :limit"
)


def test_list_users_statement_pins_its_predicates_order_and_limit() -> None:
    """The whole clause, so a flipped `NULL` guard or connector fails here and not only on
    Postgres; on a mismatch the message names the parts that went missing."""
    where = _sql(m._LIST_USERS).split(" FROM users u ", 1)[1]
    parts = (
        "WHERE u.deleted_at IS NULL AND ",
        "(CAST(:status AS text) IS NULL OR u.status::text = CAST(:status AS text))",
        "(CAST(:role AS text) IS NULL OR EXISTS (",
        "WHERE ur.user_id = u.id AND r.name::text = CAST(:role AS text) "
        "AND (ur.expires_at IS NULL OR ur.expires_at > now())))",
        "(CAST(:pattern AS text) IS NULL OR u.username::text ILIKE",
        "OR u.username::text ILIKE CAST(:pattern AS text) ESCAPE '\\' ",
        "OR u.email::text ILIKE CAST(:pattern AS text) ESCAPE '\\')",
        "(CAST(:after_at AS timestamptz) IS NULL OR (u.created_at, u.id) >",
        "OR (u.created_at, u.id) > (CAST(:after_at AS timestamptz), CAST(:after_id AS uuid)))",
        " ORDER BY u.created_at, u.id LIMIT :limit",
    )
    assert where == _WHERE, [part for part in parts if part not in where]
    assert set(m._LIST_USERS._bindparams) == {
        "status", "role", "pattern", "after_at", "after_id", "limit",
    }  # fmt: skip


async def test_list_users_binds_its_filter_and_maps_rows_as_the_user_read_model() -> None:
    db = _Db(_row(_A, roles=None, mfa_enabled=1), _row(_B, last_login_at=_T))
    after = (_T, _A)
    found = await _list(db, _query(status="active", role="viewer", pattern="%x%", after=after))
    assert db.bound == [{
        "status": "active", "role": "viewer", "pattern": "%x%", "after_at": _T,
        "after_id": str(_A), "limit": 101,
    }]  # fmt: skip
    assert found == [identity.user_of(_row(_A, roles=None, mfa_enabled=1)), identity.user_of(
        _row(_B, last_login_at=_T))]  # fmt: skip
    first, second = found
    assert (first["roles"], first["mfa_enabled"], first["created_at"]) == ([], True, _T.isoformat())
    assert second["last_login_at"] == _T.isoformat() and second["mfa_enabled"] is False


async def test_list_users_first_page_binds_no_position() -> None:
    db = _Db()
    assert await _list(db, _query()) == []
    assert db.bound == [{
        "status": None, "role": None, "pattern": None, "after_at": None, "after_id": None,
        "limit": 101,
    }]  # fmt: skip


@pytest.mark.parametrize("limit", [1, 2, 3, 501])
async def test_list_users_reads_limit_rows_as_asked(limit: int) -> None:
    """The store reads what it is given: the route asks the page size plus one."""
    db = _Db(*(_row(uuid.UUID(int=n)) for n in range(1, 5)))
    found = await _list(db, _query(limit=limit))
    assert db.bound[0]["limit"] == limit and len(found) == min(limit, 4)


async def test_list_users_lets_a_driver_error_propagate() -> None:
    db = _Db(_row(_A))
    db.error = ConnectionRefusedError(111, "database down")
    with pytest.raises(ConnectionRefusedError):
        await _list(db, _query())


def test_like_pattern_escapes_backslash_percent_and_underscore() -> None:
    assert like_pattern("") == "%%"
    assert like_pattern("ab") == "%ab%"
    assert like_pattern("a%b_c\\d") == "%a\\%b\\_c\\\\d%"
    assert like_pattern("\\%") == "%\\\\\\%%"  # the backslash first, so no escape is escaped twice
