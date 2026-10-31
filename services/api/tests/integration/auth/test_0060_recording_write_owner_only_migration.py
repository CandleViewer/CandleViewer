"""Integration: `0060_recording_write_owner_only` on real Postgres 16 (E16-S01 #484, G-04).

The data effect, on 0016's pattern: the upgrade takes `recording:write` from `manager` and nothing
else; the `owner` and `viewer` rows and the `permissions` rows are untouched; each direction run
twice changes nothing the second time; the downgrade restores the exact grant set. The revision's
id, parent and SQL are read from its file, so a re-parent at merge changes nothing here. Each test
first brings the database to the revision's parent, so the order of the tests does not matter.
Not run locally (no docker); exercised by the integration and migrations CI jobs.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_ROWS_SQL = (
    "SELECT r.name::text, p.code, rp.granted_at FROM role_permissions rp "
    "JOIN roles r ON r.id = rp.role_id JOIN permissions p ON p.id = rp.permission_id"
)
_PERMISSIONS_SQL = "SELECT id::text, code, domain, description, is_dangerous FROM permissions"


def _revision() -> ModuleType:
    versions = _ROOT / "candleviewer" / "migrations" / "versions"
    [path] = sorted(versions.glob("*_recording_write_owner_only.py"))
    spec = importlib.util.spec_from_file_location("_rev_recording_write_owner_only", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_REV = _revision()


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#484)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn},
        check=True,
    )


def _libpq(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg", "postgresql")


def _at_parent(dsn: str) -> None:
    """The database at the revision's parent, from any state the other test leaves."""
    _alembic(dsn, "upgrade", _REV.revision)
    _alembic(dsn, "downgrade", _REV.down_revision)


def _rows(dsn: str) -> dict[str, dict[str, datetime]]:
    """Each role's grants: permission code -> `granted_at`, so a row deleted and inserted again
    reads as changed."""
    found: dict[str, dict[str, datetime]] = {}
    with psycopg.connect(_libpq(dsn)) as conn:
        for role, code, granted_at in conn.execute(_ROWS_SQL).fetchall():
            found.setdefault(str(role), {})[str(code)] = granted_at
    return found


def _permissions(dsn: str) -> set[tuple[object, ...]]:
    with psycopg.connect(_libpq(dsn)) as conn:
        return {tuple(row) for row in conn.execute(_PERMISSIONS_SQL).fetchall()}


def _run_sql(dsn: str, sql: str) -> None:
    with psycopg.connect(_libpq(dsn), autocommit=True) as conn:
        conn.execute(sql)


def test_upgrade_takes_recording_write_from_the_manager_alone_and_downgrade_restores_it(
    pg_dsn: str,
) -> None:
    _at_parent(pg_dsn)
    before, permissions = _rows(pg_dsn), _permissions(pg_dsn)
    assert "recording:write" in before["manager"]  # 0001 seeded it

    _alembic(pg_dsn, "upgrade", _REV.revision)
    after = _rows(pg_dsn)
    kept = {code: at for code, at in before["manager"].items() if code != "recording:write"}
    assert set(before["manager"]) - set(after["manager"]) == {"recording:write"}
    assert after["manager"] == kept  # every other Manager row as it was, `granted_at` included
    assert (after["owner"], after["viewer"]) == (before["owner"], before["viewer"])
    assert "recording:write" in after["owner"] and "recording:write" not in after["viewer"]
    assert _permissions(pg_dsn) == permissions

    _alembic(pg_dsn, "downgrade", _REV.down_revision)
    restored = _rows(pg_dsn)
    assert {role: set(codes) for role, codes in restored.items()} == {
        role: set(codes) for role, codes in before.items()
    }
    assert (restored["owner"], restored["viewer"]) == (before["owner"], before["viewer"])
    assert _permissions(pg_dsn) == permissions


def test_each_direction_run_twice_changes_nothing_the_second_time(pg_dsn: str) -> None:
    _at_parent(pg_dsn)
    permissions = _permissions(pg_dsn)

    _alembic(pg_dsn, "upgrade", _REV.revision)
    upgraded = _rows(pg_dsn)
    _run_sql(pg_dsn, _REV._REVOKE_SQL)  # the upgrade again: nothing left to delete
    assert _rows(pg_dsn) == upgraded

    _alembic(pg_dsn, "downgrade", _REV.down_revision)
    downgraded = _rows(pg_dsn)
    _run_sql(pg_dsn, _REV._GRANT_SQL)  # the downgrade again: ON CONFLICT DO NOTHING
    assert _rows(pg_dsn) == downgraded
    assert _permissions(pg_dsn) == permissions
