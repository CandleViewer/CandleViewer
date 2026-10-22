"""Integration: `0047_system_events_recipient` on real Postgres 16 (#3085 S13a): the round trip on
an empty and a seeded database, the FK's `ON DELETE SET NULL`, and the refused downgrade.
`testcontainers` in CI."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PREV, _TEMPLATE = "0043_order_submission", "system_events_recipient_head_template"
_FK, _INDEX = "system_events_recipient_user_id_fkey", "ix_se_recipient"
_COLUMNS_SQL = (
    "SELECT attname, format_type(atttypid, atttypmod), attnotnull FROM pg_attribute "
    "WHERE attrelid = 'system_events'::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
)
_CONSTRAINTS_SQL = (
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = 'system_events'::regclass ORDER BY conname"
)
_INDEXES_SQL = (
    "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'system_events' ORDER BY 1"
)
_ROWS = "SELECT id, component, kind, message FROM system_events ORDER BY id"
_VERSION = "SELECT version_num FROM alembic_version"
_USER = (
    "INSERT INTO users (id, email, username, password_hash, status) "
    "VALUES (%s, %s, %s, '$argon2id$fixture', 'active')"
)
_EVENT = (
    "INSERT INTO system_events (component, kind, message, recipient_user_id) "
    "VALUES ('auth', 'view_as_started', 'a notice', %s) RETURNING id"
)
#: The one active owner (the owner floor checks every `users` write) and the user a row addresses.
_OWNER, _TARGET = uuid.UUID(int=0xA1), uuid.UUID(int=0xB2)

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
    """A database of the test's own at head; seeded with the two users and an unaddressed row."""
    dsn = _create(pg_dsn, f"recipient_{uuid.uuid4().hex[:12]}", _TEMPLATE)
    if seeded:
        with _conn(dsn) as c:
            for uid in (_OWNER, _TARGET):
                name = f"r{uid.hex[-12:]}"
                c.execute(_USER, (uid, f"{name}@x.invalid", name))
            c.execute(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT %s, id FROM roles WHERE name::text = 'owner'",
                (_OWNER,),
            )
            c.execute(_EVENT, (None,))
    return dsn


def _catalog(c: Conn) -> tuple[list[Any], list[Any], list[Any]]:
    queries = (_COLUMNS_SQL, _CONSTRAINTS_SQL, _INDEXES_SQL)
    columns, constraints, indexes = (c.execute(query).fetchall() for query in queries)
    return columns, constraints, indexes


@pytest.mark.parametrize("seed", [False, True], ids=["empty", "seeded"])
def test_round_trip_removes_only_what_the_revision_added(pg_dsn: str, seed: bool) -> None:
    """C-5.2, C-5.5: upgrade, downgrade and upgrade again each succeed; the downgrade drops the
    column, its FK and the partial index and nothing else (every other column, constraint, index
    and row is as it was); the second upgrade restores the head, the index with its predicate."""
    dsn = _fresh(pg_dsn, seeded=seed)
    with _conn(dsn) as c:
        head, rows = _catalog(c), c.execute(_ROWS).fetchall()
    assert head[0][-1] == ("recipient_user_id", "uuid", False)  # nullable, appended
    assert _FK in {name for name, _ in head[1]}
    (index,) = (d for name, d in head[2] if name == _INDEX)
    assert index.endswith(
        "USING btree (recipient_user_id, event_ts DESC) WHERE (recipient_user_id IS NOT NULL)"
    )
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    with _conn(dsn) as c:
        columns, constraints, indexes = _catalog(c)
        kept = c.execute(_ROWS).fetchall()
    assert columns == head[0][:-1]
    assert constraints == [k for k in head[1] if k[0] != _FK]
    assert indexes == [i for i in head[2] if i[0] != _INDEX]
    assert kept == rows and len(kept) == (1 if seed else 0)
    assert _alembic(dsn, "upgrade", "head").returncode == 0
    with _conn(dsn) as c:
        assert _catalog(c) == head and c.execute(_ROWS).fetchall() == rows


def test_a_hard_deleted_users_rows_lose_their_address_and_stay(pg_dsn: str) -> None:
    """`ON DELETE SET NULL`, as `resolved_by`: a hard delete, which no path issues (a purge
    anonymises the user in place), nulls the address; the row stays, the Owner's alone."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        row = c.execute(_EVENT, (_TARGET,)).fetchone()
        assert row is not None
        c.execute("DELETE FROM users WHERE id = %s", (_TARGET,))
        got = c.execute(
            "SELECT recipient_user_id FROM system_events WHERE id = %s", (row[0],)
        ).fetchone()
    assert got == (None,)


def test_the_downgrade_refuses_while_a_row_is_addressed(pg_dsn: str) -> None:
    """Dropping the column would hand a user's notice to the Owner alone, so the downgrade
    refuses while any row is addressed, and changes nothing."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        c.execute(_EVENT, (_TARGET,))
        before = c.execute(_VERSION).fetchone(), _catalog(c), c.execute(_ROWS).fetchall()
    refused = _alembic(dsn, "downgrade", _PREV)
    assert refused.returncode != 0
    assert "0047_system_events_recipient downgrade refused" in refused.stderr
    with _conn(dsn) as c:
        assert (c.execute(_VERSION).fetchone(), _catalog(c), c.execute(_ROWS).fetchall()) == before
