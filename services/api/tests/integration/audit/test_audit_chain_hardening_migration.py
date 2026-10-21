"""Integration: `0045_audit_chain_hardening`'s search_path pin (#4032) on real Postgres 16.

0003's `audit_chain()` names what it calls (`digest`, `encode`, `audit_field`, ...) and the table
it reads without a schema, so without a search_path of its own it resolves them through the path of
the session that inserts; `audit_field()` runs under whichever path the chain has. 0045 gives the
chain `pg_catalog, public, pg_temp`. Here a session puts a schema first on its path that holds a
`digest(text, text)` returning 32 zero bytes. At head, the row it appends is hashed by pgcrypto's
`digest`. At 0044, the shadow forges the hash to 64 zeros, which shows the case tells the two
apart. A temporary `audit_log` of the session's own, holding a forged head, is the other case: a
path that does not name `pg_temp` searches it first, so at 0044 the row the session appends links
to the forged head; `pg_temp` is last in the pinned path, so at head the row links to the real
one. The upgrade pins the function again, with the same body as before. Bootstrapped with the
shipped `infra/scripts/pg_bootstrap.sql` and migrated as `cv_owner` (the CI `migrations` order).
`testcontainers` in CI; the offline render is
`tests/unit/migrations/test_0045_audit_chain_hardening.py`, and the id drawn under the lock is
`tests/integration/audit/test_audit_repository.py`'s.
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
_REV, _PREV = "0045_audit_chain_hardening", "0044_account_no_hard_delete"
_TEMPLATE = "chain_hardening_template"
_PINNED = ["search_path=pg_catalog, public, pg_temp"]
#: `audit_chain()`'s own settings and the md5 of its body.
_CONFIG = (
    "SELECT p.proconfig, md5(p.prosrc) FROM pg_proc p "
    "JOIN pg_namespace n ON n.oid = p.pronamespace "
    "WHERE n.nspname = 'public' AND p.proname = 'audit_chain'"
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
#: A temporary `audit_log` with one forged row. A path that does not name `pg_temp` searches the
#: temporary schema first, so there its `entry_hash` is the chain head (the id is any high one).
_FORGED = "f" * 64
_TEMP_HEAD = (
    "CREATE TEMP TABLE audit_log (id bigint, entry_hash text); "
    "INSERT INTO pg_temp.audit_log VALUES (4611686018427387904, repeat('f', 64))"
)
#: The next row, through `public.audit_log`: the session's own `audit_log` is the temporary one.
_NEXT = (
    "INSERT INTO public.audit_log (record_id, actor_label, action) "
    "VALUES (gen_random_uuid(), 'temp-probe', 'auth.temp_probe') RETURNING prev_hash"
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
        assert psql is not None, "psql not found; the integration lane's runner image ships it"
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


def _config(dsn: str) -> tuple[Any, ...]:
    with _conn(dsn) as c:
        [row] = c.execute(_CONFIG).fetchall()
    return row


def _append_through_the_shadow(dsn: str) -> str:
    """The entry hash of a row `cv_app` appends with the shadow schema first on its path."""
    with _conn(_as(dsn, "cv_app")) as c:
        c.execute("SET search_path = shadow, public")
        (row,) = c.execute(_PROBE).fetchall()
    return str(row[0])


def _append_beside_a_forged_head(dsn: str) -> tuple[str, str]:
    """`(head, linked)`: the entry hash of the real head, and the `prev_hash` of the row `cv_app`
    appends from a session whose own `audit_log` is a temporary table holding a forged head. The
    session is new, so the chain function is first planned there with the temporary table in
    place."""
    with _conn(_as(dsn, "cv_app")) as c:
        (head,) = c.execute(_PROBE).fetchall()
    with _conn(_as(dsn, "cv_app")) as c:
        c.execute(_TEMP_HEAD)
        (row,) = c.execute(_NEXT).fetchall()
    return str(head[0]), str(row[0])


def test_the_chain_function_carries_the_pinned_search_path(pg_dsn: str) -> None:
    assert _config(_fresh(pg_dsn))[0] == _PINNED


def test_a_session_path_cannot_shadow_what_the_chain_calls(pg_dsn: str) -> None:
    assert _append_through_the_shadow(_fresh(pg_dsn)) != "0" * 64


def test_the_round_trip_drops_the_pin_and_pins_it_again(pg_dsn: str) -> None:
    """C-5.5, on a seeded database: at 0044 the function has no path of its own and the shadow
    forges the hash; the upgrade pins it again, with the same body as before."""
    dsn = _fresh(pg_dsn)
    at_head = _config(dsn)
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    assert _config(dsn)[0] is None
    assert _append_through_the_shadow(dsn) == "0" * 64
    upgraded = _alembic(dsn, "upgrade", _REV)
    assert upgraded.returncode == 0, upgraded.stderr
    assert _config(dsn) == at_head
    assert _append_through_the_shadow(dsn) != "0" * 64


def test_a_temporary_table_cannot_stand_in_for_the_chain_head(pg_dsn: str) -> None:
    """`pg_temp` is last in the pinned path: the row a session appends while its own temporary
    `audit_log` holds a forged head links to the real head. At 0044 it links to the forged one,
    which shows the case tells the two apart."""
    dsn = _fresh(pg_dsn)
    head, linked = _append_beside_a_forged_head(dsn)
    assert linked == head != _FORGED
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    head, linked = _append_beside_a_forged_head(dsn)
    assert linked == _FORGED != head
