"""Integration: the hotkey_profiles revision on real Postgres 16 (E10-T05, #5211): the CHECKs at
their bounds, `ux_hk_name` (unique per user as `lower()` folds it), `ux_hk_active` (one active
profile per user), the cascade with the owner, and the round trip, upgrade -> downgrade -> upgrade,
on an empty and on a seeded database, the seeded downgrade refused. `testcontainers`: CI, or locally
when the host's load allows (C-5.5).
"""

from __future__ import annotations

import importlib.util
import json
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
    if "CREATE TABLE hotkey_profiles (" in path.read_text(encoding="utf-8")
)
Conn = psycopg.Connection[tuple[Any, ...]]


def _down_revision() -> str:
    """Read from the file, so a re-parent edits the migration and the lockfile only."""
    spec = importlib.util.spec_from_file_location("rev_hotkey_profiles_it", _FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#5211)
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


def _profile(c: Conn, user: str, name: str, bindings: object = None, **kw: Any) -> str:
    pid = str(uuid.uuid4())
    stored = json.dumps({"ticket.side_buy": "B"} if bindings is None else bindings)
    c.execute(
        "INSERT INTO hotkey_profiles (id, owner_user_id, name, bindings, is_active, version) "
        "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
        (pid, user, name, stored, kw.get("is_active", False), kw.get("version", 1)),
    )
    return pid


def _exists(c: Conn) -> bool:
    return c.execute("SELECT to_regclass('hotkey_profiles')").fetchone() == ("hotkey_profiles",)


def test_a_new_profile_is_inactive_at_version_1(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        user = _user(c)
        pid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO hotkey_profiles (id, owner_user_id, name, bindings) "
            "VALUES (%s, %s, 'CandleViewer Default', '{}'::jsonb)",
            (pid, user),
        )
        row = c.execute(
            "SELECT is_active, version, bindings, created_at = updated_at FROM hotkey_profiles "
            "WHERE id = %s",
            (pid,),
        ).fetchone()
        assert row == (False, 1, {}, True)


def test_the_checks_hold_the_name_the_bindings_object_and_the_version(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        user = _user(c)
        _profile(c, user, "é" * 80)  # characters, not bytes
        refused = [
            ("", None, 1, "hk_name_len"),
            ("x" * 81, None, 1, "hk_name_len"),
            ("array", ["B"], 1, "hk_bindings"),
            ("string", "B", 1, "hk_bindings"),
            ("v0", None, 0, "hk_version"),
        ]
        for name, bindings, version, check in refused:
            with pytest.raises(pgerr.CheckViolation) as err:
                _profile(c, user, name, bindings, version=version)
            assert err.value.diag.constraint_name == check, name


def test_ux_hk_name_is_unique_per_user_as_lower_folds_it(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        _profile(c, a, "Scalping")
        with pytest.raises(pgerr.UniqueViolation) as err:
            _profile(c, a, "SCALPING")
        assert err.value.diag.constraint_name == "ux_hk_name"
        _profile(c, b, "scalping")  # another user's profiles are another namespace


def test_ux_hk_active_lets_a_user_hold_one_active_profile(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        _profile(c, a, "One", is_active=True)
        _profile(c, a, "Two")  # any number of inactive ones
        with pytest.raises(pgerr.UniqueViolation) as err:
            _profile(c, a, "Three", is_active=True)
        assert err.value.diag.constraint_name == "ux_hk_active"
        _profile(c, b, "Theirs", is_active=True)


def test_a_users_profiles_go_with_the_user(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _user(c, owner=True)
        gone = _user(c)
        pid = _profile(c, gone, "Cascade")
        c.execute("DELETE FROM users WHERE id = %s", (gone,))
        assert c.execute("SELECT 1 FROM hotkey_profiles WHERE id = %s", (pid,)).fetchone() is None


def test_round_trip_up_down_up_seeded_then_empty(pg_dsn: str) -> None:
    """C-5.2 and C-5.5: a seeded database refuses the downgrade (its profiles would be lost) and
    keeps the table; emptied, it goes down and comes back up; and up, down, up again on the empty
    database."""
    prev = _down_revision()
    with _conn(pg_dsn) as c:
        _profile(c, _user(c), "Blocks the downgrade")
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0 and "downgrade refused" in refused.stderr
        assert _exists(c)
        c.execute("DELETE FROM hotkey_profiles")
        assert _alembic(pg_dsn, "downgrade", prev).returncode == 0
        assert not _exists(c)
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        assert _exists(c)
        assert _alembic(pg_dsn, "downgrade", prev).returncode == 0
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        assert _exists(c)
        _profile(c, _user(c), "Back", is_active=True)  # the table works after the round trip
