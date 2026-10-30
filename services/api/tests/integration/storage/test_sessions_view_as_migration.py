"""Integration: `0042_sessions_view_as` on real Postgres 16 (#3085 S2a): the round trip on an empty
and a seeded database, each CHECK's refusal, the FK, the refused downgrade, and a stored context
read back by `find_by_id`. `testcontainers` in CI."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import VIEW_AS_TTL, ViewAsState
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PREV, _TEMPLATE = "0041_account_env_write_once", "sessions_view_as_head_template"
_SHAPE, _REASON = "sessions_view_as_shape", "sessions_view_as_end_reason"
_FK = "sessions_view_as_target_user_id_fkey"
_INDEXES = ("ix_sessions_view_as_due", "ix_sessions_view_as_target", "ix_sessions_view_as_context")
_COLUMNS_SQL = (
    "SELECT attname, format_type(atttypid, atttypmod), attnotnull FROM pg_attribute "
    "WHERE attrelid = 'sessions'::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
)
_CONSTRAINTS_SQL = (
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = 'sessions'::regclass ORDER BY conname"
)
_INDEXES_SQL = "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'sessions' ORDER BY 1"
_ROWS = "SELECT id, user_id, refresh_token_hash::text, revoked_at FROM sessions ORDER BY id"
_VERSION = "SELECT version_num FROM alembic_version"
_USER = (
    "INSERT INTO users (id, email, username, password_hash, status) "
    "VALUES (%s, %s, %s, '$argon2id$fixture', 'active')"
)
_SESSION_ROW = (
    "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at) "
    "VALUES (%s, %s, %s, now() + interval '12 hours')"
)

#: The viewer (the one active owner: the owner floor checks every `users` write), their target,
#: and the viewer's session, which holds the context. Fixed ids: each database is a test's own.
_OWNER, _MANAGER, _SESSION = uuid.UUID(int=0xA1), uuid.UUID(int=0xB2), uuid.UUID(int=0xC3)
_T0 = datetime(2026, 10, 20, 12, tzinfo=UTC)
_EXPIRY, _END, _US = _T0 + VIEW_AS_TTL, _T0 + timedelta(minutes=10), timedelta(microseconds=1)
#: A live context, the eight columns in their `ADD COLUMN` order.
_LIVE: dict[str, Any] = {
    "view_as_context_id": uuid.UUID(int=1),
    "view_as_target_user_id": _MANAGER,
    "view_as_started_at": _T0,
    "view_as_expires_at": _EXPIRY,
    "view_as_ended_at": None,
    "view_as_end_recorded_at": None,
    "view_as_cleared_at": None,
    "view_as_end_reason": None,
}
_TZ = "timestamp with time zone"
_TYPES = list(zip(_LIVE, ("uuid", "uuid", _TZ, _TZ, _TZ, _TZ, _TZ, "text"), strict=True))
#: The columns later revisions add to `sessions` (`0056_sessions_lock_state`, #4743): the
#: downgrade to `_PREV` drops them too, so the catalogs are compared by column name, never by
#: position.
_LATER_COLUMNS = frozenset({"locked_at", "unlocked_at"})
_WRITE = sql.SQL("UPDATE sessions SET ({}) = ({}) WHERE id = %(id)s").format(
    sql.SQL(", ").join(map(sql.Identifier, _LIVE)), sql.SQL(", ").join(map(sql.Placeholder, _LIVE))
)
_ENDED: dict[str, Any] = {"view_as_ended_at": _END, "view_as_end_reason": "ended"}
_CLEARED: dict[str, Any] = {**_ENDED, "view_as_end_recorded_at": _END, "view_as_cleared_at": _END}
#: case id -> (the columns changed from `_LIVE`, the CHECK that refuses the row). One row each;
#: `tests/unit/auth/test_view_as_state.py` has `ViewAsState` refuse the same rows.
_REFUSED: dict[str, tuple[dict[str, Any], str]] = {
    "context-without-target": ({"view_as_target_user_id": None}, _SHAPE),
    "target-without-context": ({"view_as_context_id": None}, _SHAPE),
    "expiry-not-start-plus-30m": ({"view_as_expires_at": _EXPIRY + _US}, _SHAPE),
    "own-user": ({"view_as_target_user_id": _OWNER}, _SHAPE),
    "end-without-reason": ({"view_as_ended_at": _END}, _SHAPE),
    "reason-without-end": ({"view_as_end_reason": "ended"}, _SHAPE),
    "recorded-without-end": ({"view_as_end_recorded_at": _END}, _SHAPE),
    "cleared-without-end": ({"view_as_cleared_at": _END}, _SHAPE),
    "end-after-expiry": ({**_ENDED, "view_as_ended_at": _EXPIRY + _US}, _SHAPE),
    "expired-before-expiry": ({**_ENDED, "view_as_end_reason": "expired"}, _SHAPE),
    "ended-at-expiry": ({**_ENDED, "view_as_ended_at": _EXPIRY}, _SHAPE),
    "unknown-reason": ({**_ENDED, "view_as_end_reason": "logout"}, _REASON),
}
#: case id -> the columns changed from `_LIVE`: a row `ViewAsState` admits, the CHECKs too, or
#: (`none`) a row holding no context.
_ADMITTED: dict[str, dict[str, Any]] = {
    "none": dict.fromkeys(_LIVE),
    "live": {},
    "expired-at-expiry": {"view_as_ended_at": _EXPIRY, "view_as_end_reason": "expired"},
    "pending-end-cleared": {**_ENDED, "view_as_cleared_at": _END},
    "times-in-no-order": {**_CLEARED, "view_as_end_recorded_at": _T0, "view_as_cleared_at": _T0},
    "every-column": _CLEARED,
}

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#3085)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _create(dsn: str, name: str, template: str) -> str:
    """`CREATE DATABASE name TEMPLATE template` on the server of `dsn`; the new database's DSN."""
    server = dsn.rsplit("/", 1)[0]
    with _conn(f"{server}/postgres") as c:
        stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
        c.execute(stmt.format(sql.Identifier(name), sql.Identifier(template)))
    return f"{server}/{name}"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """A server whose `_TEMPLATE` database is at head and untouched, for each test to clone."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        _create(dsn, _TEMPLATE, dsn.rsplit("/", 1)[1])
        yield dsn


def _fresh(pg_dsn: str, *, seeded: bool = True) -> str:
    """A database of the test's own at head, seeded unless asked otherwise."""
    dsn = _create(pg_dsn, f"view_as_{uuid.uuid4().hex[:12]}", _TEMPLATE)
    if seeded:
        with _conn(dsn) as c:
            _seed(c)
    return dsn


def _seed(c: Conn) -> None:
    """The owner and their target, one live session each, and no context anywhere."""
    for uid, sid in ((_OWNER, _SESSION), (_MANAGER, uuid.UUID(int=0xD4))):
        name = f"v{uid.hex[-12:]}"
        c.execute(_USER, (uid, f"{name}@x.invalid", name))
        c.execute(_SESSION_ROW, (sid, uid, sid.hex * 2))
    c.execute(
        "INSERT INTO user_roles (user_id, role_id) "
        "SELECT %s, id FROM roles WHERE name::text = 'owner'",
        (_OWNER,),
    )


@pytest.fixture(scope="module")
def seeded(pg_dsn: str) -> str:
    """One seeded database for the row tests: each write sets all eight columns of one row."""
    return _fresh(pg_dsn)


def _write(c: Conn, changes: dict[str, Any]) -> None:
    """Put `_LIVE` with `changes` on the owner's session row: every column, so no write leaks."""
    c.execute(_WRITE, {**_LIVE, **changes, "id": _SESSION})


def _catalog(c: Conn) -> tuple[list[Any], list[Any], list[Any]]:
    queries = (_COLUMNS_SQL, _CONSTRAINTS_SQL, _INDEXES_SQL)
    columns, constraints, indexes = (c.execute(query).fetchall() for query in queries)
    return columns, constraints, indexes


async def _find(dsn: str) -> SessionRecord:
    """The owner's session read the way the app reads it (`find_by_id`, asyncpg)."""
    relational = SqlAlchemyRelationalRepository(
        dsn.replace("postgresql+psycopg", "postgresql+asyncpg")
    )
    repo = SqlAlchemySessionRepository(relational, lambda **f: SessionRecord.model_validate(f))
    try:
        record = await repo.find_by_id(str(_SESSION))
    finally:
        await relational.dispose()
    assert isinstance(record, SessionRecord)
    return record


@pytest.mark.parametrize("seed", [False, True], ids=["empty", "seeded"])
def test_round_trip_removes_only_what_the_revision_added(pg_dsn: str, seed: bool) -> None:
    """C-5.2, C-5.5: upgrade, downgrade and upgrade again each succeed; the downgrade drops the
    eight columns, the two CHECKs, the FK and the three partial indexes and nothing else (every
    other column, constraint, index and row is as it was, but the columns later revisions add,
    which go with them); the second upgrade restores the head, the indexes with their predicates
    (the sweeper's due read, the contexts naming a target and the rows of one context)."""
    dsn = _fresh(pg_dsn, seeded=seed)
    with _conn(dsn) as c:
        head, rows = _catalog(c), c.execute(_ROWS).fetchall()
    view_as = {name for name, _ in _TYPES}
    assert [col for col in head[0] if col[0] in view_as] == [
        (name, kind, False) for name, kind in _TYPES
    ]  # nullable, in the revision's order
    added = {_SHAPE, _REASON, _FK}
    assert added <= {name for name, _ in head[1]} and set(_INDEXES) <= {i for i, _ in head[2]}
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    with _conn(dsn) as c:
        columns, constraints, indexes = _catalog(c)
        kept = c.execute(_ROWS).fetchall()
    assert columns == [col for col in head[0] if col[0] not in view_as | _LATER_COLUMNS]
    assert constraints == [k for k in head[1] if k[0] not in added]
    assert indexes == [i for i in head[2] if i[0] not in _INDEXES]
    assert kept == rows and len(kept) == (2 if seed else 0)
    assert _alembic(dsn, "upgrade", "head").returncode == 0
    with _conn(dsn) as c:
        assert _catalog(c) == head and c.execute(_ROWS).fetchall() == rows
    due, by_target, by_context = (re.sub(r"[()]", "", dict(head[2])[name]) for name in _INDEXES)
    assert due.endswith(
        "btree view_as_expires_at WHERE view_as_context_id IS NOT NULL "
        "AND view_as_end_recorded_at IS NULL"
    )
    assert by_target.endswith(
        "btree view_as_target_user_id WHERE view_as_context_id IS NOT NULL "
        "AND view_as_ended_at IS NULL"
    )
    assert by_context.endswith("btree view_as_context_id WHERE view_as_context_id IS NOT NULL")


@pytest.mark.parametrize(("changes", "check"), list(_REFUSED.values()), ids=list(_REFUSED))
def test_each_check_refuses_its_case_under_its_own_name(
    seeded: str, changes: dict[str, Any], check: str
) -> None:
    with _conn(seeded) as c, pytest.raises(pgerr.CheckViolation) as refused:
        _write(c, changes)
    assert refused.value.diag.constraint_name == check


@pytest.mark.parametrize("changes", list(_ADMITTED.values()), ids=list(_ADMITTED))
async def test_a_stored_context_reads_back_through_find_by_id_as_the_same_state(
    seeded: str, changes: dict[str, Any]
) -> None:
    columns = {**_LIVE, **changes}
    with _conn(seeded) as c:
        _write(c, changes)
    held = {name.removeprefix("view_as_"): value for name, value in columns.items()}
    expected = None if columns["view_as_context_id"] is None else ViewAsState(**held)
    assert (await _find(seeded)).view_as == expected


def test_the_fk_refuses_to_delete_a_user_a_context_names(pg_dsn: str) -> None:
    """`ON DELETE RESTRICT`, a cleared and recorded context included: the refusal names the FK
    (SQLSTATE 23503) and the user stays. No `users` row is ever deleted (the purge anonymises)."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        _write(c, _CLEARED)
        definition = c.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s", (_FK,)
        ).fetchone()
        with pytest.raises(pgerr.ForeignKeyViolation) as refused:
            c.execute("DELETE FROM users WHERE id = %s", (_MANAGER,))
        kept = c.execute("SELECT count(*) FROM users WHERE id = %s", (_MANAGER,)).fetchone()
    restrict = "FOREIGN KEY (view_as_target_user_id) REFERENCES users(id) ON DELETE RESTRICT"
    assert definition == (restrict,) and refused.value.diag.constraint_name == _FK
    assert kept == (1,)


@pytest.mark.parametrize(
    "changes",
    [{}, {**_ENDED, "view_as_cleared_at": _END}, _CLEARED],
    ids=["live", "pending", "done"],
)
def test_the_downgrade_refuses_while_a_row_names_a_context(
    pg_dsn: str, changes: dict[str, Any]
) -> None:
    """Dropping the columns would end a live context with no record or lose an end its record
    still owes, so the downgrade refuses while any row names a context, and changes nothing."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        _write(c, changes)
        before = c.execute(_VERSION).fetchone(), _catalog(c)
    refused = _alembic(dsn, "downgrade", _PREV)
    assert refused.returncode != 0 and "0042_sessions_view_as downgrade refused" in refused.stderr
    with _conn(dsn) as c:
        assert (c.execute(_VERSION).fetchone(), _catalog(c)) == before
