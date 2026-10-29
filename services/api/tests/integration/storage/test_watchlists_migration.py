"""Integration: the watchlists revision on real Postgres 16 (E08-T07, #4706): the CHECKs at their
bounds, `ux_wl_name` (unique per user as `lower()` folds it), the cascade with the owner, and the
round trip with the refused downgrade. `testcontainers` in CI; not run on the laptop or the VPS.
"""

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
from psycopg import errors as pgerr
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_FILE = next(  # the revision that creates the table: its id is read from it, never repeated
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "CREATE TABLE watchlists (" in path.read_text(encoding="utf-8")
)
Conn = psycopg.Connection[tuple[Any, ...]]


def _down_revision() -> str:
    """Read from the file, so a re-parent edits the migration and the lockfile only."""
    spec = importlib.util.spec_from_file_location("rev_watchlists_it", _FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4706)
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
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(c: Conn, *, owner: bool = False) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$x', 'active')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    if owner:  # `trg_owner_floor_fn` lets other users go only while an active owner stays
        c.execute(
            "INSERT INTO user_roles (user_id, role_id) "
            "SELECT %s, id FROM roles WHERE name = 'owner'",
            (uid,),
        )
    return uid


def _list(c: Conn, user: str, name: str, symbols: list[str] | None = None, **kw: Any) -> str:
    wid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO watchlists (id, user_id, name, symbols, columns, version) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (wid, user, name, symbols or [], kw.get("columns", []), kw.get("version", 1)),
    )
    return wid


def test_a_new_list_is_version_1_with_empty_columns(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        wid = _list(c, _user(c), "Majors", ["BTCUSDT", "ETHUSDT"])
        row = c.execute("SELECT symbols, columns, version FROM watchlists WHERE id = %s", (wid,))
        assert row.fetchone() == (["BTCUSDT", "ETHUSDT"], [], 1)


def test_the_checks_hold_the_name_both_counts_and_the_version(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        user = _user(c)
        _list(c, user, "é" * 80, [f"S{i}USDT" for i in range(200)])  # characters, not bytes
        refused = [
            ("", None, 1),
            ("x" * 81, None, 1),
            ("over", ["XUSDT"] * 201, 1),
            ("v0", None, 0),
        ]
        for name, symbols, version in refused:
            with pytest.raises(pgerr.CheckViolation):
                _list(c, user, name, symbols, version=version)
        _list(c, user, "32 columns", columns=[f"c{i}" for i in range(32)])
        with pytest.raises(pgerr.CheckViolation) as err:
            _list(c, user, "33 columns", columns=[f"c{i}" for i in range(33)])
        assert err.value.diag.constraint_name == "wl_columns_max"


def test_ux_wl_name_is_unique_per_user_as_lower_folds_it(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        _list(c, a, "Majors")
        with pytest.raises(pgerr.UniqueViolation) as err:
            _list(c, a, "MAJORS")
        assert err.value.diag.constraint_name == "ux_wl_name"
        _list(c, b, "majors")  # another user's lists are another namespace


def test_a_users_lists_go_with_the_user(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _user(c, owner=True)
        gone = _user(c)
        wid = _list(c, gone, "Cascade")
        c.execute("DELETE FROM users WHERE id = %s", (gone,))
        assert c.execute("SELECT 1 FROM watchlists WHERE id = %s", (wid,)).fetchone() is None


def test_round_trip_up_down_up_with_the_refused_downgrade(pg_dsn: str) -> None:
    """C-5.2 and C-5.5: a list refuses the downgrade (it would be lost); an empty table drops."""
    prev = _down_revision()
    with _conn(pg_dsn) as c:
        _list(c, _user(c), "Blocks the downgrade")
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0 and "downgrade refused" in refused.stderr
        assert c.execute("SELECT to_regclass('watchlists')").fetchone() == ("watchlists",)
        c.execute("DELETE FROM watchlists")
        assert _alembic(pg_dsn, "downgrade", prev).returncode == 0
        assert c.execute("SELECT to_regclass('watchlists')").fetchone() == (None,)
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        assert c.execute("SELECT to_regclass('watchlists')").fetchone() == ("watchlists",)
