"""Integration: the password_history revision on real Postgres 16 (#2110 / #2330): the Argon2id
CHECK, the per-user key, the cascade with the user, the store's compare-and-swap and prune, and
the round trip with the refused downgrade. `testcontainers` in CI; not run on the laptop or the VPS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
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
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_FILE = next(  # the revision that creates the table: its id is read from it, never repeated
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "CREATE TABLE password_history (" in path.read_text(encoding="utf-8")
)
_H = "$argon2id$v=19$m=65536,t=3,p=4$"  # an Argon2id prefix; the CHECK reads no further
_INSERT = "INSERT INTO password_history (user_id, password_hash) VALUES (%s, %s)"
_COUNT = "SELECT count(*) FROM password_history WHERE user_id = %s"
_PARAMS = {"m": 65536, "t": 3, "p": 4}
#: The active owner the owner floor (21 Sec.3.1.2) needs before any users row changes.
_OWNER = (
    "WITH u AS (INSERT INTO users (id, email, username, password_hash, status) VALUES "
    "(%(id)s, 'owner@x.invalid', 'owner', '$argon2id$x', 'active') RETURNING id) "
    "INSERT INTO user_roles (user_id, role_id) SELECT u.id, r.id FROM u, roles r "
    "WHERE r.name = 'owner'"
)
Conn = psycopg.Connection[tuple[Any, ...]]


def _down_revision() -> str:
    spec = importlib.util.spec_from_file_location("rev_password_history_it", _FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2110)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        with _conn(dsn) as c:  # `trg_owner_floor_users` checks every users UPDATE and DELETE
            c.execute(_OWNER, {"id": str(uuid.uuid4())})
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, %s, 'active')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}", _H + "current"),
    )
    return uid


def test_only_an_argon2id_hash_is_kept(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        uid = _user(c)
        c.execute(_INSERT, (uid, _H))
        with pytest.raises(pgerr.CheckViolation):
            c.execute(
                "INSERT INTO password_history (user_id, password_hash) VALUES (%s, 'plain')", (uid,)
            )


def test_the_history_goes_with_the_user(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        uid = _user(c)
        c.execute(_INSERT, (uid, _H))
        c.execute("DELETE FROM users WHERE id = %s", (uid,))
        row = c.execute(_COUNT, (uid,)).fetchone()
        assert row == (0,)


def test_the_store_swaps_the_hash_once_and_keeps_four_retired(pg_dsn: str) -> None:
    """BQ-227 / BQ-232: one unit of work swaps the hash against the expected one, retires it and
    prunes to 4; a change against a stale hash writes nothing."""
    with _conn(pg_dsn) as c:
        uid = _user(c)
    relational = SqlAlchemyRelationalRepository(pg_dsn, "auth")
    repo = SqlAlchemyUserRepository(relational, dict, clock=lambda: datetime.now(UTC))
    t0 = datetime(2026, 10, 31, tzinfo=UTC)

    async def run() -> list[bool]:
        results = []
        current = _H + "current"
        for i in range(6):
            new = f"{_H}new{i}"
            results.append(
                await repo.change_password(
                    uid,
                    expected_hash=current,
                    new_hash=new,
                    algo_params=_PARAMS,
                    keep=4,
                    now=t0 + timedelta(minutes=i),
                )
            )
            current = new
        results.append(
            await repo.change_password(
                uid, expected_hash=_H + "stale", new_hash=_H + "x", algo_params={}, keep=4, now=t0
            )
        )
        history = await repo.recent_password_hashes(uid, limit=4)
        await relational.dispose()
        assert history == (_H + "new4", _H + "new3", _H + "new2", _H + "new1")
        return results

    assert asyncio.run(run()) == [True] * 6 + [False]
    with _conn(pg_dsn) as c:
        row = c.execute("SELECT password_hash FROM users WHERE id = %s", (uid,)).fetchone()
        assert row == (_H + "new5",)
        n = c.execute(_COUNT, (uid,)).fetchone()
        assert n == (4,)


def test_the_downgrade_is_refused_while_a_row_exists_then_round_trips(pg_dsn: str) -> None:
    previous = _down_revision()
    with _conn(pg_dsn) as c:
        _user_id = _user(c)
        c.execute(
            "INSERT INTO password_history (user_id, password_hash) VALUES (%s, %s)", (_user_id, _H)
        )
    refused = _alembic(pg_dsn, "downgrade", previous)
    assert refused.returncode != 0 and "downgrade refused" in refused.stderr
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM password_history")
    assert _alembic(pg_dsn, "downgrade", previous).returncode == 0
    assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
