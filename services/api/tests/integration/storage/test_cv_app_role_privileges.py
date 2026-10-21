"""Integration test for bugfix #1556 defect 5 (parent E07-T02, issue #168):
proves the `cv_app` role is refused DDL with `insufficient_privilege`.

Needs a real Postgres 16 (`testcontainers`, `@pytest.mark.integration` —
CONSTITUTION.md C-13.3 / `.claude/rules/40-testing.md`); no network egress
beyond the locally-started container. Not run in this sandbox: docker is
unavailable here ("not run locally: no docker" — see the PR body); this
suite is exercised by the `migrations` CI job, which also runs
`infra/scripts/pg_bootstrap.sql` to create the `cv_owner`/`cv_app`/`cv_ro`
roles before this test's DML/DDL assertions.

AC (#168 Gherkin): "Given the cv_app role, when it attempts CREATE TABLE,
ALTER TABLE or DROP TABLE, then Postgres refuses with insufficient_privilege,
asserted by an integration test."
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT = _SERVICES_API_ROOT.parents[1]
_BOOTSTRAP_SQL = _REPO_ROOT / "infra" / "scripts" / "pg_bootstrap.sql"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    # `pg_bootstrap.sql` unconditionally `\connect candleviewer`s and creates
    # that database if missing (matching the CI job's `POSTGRES_DB:
    # candleviewer`), so the container's initial database must share that
    # name for the script's role/grant statements to land on the same DB
    # alembic and this test's DML/DDL assertions run against.
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _alembic_sync_dsn(async_dsn: str) -> str:
    return async_dsn.replace("postgresql+asyncpg", "postgresql+psycopg")


def _psycopg_dsn(async_dsn: str, *, user: str | None = None, password: str | None = None) -> str:
    dsn = async_dsn.replace("postgresql+asyncpg", "postgresql")
    if user is not None:
        # testcontainers DSNs embed the superuser credentials; swap them for
        # the role under test while keeping host/port/dbname.
        import re

        dsn = re.sub(r"postgresql://[^@]+@", f"postgresql://{user}:{password}@", dsn)
    return dsn


def _swap_user(async_dsn: str, *, user: str, password: str) -> str:
    """Like `_psycopg_dsn` but keeps the `postgresql+asyncpg://` driver
    prefix, for callers (e.g. `_alembic`, via `_alembic_sync_dsn`) that
    still need to convert the driver themselves."""
    import re

    return re.sub(r"://[^@]+@", f"://{user}:{password}@", async_dsn)


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ, "CV_PG_DSN": _alembic_sync_dsn(dsn)},
        check=True,
    )


def _bootstrap_roles(dsn: str) -> None:
    """Run the *real* `infra/scripts/pg_bootstrap.sql` via `psql`, exactly as
    the `migrations` CI job does, so this test proves the shipped bootstrap
    script itself refuses DDL for `cv_app` — not a hand-rolled stand-in that
    can silently drift from it (bugfix #1556 QA follow-up)."""
    parsed = psycopg.conninfo.conninfo_to_dict(_psycopg_dsn(dsn))
    host = str(parsed.get("host", "localhost"))
    port = str(parsed.get("port", "5432"))
    dbname = str(parsed.get("dbname", "postgres"))
    superuser = str(parsed["user"])
    superuser_pw = str(parsed["password"])

    psql = shutil.which("psql")
    if psql is None:
        raise RuntimeError(
            "psql not found on PATH; the migrations CI job installs the "
            "postgresql-client package before running this test"
        )

    subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
        [
            psql,
            "-h",
            host,
            "-p",
            port,
            "-U",
            superuser,
            "-d",
            dbname,
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "owner_pw=cv_owner_test_pw",
            "-v",
            "app_pw=cv_app_test_pw",
            "-v",
            "ro_pw=cv_ro_test_pw",
            "-f",
            str(_BOOTSTRAP_SQL),
        ],
        check=True,
        env={**os.environ, "PGPASSWORD": superuser_pw},
    )


@pytest.fixture(scope="module")
def cv_app_dsn(pg_dsn: str) -> str:
    # Bootstrap roles/default-privileges *before* running migrations, exactly
    # as the `migrations` CI job orders these two steps — `pg_bootstrap.sql`'s
    # `ALTER DEFAULT PRIVILEGES` only auto-grants `cv_app`/`cv_ro` access to
    # tables created *after* it runs, so reversing the order here would leave
    # every migrated table ungranted and give a false-negative DDL-refusal
    # signal masked by a permission-denied-for-everything role.
    _bootstrap_roles(pg_dsn)
    # Run alembic as `cv_owner`, the DDL role migrations use in production
    # (21-database-schema.md Sec.1.1) and in the `migrations` CI job — not
    # the testcontainers superuser — so `ALTER DEFAULT PRIVILEGES FOR ROLE
    # cv_owner` actually applies to the tables these migrations create.
    owner_dsn = _swap_user(
        pg_dsn,
        user="cv_owner",
        password="cv_owner_test_pw",  # noqa: S106 -- test-only fixture credential, never real
    )
    _alembic(owner_dsn, "upgrade", "head")
    return _psycopg_dsn(
        pg_dsn,
        user="cv_app",
        password="cv_app_test_pw",  # noqa: S106 -- test-only fixture credential, never real
    )


def test_cv_app_create_table_is_refused_with_insufficient_privilege(
    cv_app_dsn: str,
) -> None:
    with psycopg.connect(cv_app_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as excinfo:
            cur.execute("CREATE TABLE cv_app_should_not_create (id int)")
        assert excinfo.value.sqlstate == "42501"  # insufficient_privilege
        conn.rollback()


def test_cv_app_alter_table_is_refused_with_insufficient_privilege(
    cv_app_dsn: str,
) -> None:
    with psycopg.connect(cv_app_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as excinfo:
            cur.execute("ALTER TABLE users ADD COLUMN cv_app_should_not_add int")
        assert excinfo.value.sqlstate == "42501"
        conn.rollback()


def test_cv_app_drop_table_is_refused_with_insufficient_privilege(
    cv_app_dsn: str,
) -> None:
    with psycopg.connect(cv_app_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as excinfo:
            cur.execute("DROP TABLE users")
        assert excinfo.value.sqlstate == "42501"
        conn.rollback()


def test_cv_app_retains_dml_on_existing_tables(cv_app_dsn: str) -> None:
    """Negative-privilege coverage must not silently also break DML — the
    role is meant to be DML-only, not privilege-less."""
    with psycopg.connect(cv_app_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM roles")
        row = cur.fetchone()
        assert row is not None
        conn.rollback()


def test_auth_keys_grants_are_pinned_at_head(cv_app_dsn: str) -> None:
    """`auth_keys` holds class S wraps (21 Sec.3.1.5a): `cv_app` gets no DELETE or TRUNCATE and
    `cv_ro` only SELECT, at head, so a later widening (a blanket GRANT) fails here."""
    probe = (
        "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
        "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p "
        "WHERE has_table_privilege(%s, 'auth_keys', p)"
    )
    with psycopg.connect(cv_app_dsn) as conn:
        held = [conn.execute(probe, (role,)).fetchone() for role in ("cv_app", "cv_ro")]
    assert held == [("INSERT SELECT UPDATE",), ("SELECT",)]


def test_account_profile_grants_are_pinned_at_head(cv_app_dsn: str) -> None:
    """Profile history is written only by `trg_ap_revision`'s definer function (21 Sec.3.2.5,
    SR-E28-07): `cv_app` reads it and holds no INSERT, UPDATE, DELETE or TRUNCATE on it; on the
    live profile rows it holds no DELETE, as a profile leaves by soft delete (21 Sec.3.2.4)."""
    probe = (
        "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
        "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p "
        "WHERE has_table_privilege(%s, %s, p)"
    )
    with psycopg.connect(cv_app_dsn) as conn:
        held = {
            (role, table): conn.execute(probe, (role, table)).fetchone()
            for role in ("cv_app", "cv_ro")
            for table in ("account_profiles", "account_profile_revisions")
        }
    assert held[("cv_app", "account_profile_revisions")] == ("SELECT",)
    assert held[("cv_app", "account_profiles")] == ("INSERT SELECT UPDATE",)
    assert held[("cv_ro", "account_profile_revisions")] == ("SELECT",)
    assert held[("cv_ro", "account_profiles")] == ("SELECT",)


def test_risk_state_grants_are_pinned_at_head(cv_app_dsn: str) -> None:
    """The E39 risk state is kept indefinitely (21 Sec.3.11): a release updates its row and nothing
    deletes one, so `cv_app` holds no DELETE on the three tables and `cv_ro` only SELECT."""
    probe = (
        "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
        "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p "
        "WHERE has_table_privilege(%s, %s, p)"
    )
    tables = ("risk_lockouts", "risk_policy", "kill_switch_state")
    with psycopg.connect(cv_app_dsn) as conn:
        held = {
            (role, table): conn.execute(probe, (role, table)).fetchone()
            for role in ("cv_app", "cv_ro")
            for table in tables
        }
    for table in tables:
        assert held[("cv_app", table)] == ("INSERT SELECT UPDATE",), table
        assert held[("cv_ro", table)] == ("SELECT",), table


def test_trade_group_grants_are_pinned_at_head(cv_app_dsn: str) -> None:
    """A trade group and its legs are trading history, and a definition leaves by soft delete
    (21 Sec.3.3.3a, revision 0039_trade_groups): `cv_app` holds no DELETE or TRUNCATE on them.
    A definition's member is removed outright, so `cv_app` keeps DELETE there; `cv_ro` reads."""
    probe = (
        "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
        "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p "
        "WHERE has_table_privilege(%s, %s, p)"
    )
    history = ("trade_groups", "trade_group_legs", "trade_group_definitions")
    with psycopg.connect(cv_app_dsn) as conn:
        held = {
            (role, table): conn.execute(probe, (role, table)).fetchone()
            for role in ("cv_app", "cv_ro")
            for table in (*history, "trade_group_definition_members")
        }
    for table in history:
        assert held[("cv_app", table)] == ("INSERT SELECT UPDATE",)
        assert held[("cv_ro", table)] == ("SELECT",)
    assert held[("cv_app", "trade_group_definition_members")] == ("DELETE INSERT SELECT UPDATE",)
    assert held[("cv_ro", "trade_group_definition_members")] == ("SELECT",)


def test_account_and_key_grants_are_pinned_at_head(cv_app_dsn: str) -> None:
    """#2758: `cv_app` can delete neither table a key's guarantee rests on. `api_keys` lost DELETE
    in 0024 and `exchange_accounts` in 0044: a delete of the parent cascades to the keys and lets
    the id be inserted again (another environment, an older key row), which no UPDATE guard sees.
    It keeps INSERT, SELECT and UPDATE (the store inserts, patches and soft-deletes), holds no
    TRUNCATE (the bootstrap never granted it), and `cv_ro` reads."""
    probe = (
        "SELECT string_agg(p, ' ' ORDER BY p) FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', "
        "'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p "
        "WHERE has_table_privilege(%s, %s, p)"
    )
    tables = ("exchange_accounts", "api_keys")
    with psycopg.connect(cv_app_dsn) as conn:
        held = {
            (role, table): conn.execute(probe, (role, table)).fetchone()
            for role in ("cv_app", "cv_ro")
            for table in tables
        }
    for table in tables:
        assert held[("cv_app", table)] == ("INSERT SELECT UPDATE",), table
        assert held[("cv_ro", table)] == ("SELECT",), table
