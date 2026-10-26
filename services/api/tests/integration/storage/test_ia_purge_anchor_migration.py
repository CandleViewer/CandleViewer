"""Integration: `0052_ia_purge_anchor` (E16-T06, #490) on real Postgres 16.

A purge anchor carries its bound and an order anchor none (`ia_bound`), `ia_operation` admits
`purgeRecordedData`, the bound is write-once whatever the replication role, the store's find and
create read and write it, the round trip holds on an empty and a seeded database (C-5.5), and the
downgrade refuses while a purge anchor exists. `testcontainers` in CI; the offline render is
`tests/unit/migrations/test_0052_ia_purge_anchor.py`.
"""

from __future__ import annotations

import asyncio
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

from candleviewer.storage.repositories.purge_anchors import NewPurgeAnchor
from candleviewer.storage.repositories.purge_anchors_sqlalchemy import SqlAlchemyPurgeAnchorStore
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REV, _PREV = "0052_ia_purge_anchor", "0051_replay_symbols_streams"
_TEMPLATE = "ia_purge_anchor_head"
_USER = uuid.UUID(int=0xA1)
_REF, _SHA = "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59", "ab" * 32
_BEFORE = 1_792_548_000_000_000
_INSERT = (
    "INSERT INTO idempotency_anchors (id, created_by, operation, client_ref, request_sha256, "
    "before_us) VALUES (%s, %s, %s, %s, %s, %s)"
)
_CATALOG = (
    "SELECT attname, format_type(atttypid, atttypmod), attnotnull FROM pg_attribute "
    "WHERE attrelid = 'idempotency_anchors'::regclass AND attnum > 0 AND NOT attisdropped "
    "ORDER BY attnum",
    "SELECT conname, pg_get_constraintdef(oid), convalidated FROM pg_constraint "
    "WHERE conrelid = 'idempotency_anchors'::regclass ORDER BY conname",
    "SELECT pg_get_functiondef('ia_write_once'::regproc)",
)

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#490)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """A server whose `_TEMPLATE` database is at head and untouched, for each test to clone."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        server = dsn.rsplit("/", 1)[0]
        with _conn(f"{server}/postgres") as c:
            stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
            c.execute(stmt.format(sql.Identifier(_TEMPLATE), sql.Identifier(dsn.rsplit("/")[-1])))
        yield dsn


@pytest.fixture
def db(pg_dsn: str) -> str:
    name = f"t_{uuid.uuid4().hex[:16]}"
    server = pg_dsn.rsplit("/", 1)[0]
    with _conn(f"{server}/postgres") as c:
        stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
        c.execute(stmt.format(sql.Identifier(name), sql.Identifier(_TEMPLATE)))
    return f"{server}/{name}"


def _user(c: Conn) -> None:
    c.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, 'u@example.test', 'user_one', '$argon2id$x', 'active')",
        (_USER,),
    )


def _catalog(c: Conn) -> list[list[tuple[Any, ...]]]:
    return [list(c.execute(query).fetchall()) for query in _CATALOG]


def _refused(c: Conn, params: tuple[object, ...], constraint: str) -> None:
    with pytest.raises(pgerr.CheckViolation) as exc, c.transaction():
        c.execute(_INSERT, params)
    assert exc.value.diag.constraint_name == constraint


def test_a_purge_anchor_needs_its_bound_and_an_order_anchor_takes_none(db: str) -> None:
    with _conn(db) as c:
        _user(c)
        _refused(c, (uuid.uuid4(), _USER, "purgeRecordedData", _REF, _SHA, None), "ia_bound")
        _refused(c, (uuid.uuid4(), _USER, "purgeRecordedData", _REF, _SHA, -1), "ia_bound")
        _refused(c, (uuid.uuid4(), _USER, "closePosition", _REF, _SHA, _BEFORE), "ia_bound")
        _refused(c, (uuid.uuid4(), _USER, "cancelOrder", _REF, _SHA, None), "ia_operation")
        c.execute(_INSERT, (uuid.uuid4(), _USER, "purgeRecordedData", _REF, _SHA, _BEFORE))
        c.execute(_INSERT, (uuid.uuid4(), _USER, "closePosition", _REF, _SHA, None))


@pytest.mark.parametrize("role", ["origin", "replica", "local"])
def test_the_bound_is_write_once(db: str, role: str) -> None:
    with _conn(db) as c:
        _user(c)
        anchor = uuid.uuid4()
        c.execute(_INSERT, (anchor, _USER, "purgeRecordedData", _REF, _SHA, _BEFORE))
        with c.transaction():
            c.execute(sql.SQL("SET LOCAL session_replication_role = {}").format(sql.Literal(role)))
            with pytest.raises(pgerr.CheckViolation) as exc, c.transaction():
                c.execute(
                    "UPDATE idempotency_anchors SET before_us = before_us + 1 WHERE id = %s",
                    (anchor,),
                )
        assert exc.value.diag.constraint_name == "trg_ia_write_once"
        assert exc.value.diag.message_primary == (
            "trg_ia_write_once: idempotency_anchors.before_us is write-once"
        )


def test_the_store_creates_once_and_finds_the_bound_scoped_to_its_principal(db: str) -> None:
    with _conn(db) as c:
        _user(c)

    async def run() -> None:
        relational = SqlAlchemyRelationalRepository(db.replace("+psycopg", "+asyncpg"))
        store = SqlAlchemyPurgeAnchorStore(relational)
        try:
            anchor = NewPurgeAnchor(
                id=uuid.uuid4(), created_by=_USER, client_ref=_REF, request_sha256=_SHA,
                before_us=_BEFORE,
            )  # fmt: skip
            assert await store.create(anchor) is True
            assert await store.create(anchor) is False
            found = await store.find(_USER, _REF, _SHA)
            assert found is not None and (found.id, found.before_us) == (anchor.id, _BEFORE)
            assert found.body_matches is True
            other = await store.find(_USER, _REF, "cd" * 32)
            assert other is not None and other.body_matches is False
            assert await store.find(uuid.uuid4(), _REF, _SHA) is None
        finally:
            await relational.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_the_revision_round_trips(db: str, seeded: bool) -> None:
    """C-5.5: an order anchor does not hold the downgrade back."""
    with _conn(db) as c:
        if seeded:
            _user(c)
            c.execute(_INSERT, (uuid.uuid4(), _USER, "closePosition", _REF, _SHA, None))
        head = _catalog(c)
    assert _alembic(db, "downgrade", _PREV).returncode == 0
    with _conn(db) as c:
        column = c.execute(
            "SELECT count(*) FROM pg_attribute WHERE attrelid = 'idempotency_anchors'::regclass "
            "AND attname = 'before_us' AND NOT attisdropped"
        ).fetchone()
        assert column == (0,)
        kept = c.execute("SELECT count(*) FROM idempotency_anchors").fetchone()
        assert kept == ((1,) if seeded else (0,))
    assert _alembic(db, "upgrade", "head").returncode == 0
    with _conn(db) as c:
        assert _catalog(c) == head


def test_the_downgrade_refuses_while_a_purge_anchor_exists(db: str) -> None:
    with _conn(db) as c:
        _user(c)
        c.execute(_INSERT, (uuid.uuid4(), _USER, "purgeRecordedData", _REF, _SHA, _BEFORE))
        before = _catalog(c)
    refused = _alembic(db, "downgrade", _PREV)
    assert refused.returncode != 0 and f"{_REV} downgrade refused" in refused.stderr
    with _conn(db) as c:
        assert _catalog(c) == before
        assert c.execute("SELECT count(*) FROM idempotency_anchors").fetchone() == (1,)
