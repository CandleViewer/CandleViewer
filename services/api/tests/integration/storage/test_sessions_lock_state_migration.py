"""Integration: `0056_sessions_lock_state` on real Postgres 16 (#4743, E09-S03-F1): the two nullable
columns with no default, the downgrade refused while a live session is locked by request, and the
round trip on an empty and a seeded database. `testcontainers` in CI."""

from __future__ import annotations

import importlib.util
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
_FILE = next(  # the revision that adds the columns: its ids are read from it, never repeated
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "ADD COLUMN locked_at" in path.read_text(encoding="utf-8")
)
_TEMPLATE = "sessions_lock_state_head_template"
_COLUMNS_SQL = (
    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, d.adbin IS NOT NULL "
    "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE a.attrelid = 'sessions'::regclass AND a.attname IN ('locked_at', 'unlocked_at') "
    "AND NOT a.attisdropped ORDER BY a.attnum"
)
_USER = (
    "INSERT INTO users (id, email, username, password_hash, status) "
    "VALUES (%s, %s, %s, '$argon2id$fixture', 'active')"
)
_SESSION = (
    "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at) "
    "VALUES (%s, %s, %s, now() + interval '12 hours')"
)
#: The seeded rows' states, one literal statement each (`%s`: the session id).
_LOCKED_LIVE = "UPDATE sessions SET locked_at = now() WHERE id = %s"
_LOCKED_REVOKED = (
    "UPDATE sessions SET locked_at = now(), revoked_at = now(), revoked_reason = 'logout' "
    "WHERE id = %s"
)
_LOCKED_EXPIRED = (
    "UPDATE sessions SET locked_at = now() - interval '2 hours', "
    "issued_at = now() - interval '13 hours', expires_at = now() - interval '1 hour' WHERE id = %s"
)
_UNLOCKED = "UPDATE sessions SET unlocked_at = now() WHERE id = %s"
Conn = psycopg.Connection[tuple[Any, ...]]


def _revisions() -> tuple[str, str]:
    """`(revision, down_revision)`, read from the file, so a re-parent edits the migration and the
    lockfile only."""
    spec = importlib.util.spec_from_file_location("rev_sessions_lock_state_it", _FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.revision), str(revision.down_revision)


_REV, _PREV = _revisions()


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4743)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    """A server whose `_TEMPLATE` database is at head and untouched, for each test to clone."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        with _conn(dsn.rsplit("/", 1)[0] + "/postgres") as c:
            stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
            c.execute(stmt.format(sql.Identifier(_TEMPLATE), sql.Identifier(dsn.rsplit("/", 1)[1])))
        yield dsn.rsplit("/", 1)[0]


@pytest.fixture
def db(server: str) -> str:
    """This test's own database, at head."""
    name = f"lock_state_{uuid.uuid4().hex[:12]}"
    with _conn(f"{server}/postgres") as c:
        stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
        c.execute(stmt.format(sql.Identifier(name), sql.Identifier(_TEMPLATE)))
    return f"{server}/{name}"


def _columns(dsn: str) -> list[tuple[Any, ...]]:
    with _conn(dsn) as c:
        return c.execute(_COLUMNS_SQL).fetchall()


def _session(dsn: str, state: str) -> str:
    """A session row of a fresh user, put in *state* (one of the statements above)."""
    uid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    with _conn(dsn) as c:
        c.execute(_USER, (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"))
        c.execute(_SESSION, (sid, uid, "a" * 32 + uid.replace("-", "")))
        c.execute(state, (sid,))
    return sid


def test_upgrade_adds_two_nullable_columns_with_no_default(db: str) -> None:
    tz = "timestamp with time zone"
    assert _columns(db) == [("locked_at", tz, False, False), ("unlocked_at", tz, False, False)]


def test_downgrade_refuses_while_a_live_session_is_locked_by_request(db: str) -> None:
    """C-5.2: dropping `locked_at` would unlock the live session, so the downgrade is refused and
    changes nothing."""
    sid = _session(db, _LOCKED_LIVE)
    refused = _alembic(db, "downgrade", _PREV)
    assert refused.returncode != 0
    assert f"{_REV} downgrade refused" in refused.stderr
    assert len(_columns(db)) == 2
    with _conn(db) as c:
        row = c.execute(
            "SELECT locked_at IS NOT NULL FROM sessions WHERE id = %s", (sid,)
        ).fetchone()
        version = c.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row == (True,) and version == (_REV,)


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_downgrade_then_upgrade_round_trips_when_no_live_session_is_locked(
    db: str, seeded: bool
) -> None:
    """C-5.5: a lock by request on a revoked or expired row, and an unlock stamp, hold nothing
    back: down drops both columns and keeps the rows, up adds them back empty."""
    states = (_LOCKED_REVOKED, _LOCKED_EXPIRED, _UNLOCKED) if seeded else ()
    sids = [_session(db, state) for state in states]
    assert _alembic(db, "downgrade", _PREV).returncode == 0
    assert _columns(db) == []
    assert _alembic(db, "upgrade", "head").returncode == 0
    assert [row[0] for row in _columns(db)] == ["locked_at", "unlocked_at"]
    with _conn(db) as c:
        rows = c.execute("SELECT id::text, locked_at, unlocked_at FROM sessions").fetchall()
    assert sorted(rows) == sorted((sid, None, None) for sid in sids)
