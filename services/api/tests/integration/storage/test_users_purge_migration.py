"""Integration: `0035_users_purge` on real Postgres 16 (E42-T10 #2650, S2). The round trip on an
empty and a seeded database removes only the two new columns and their CHECK and keeps every row;
the CHECK refuses an anonymisation mark with no schedule; the downgrade refuses while a purge is
pending. `testcontainers` in CI; not run on the laptop (no docker socket)."""

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
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PREV = "0034_order_vocabulary"
_TEMPLATE = "users_purge_head_template"
_NEW = ("purge_after", "anonymised_at")
_SHAPE = (
    "SELECT attname, format_type(atttypid, atttypmod), attnotnull FROM pg_attribute "
    "WHERE attrelid = 'users'::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum"
)
_CHECKS = (
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = 'users'::regclass ORDER BY conname"
)
_INDEXES = "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'users' ORDER BY 1"
_ROWS = "SELECT id, email::text, username::text, status::text FROM users ORDER BY id"
_VERSION = "SELECT version_num FROM alembic_version"
_USER = (
    "INSERT INTO users (id, email, username, password_hash, status) "
    "VALUES (%s, %s, %s, '$argon2id$fixture', %s)"
)

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2650)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _clone(dsn: str, template: str) -> str:
    name = f"purge_{uuid.uuid4().hex[:12]}" if template == _TEMPLATE else _TEMPLATE
    with _conn(f"{dsn.rsplit('/', 1)[0]}/postgres") as c:
        stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
        c.execute(stmt.format(sql.Identifier(name), sql.Identifier(template)))
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Head, plus an untouched copy of it that each test clones."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        _clone(dsn, dsn.rsplit("/", 1)[1])
        yield dsn


def _seed(c: Conn) -> tuple[uuid.UUID, uuid.UUID]:
    """An active owner (the owner-floor trigger checks every `users` update), a disabled manager,
    and a disabled user anonymised already, the CHECK's other arm. Returns the last two."""
    owner, manager, gone = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for uid, status in ((owner, "active"), (manager, "disabled"), (gone, "disabled")):
        name = f"p{uid.hex[:12]}"
        c.execute(_USER, (uid, f"{name}@x.invalid", name, status))
    c.execute(
        "INSERT INTO user_roles (user_id, role_id) "
        "SELECT %s, id FROM roles WHERE name::text = 'owner'",
        (owner,),
    )
    c.execute(
        "UPDATE users SET purge_after = now() - interval '1 day', anonymised_at = now() "
        "WHERE id = %s",
        (gone,),
    )
    return manager, gone


def _catalog(c: Conn) -> tuple[list[Any], list[Any], list[Any]]:
    return (
        c.execute(_SHAPE).fetchall(),
        c.execute(_CHECKS).fetchall(),
        c.execute(_INDEXES).fetchall(),
    )


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_round_trip_removes_only_the_two_new_columns(pg_dsn: str, seeded: bool) -> None:
    """C-5.2, C-5.5: upgrade, downgrade and upgrade again each succeed; the downgrade drops the two
    columns and their CHECK and nothing else (every other column, constraint, index and row is as
    it was), and the second upgrade restores the head exactly."""
    dsn = _clone(pg_dsn, _TEMPLATE)
    with _conn(dsn) as c:
        if seeded:
            _seed(c)
        head, rows = _catalog(c), c.execute(_ROWS).fetchall()
    added = [("purge_after", "timestamp with time zone", False)]
    added += [("anonymised_at", "timestamp with time zone", False)]
    assert head[0][-2:] == added  # nullable, tz-aware, appended (no rewrite)
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    with _conn(dsn) as c:
        shape, checks, indexes = _catalog(c)
        kept = c.execute(_ROWS).fetchall()
    assert shape == [column for column in head[0] if column[0] not in _NEW]
    assert checks == [check for check in head[1] if check[0] != "users_purge_shape"]
    assert indexes == head[2] and kept == rows and len(kept) == (3 if seeded else 0)
    assert _alembic(dsn, "upgrade", "head").returncode == 0
    with _conn(dsn) as c:
        assert _catalog(c) == head and c.execute(_ROWS).fetchall() == rows


def test_the_check_refuses_an_anonymisation_mark_with_no_schedule(pg_dsn: str) -> None:
    """Only a scheduled purge is ever marked done: `anonymised_at` needs `purge_after`."""
    dsn = _clone(pg_dsn, _TEMPLATE)
    with _conn(dsn) as c:
        manager, _ = _seed(c)
        with pytest.raises(pgerr.CheckViolation) as refused:
            c.execute("UPDATE users SET anonymised_at = now() WHERE id = %s", (manager,))
    assert refused.value.diag.constraint_name == "users_purge_shape"


def test_the_downgrade_refuses_while_a_purge_is_pending(pg_dsn: str) -> None:
    """Dropping `purge_after` would cancel a scheduled purge silently, so the downgrade refuses
    and changes nothing; an anonymised user alone does not block it (the round trip above)."""
    dsn = _clone(pg_dsn, _TEMPLATE)
    with _conn(dsn) as c:
        manager, _ = _seed(c)
        c.execute(
            "UPDATE users SET purge_after = now() + interval '90 days' WHERE id = %s", (manager,)
        )
        before = c.execute(_VERSION).fetchone(), _catalog(c)
    refused = _alembic(dsn, "downgrade", _PREV)
    assert refused.returncode != 0 and "0035_users_purge downgrade refused" in refused.stderr
    with _conn(dsn) as c:
        assert (c.execute(_VERSION).fetchone(), _catalog(c)) == before
