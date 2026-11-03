"""Integration (#5478): `SqlAlchemyUserAdminStore.list_users` on real Postgres 16.

What the unit tests pin as statement text only: users created in one transaction share
`created_at`, and pages of any size partition them in `id` order with no repeat; `q` matches the
username or the email whatever the case, `%` and `_` taken literally; a role grant that has expired
does not match `role`; a soft-deleted row is never listed, and a purged one is, `disabled`, under
its surrogate names; a user created while the list is read lands on a later page. Each test lists
only the users whose names hold its own tag. Needs Docker (testcontainers); not run locally. CI
`integration` runs it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_list import UserListFilter, like_pattern
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserAdminStore

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', CAST(:status AS user_status))"
)
_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id) SELECT CAST(:id AS uuid), id FROM roles "
    "WHERE name::text = :role"
)
#: A grant that expired an hour ago (`user_roles_expiry`: it must end after it began).
_EXPIRED_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id, granted_at, expires_at) SELECT CAST(:id AS uuid), "
    "id, now() - interval '2 hours', now() - interval '1 hour' FROM roles WHERE name::text = :role"
)
_SOFT_DELETE = sa.text("UPDATE users SET deleted_at = now() WHERE id = CAST(:id AS uuid)")
#: What the purge reaper leaves (E42-T10): a disabled row, surrogate names, the date stamped.
_PURGED = sa.text(
    "UPDATE users SET status = 'disabled', username = :name, email = :email, "
    "display_name = NULL, purge_after = now() - interval '1 day', anonymised_at = now() "
    "WHERE id = CAST(:id AS uuid)"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


@pytest.fixture
async def db(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyUserAdminStore, AsyncEngine]]:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    try:
        yield SqlAlchemyUserAdminStore(rel, owner_floor=_no_floor), engine
    finally:
        await rel.dispose()
        await engine.dispose()


def _no_floor(_current: frozenset[str], _new: frozenset[str], _owners: int) -> None:
    return None


def _tag() -> str:
    return f"l{uuid.uuid4().hex[:8]}"


async def _users(
    engine: AsyncEngine, *names: str, role: str = "viewer", status: str = "active"
) -> list[uuid.UUID]:
    """Users named `names`, in one transaction, so they share `created_at` (`now()`); an active
    owner first, as the owner-floor trigger refuses any role row while none is active."""
    ids = [uuid.uuid4() for _ in names]
    async with engine.begin() as conn:
        owner = uuid.uuid4()
        await conn.execute(_USER, {"id": str(owner), "email": f"{owner.hex}@x.invalid",
                                   "name": f"o{owner.hex[:12]}", "status": "active"})  # fmt: skip
        await conn.execute(_ROLE, {"id": str(owner), "role": "owner"})
        for uid, name in zip(ids, names, strict=True):
            params = {"id": str(uid), "email": f"{name}@x.invalid", "name": name, "status": status}
            await conn.execute(_USER, params)
            await conn.execute(_ROLE, {"id": str(uid), "role": role})
    return ids


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


def _filter(
    after: tuple[datetime, uuid.UUID] | None = None, limit: int = 101, **fields: Any
) -> UserListFilter:
    base: dict[str, Any] = {"status": None, "role": None, "pattern": None}
    return UserListFilter(**(base | fields), after=after, limit=limit)


def _position(row: dict[str, Any]) -> tuple[datetime, uuid.UUID]:
    return datetime.fromisoformat(row["created_at"]), uuid.UUID(row["id"])


async def _pages(
    store: SqlAlchemyUserAdminStore, size: int, **fields: Any
) -> list[list[dict[str, Any]]]:
    """Every page of `size` rows, as the route reads them: `size + 1` rows, the next page after
    the last row shown. A page holds a row, so the walk ends within a turn per row and one more:
    a cursor that never moves fails here instead of reading for ever."""
    total = len(await store.list_users(_filter(limit=10_000, **fields)))
    pages: list[list[dict[str, Any]]] = []
    after = None
    for _ in range(total + 1):
        rows = await store.list_users(_filter(after, size + 1, **fields))
        pages.append(rows[:size])
        if len(rows) <= size:
            return pages
        after = _position(rows[size - 1])
    raise AssertionError("the cursor never reached the last page")


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["id"] for row in rows]


async def test_list_users_pg_tied_created_at_partitions_every_page(
    db: tuple[SqlAlchemyUserAdminStore, AsyncEngine],
) -> None:
    store, engine = db
    tag = _tag()
    ids = await _users(engine, *(f"{tag}-{n}" for n in range(5)))
    full = await store.list_users(_filter(pattern=like_pattern(tag)))
    assert _ids(full) == [str(uid) for uid in sorted(ids)]  # a tie on the time, broken by the id
    assert len({row["created_at"] for row in full}) == 1
    for size in (1, 2, 3):
        pages = await _pages(store, size, pattern=like_pattern(tag))
        assert [len(page) for page in pages[:-1]] == [size] * (len(pages) - 1)
        assert [uid for page in pages for uid in _ids(page)] == _ids(full)  # each once, in order


async def test_list_users_pg_q_ignores_case_and_takes_percent_underscore_backslash_literally(
    db: tuple[SqlAlchemyUserAdminStore, AsyncEngine],
) -> None:
    store, engine = db
    tag = _tag()
    names = (
        f"{tag}ab_cd",
        f"{tag}abxcd",
        f"{tag}zz",
        f"{tag}a%b",
        f"{tag}axb",
        f"{tag}c\\d",
        f"{tag}cxd",
    )
    under, plain, other, percent, wild, slash, unslashed = await _users(engine, *names)
    await _exec(engine, sa.text(
        "UPDATE users SET email = :email WHERE id = CAST(:id AS uuid)"
    ), email=f"AB_CD.{tag}@x.invalid", id=str(other))  # fmt: skip
    found = await store.list_users(_filter(pattern=like_pattern("B_C")))
    assert set(_ids(found)) & {str(u) for u in (under, plain, other)} == {str(under), str(other)}
    found = await store.list_users(_filter(pattern=like_pattern("A%B")))
    assert set(_ids(found)) & {str(percent), str(wild)} == {str(percent)}
    found = await store.list_users(_filter(pattern=like_pattern("C\\D")))  # the backslash itself
    assert set(_ids(found)) & {str(slash), str(unslashed)} == {str(slash)}
    assert _ids(await store.list_users(_filter(pattern=like_pattern(tag.upper())))) == _ids(
        await store.list_users(_filter(pattern=like_pattern(tag)))
    )


async def test_list_users_pg_role_filter_ignores_an_expired_grant(
    db: tuple[SqlAlchemyUserAdminStore, AsyncEngine],
) -> None:
    store, engine = db
    tag = _tag()
    live, expired = await _users(engine, f"{tag}-live", f"{tag}-gone", role="viewer")
    await _exec(engine, _EXPIRED_ROLE, id=str(expired), role="manager")
    await _exec(engine, _ROLE, id=str(live), role="manager")
    found = await store.list_users(_filter(role="manager", pattern=like_pattern(tag)))
    assert _ids(found) == [str(live)] and found[0]["roles"] == ["manager", "viewer"]
    everyone = await store.list_users(_filter(pattern=like_pattern(tag)))
    assert {row["id"]: row["roles"] for row in everyone}[str(expired)] == ["viewer"]


async def test_list_users_pg_never_lists_a_soft_deleted_row_and_lists_a_purged_one_disabled(
    db: tuple[SqlAlchemyUserAdminStore, AsyncEngine],
) -> None:
    store, engine = db
    tag = _tag()
    deleted, purged, kept = await _users(engine, f"{tag}-del", f"{tag}-pur", f"{tag}-kept")
    await _exec(engine, _SOFT_DELETE, id=str(deleted))
    surrogate = f"{tag}-anon"
    await _exec(engine, _PURGED, id=str(purged), name=surrogate, email=f"{surrogate}@x.invalid")
    rows = {row["id"]: row for row in await store.list_users(_filter(pattern=like_pattern(tag)))}
    assert set(rows) == {str(purged), str(kept)}
    assert (rows[str(purged)]["status"], rows[str(purged)]["username"]) == ("disabled", surrogate)
    disabled = await store.list_users(_filter(status="disabled", pattern=like_pattern(tag)))
    assert _ids(disabled) == [str(purged)]


async def test_list_users_pg_a_user_created_mid_read_lands_on_a_later_page(
    db: tuple[SqlAlchemyUserAdminStore, AsyncEngine],
) -> None:
    store, engine = db
    tag = _tag()
    first = await _users(engine, *(f"{tag}-{n}" for n in range(3)))
    page = await store.list_users(_filter(pattern=like_pattern(tag), limit=3))
    (late,) = await _users(engine, f"{tag}-late")  # a later transaction: a later `created_at`
    rest = await store.list_users(_filter(_position(page[1]), pattern=like_pattern(tag)))
    seen = _ids(page[:2]) + _ids(rest)
    assert seen == [*(str(uid) for uid in sorted(first)), str(late)]
