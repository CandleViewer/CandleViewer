"""Integration: `0045_audit_search_path` (#4032) on real Postgres 16.

0003's guard functions name what they call (`digest`, `encode`, `length`, ...) and the table
`audit_chain` reads without a schema, so without a search_path of their own they resolve them
through the path of the session that fires them. 0045 gives each `pg_catalog, public, pg_temp`.
Here a session puts a schema first on its path that holds a `digest(text, text)` returning 32 zero
bytes. At head, the row it appends is hashed by pgcrypto's `digest`. At 0044, the shadow forges the
hash to 64 zeros, which shows the case tells the two apart. The upgrade pins each function again,
and their bodies, and so the chain's hash input, are untouched. Bootstrapped with the shipped
`infra/scripts/pg_bootstrap.sql` and migrated as `cv_owner` (the CI `migrations` order).
`testcontainers` in CI; the offline render is
`tests/unit/migrations/test_0045_audit_search_path.py`.
"""

from __future__ import annotations

import os
import re
import shutil
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
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_REV, _PREV = "0045_audit_search_path", "0044_account_no_hard_delete"
_TEMPLATE = "search_path_template"
_GUARDS = ("forbid_mutation", "audit_refuse_truncate", "audit_chain", "audit_field")
_PINNED = ["search_path=pg_catalog, public, pg_temp"]
_CONFIG = (
    "SELECT p.proname::text, p.proconfig, md5(p.prosrc) FROM pg_proc p "
    "JOIN pg_namespace n ON n.oid = p.pronamespace "
    "WHERE n.nspname = 'public' AND p.proname = ANY(%s) ORDER BY p.proname"
)
#: A schema the session searches first, with a `digest` that would forge every hash.
_SHADOW = (
    "CREATE SCHEMA shadow; "
    "CREATE FUNCTION shadow.digest(text, text) RETURNS bytea LANGUAGE sql "
    "AS $$ SELECT decode(repeat('00', 32), 'hex') $$; "
    "GRANT USAGE ON SCHEMA shadow TO cv_app"
)
#: A row appended the way the audit writer does it, by `cv_app`.
_PROBE = (
    "INSERT INTO audit_log (record_id, actor_label, action) "
    "VALUES (gen_random_uuid(), 'path-probe', 'auth.path_probe') RETURNING entry_hash"
)

Conn = psycopg.Connection[tuple[Any, ...]]


def _as(dsn: str, role: str, driver: str = "postgresql") -> str:
    """`dsn` logged in as a bootstrap role (test-only password `<role>_test_pw`)."""
    return re.sub(r"^postgresql://[^@]+@", f"{driver}://{role}:{role}_test_pw@", dsn)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """As `cv_owner`, like CI; bounded, so a hung lock fails instead of waiting."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": _as(dsn, "cv_owner", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn, autocommit=True)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a cluster with the bootstrap roles and a database migrated to head as
    `cv_owner`, plus an untouched copy of it that `_fresh` clones per test.
    `pg_bootstrap.sql` connects to `candleviewer`, so the container's database has that name."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        info = psycopg.conninfo.conninfo_to_dict(dsn)
        psql = shutil.which("psql")
        assert psql is not None, "the migrations CI job installs postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved psql path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        migrated = _alembic(dsn, "upgrade", "head")
        assert migrated.returncode == 0, migrated.stderr
        with _conn(_database(dsn, "postgres")) as c:
            c.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(_TEMPLATE), sql.Identifier("candleviewer")
                )
            )
        yield dsn


def _fresh(dsn: str) -> str:
    """Its own database, cloned from the migrated template, with the shadow schema in it."""
    name = f"sp_{uuid.uuid4().hex[:12]}"
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(_TEMPLATE)
            )
        )
    fresh = _database(dsn, name)
    with _conn(fresh) as c:
        c.execute(_SHADOW)
    return fresh


def _config(dsn: str) -> list[tuple[Any, ...]]:
    with _conn(dsn) as c:
        return c.execute(_CONFIG, (list(_GUARDS),)).fetchall()


def _append_through_the_shadow(dsn: str) -> str:
    """The entry hash of a row `cv_app` appends with the shadow schema first on its path."""
    with _conn(_as(dsn, "cv_app")) as c:
        c.execute("SET search_path = shadow, public")
        (row,) = c.execute(_PROBE).fetchall()
    return str(row[0])


def test_each_guard_function_carries_the_pinned_search_path(pg_dsn: str) -> None:
    config = _config(_fresh(pg_dsn))
    assert [name for name, _, _ in config] == sorted(_GUARDS)
    assert all(pinned == _PINNED for _, pinned, _ in config)


def test_a_session_path_cannot_shadow_what_the_chain_calls(pg_dsn: str) -> None:
    assert _append_through_the_shadow(_fresh(pg_dsn)) != "0" * 64


def test_the_round_trip_resets_each_pin_and_pins_it_again(pg_dsn: str) -> None:
    """C-5.5, on a seeded database: at 0044 the functions have no path of their own and the
    shadow forges the hash; the upgrade pins them again, their bodies unchanged."""
    dsn = _fresh(pg_dsn)
    at_head = _config(dsn)
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    assert [pinned for _, pinned, _ in _config(dsn)] == [None] * len(_GUARDS)
    assert _append_through_the_shadow(dsn) == "0" * 64
    upgraded = _alembic(dsn, "upgrade", _REV)
    assert upgraded.returncode == 0, upgraded.stderr
    assert _config(dsn) == at_head
    assert _append_through_the_shadow(dsn) != "0" * 64
