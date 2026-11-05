"""Integration: the backup sidecar's roles on real Postgres 16 (ADR-0041 section 1, #3319 B1a).

Set up like production: the shipped `infra/scripts/pg_bootstrap.sql`, given both backup
passwords, then head as `cv_owner`. The role privilege matrix: `cv_backup` reads every table and
sequence of `public`, one `cv_owner` creates later included (the default privileges), and holds
nothing else; `cv_restore` is `NOLOGIN`, a member of `cv_owner` and nothing else, its login
refused while `NOLOGIN` and once its `VALID UNTIL` has passed, over a host rule that asks for
`scram-sha-256`. `0066_backup_role_grants` round-trips on the seeded database and refuses to
upgrade while `cv_restore` can log in. `testcontainers` in CI only; the unit tests are
`tests/unit/migrations/test_0066_backup_role_grants.py`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
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

_BACKUP_PW = "cv_backup_test_pw"
_RESTORE_PW = "cv_restore_test_pw"
_REVISION = "0066_backup_role_grants"
_PARENT = "0064_orders_origin"
#: PostgreSQL 16's table privileges; none but SELECT is `cv_backup`'s.
_WRITES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
_PROBE = "cv_backup_probe"


def _login(dsn: str, role: str, password: str) -> str:
    return re.sub(r"://[^@]+@", f"://{role}:{password}@", dsn)


def _conn(dsn: str, **kw: Any) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(dsn, autocommit=True, **kw)


def _alembic(dsn: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={
            **os.environ,
            "CV_PG_DSN": dsn.replace("postgresql://", "postgresql+psycopg://"),
        },
        check=check,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN (`postgresql://`) of `candleviewer`: bootstrapped with both backup
    passwords, then migrated to head as `cv_owner`."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        info = psycopg.conninfo.conninfo_to_dict(dsn)
        psql = shutil.which("psql")
        assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw",
             "-v", f"backup_pw={_BACKUP_PW}", "-v", f"restore_pw={_RESTORE_PW}",
             "-f", str(_BOOTSTRAP)],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        _alembic(_login(dsn, "cv_owner", "cv_owner_test_pw"), "upgrade", "head")
        yield dsn


def _relations(c: psycopg.Connection[tuple[Any, ...]], kinds: str) -> list[str]:
    rows = c.execute(
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
        "AND relkind::text = ANY(%s) ORDER BY 1",
        (list(kinds),),
    ).fetchall()
    return [str(name) for (name,) in rows]


def _reads_everything(c: psycopg.Connection[tuple[Any, ...]]) -> list[str]:
    """The tables and sequences of `public` `cv_backup` cannot SELECT."""
    query = (
        "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace "
        "AND CASE WHEN c.relkind::text = ANY(%s) THEN NOT {}(%s, c.oid, 'SELECT') END ORDER BY 1"
    )
    tables = c.execute(query.format("has_table_privilege"), (["r", "p"], "cv_backup"))
    unread = [str(n) for (n,) in tables.fetchall()]
    sequences = c.execute(query.format("has_sequence_privilege"), (["S"], "cv_backup"))
    return unread + [str(n) for (n,) in sequences.fetchall()]


def test_cv_backup_may_select_every_table_and_sequence(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        assert len(_relations(c, "rp")) > 20 and _relations(c, "S")
        assert _reads_everything(c) == []
        assert c.execute(
            "SELECT has_database_privilege('cv_backup', current_database(), 'CONNECT'), "
            "has_schema_privilege('cv_backup', 'public', 'USAGE')"
        ).fetchone() == (True, True)


def test_cv_backup_holds_no_write_ddl_or_membership(pg_dsn: str) -> None:
    """The privilege matrix: every write privilege on every table, sequence writes, DDL on the
    schema and the database, and every role attribute that widens what it can do."""
    with _conn(pg_dsn) as c:
        held = c.execute(
            "SELECT c.relname, p.priv FROM pg_class c CROSS JOIN unnest(%s::text[]) AS p(priv) "
            "WHERE c.relnamespace = 'public'::regnamespace "
            "AND CASE WHEN c.relkind::text = ANY(%s) "
            "THEN has_table_privilege('cv_backup', c.oid, p.priv) END ORDER BY 1, 2",
            (list(_WRITES), ["r", "p", "v", "m"]),
        ).fetchall()
        sequences = c.execute(
            "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace "
            "AND CASE WHEN c.relkind = 'S' "
            "THEN has_sequence_privilege('cv_backup', c.oid, 'USAGE') "
            "OR has_sequence_privilege('cv_backup', c.oid, 'UPDATE') END"
        ).fetchall()
        ddl = c.execute(
            "SELECT has_schema_privilege('cv_backup', 'public', 'CREATE'), "
            "has_database_privilege('cv_backup', current_database(), 'CREATE'), "
            "has_database_privilege('cv_backup', current_database(), 'TEMP')"
        ).fetchone()
        attributes = c.execute(
            "SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolreplication, "
            "rolbypassrls FROM pg_roles WHERE rolname = 'cv_backup'"
        ).fetchone()
        member_of = c.execute(
            "SELECT r.rolname FROM pg_roles r WHERE r.rolname <> 'cv_backup' "
            "AND pg_has_role('cv_backup', r.oid, 'MEMBER') AND r.rolname NOT LIKE 'pg\\_%'"
        ).fetchall()
    assert held == [] and sequences == []
    # TEMP is PUBLIC's default on a database, not this revision's; no DDL survives a session.
    assert ddl == (False, False, True)
    assert attributes == (True, False, False, False, False, False)
    assert member_of == []


def test_cv_backup_logs_in_reads_and_is_refused_a_write(pg_dsn: str) -> None:
    with _conn(_login(pg_dsn, "cv_backup", _BACKUP_PW)) as c:
        tables = _relations(c, "rp")
        for table in tables:  # every table, as `pg_dump` reads it
            c.execute(sql.SQL("SELECT 1 FROM public.{} LIMIT 1").format(sql.Identifier(table)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM public.audit_log")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("CREATE TABLE public.cv_backup_owned (id int)")


def test_cv_backup_may_select_a_table_cv_owner_creates_later(pg_dsn: str) -> None:
    owner = _login(pg_dsn, "cv_owner", "cv_owner_test_pw")
    with _conn(owner) as c:
        c.execute("CREATE TABLE public.cv_backup_probe (id bigserial PRIMARY KEY)")
        try:
            granted = c.execute(
                "SELECT has_table_privilege('cv_backup', %s, 'SELECT'), "
                "has_table_privilege('cv_backup', %s, 'INSERT'), "
                "has_sequence_privilege('cv_backup', %s, 'SELECT')",
                (f"public.{_PROBE}", f"public.{_PROBE}", f"public.{_PROBE}_id_seq"),
            ).fetchone()
        finally:
            c.execute("DROP TABLE public.cv_backup_probe")
    assert granted == (True, False, True)


def test_cv_restore_is_nologin_and_a_member_of_the_owner_only(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        attributes = c.execute(
            "SELECT rolcanlogin, rolpassword IS NOT NULL, "
            "rolvaliduntil IS NULL OR rolvaliduntil = 'infinity', rolsuper, "
            "rolcreaterole, rolcreatedb, rolreplication, rolbypassrls "
            "FROM pg_authid WHERE rolname = 'cv_restore'"
        ).fetchone()
        member_of = c.execute(
            "SELECT r.rolname FROM pg_roles r WHERE r.rolname <> 'cv_restore' "
            "AND pg_has_role('cv_restore', r.oid, 'MEMBER') AND r.rolname NOT LIKE 'pg\\_%'"
        ).fetchall()
        backup_owner = c.execute("SELECT pg_has_role('cv_backup', 'cv_owner', 'MEMBER')")
        assert backup_owner.fetchone() == (False,)
    assert attributes == (False, True, True, False, False, False, False, False)
    assert member_of == [("cv_owner",)]


def _restore_login(pg_dsn: str) -> None:
    with _conn(_login(pg_dsn, "cv_restore", _RESTORE_PW), connect_timeout=10):
        pass


def test_cv_restore_login_is_refused_while_nologin(pg_dsn: str) -> None:
    with pytest.raises(psycopg.OperationalError, match="not permitted to log in"):
        _restore_login(pg_dsn)


def test_cv_restore_login_is_refused_once_its_valid_until_has_passed(
    pg_dsn: str,
) -> None:
    """The runbook's job window: LOGIN `VALID UNTIL` the deadline opens it, a deadline passed
    refuses it (password authentication only), and NOLOGIN closes it again."""
    with _conn(pg_dsn) as superuser:
        try:
            superuser.execute("ALTER ROLE cv_restore LOGIN VALID UNTIL 'infinity'")
            _restore_login(pg_dsn)  # the job's window: its password opens it
            superuser.execute("ALTER ROLE cv_restore VALID UNTIL '2000-01-01 00:00:00+00'")
            with pytest.raises(psycopg.OperationalError, match="authentication failed"):
                _restore_login(pg_dsn)
        finally:
            superuser.execute("ALTER ROLE cv_restore NOLOGIN VALID UNTIL 'infinity'")


def test_cv_restore_host_connections_ask_for_scram(pg_dsn: str) -> None:
    """ADR-0041 relies on `scram-sha-256` for `cv_restore` from another container: `VALID UNTIL`
    binds password authentication only. The first host rule that matches it for a non-loopback
    address is the one the sidecar meets."""
    with _conn(pg_dsn) as c:
        rule = c.execute(
            "SELECT auth_method FROM pg_hba_file_rules WHERE error IS NULL "
            "AND type LIKE 'host%' AND (user_name && ARRAY['all', 'cv_restore']) "
            "AND (database && ARRAY['all', 'candleviewer']) "
            "AND coalesce(address, '') NOT IN ('127.0.0.1', '::1') "
            "ORDER BY rule_number LIMIT 1"
        ).fetchone()
    assert rule == ("scram-sha-256",)


def test_the_revision_round_trips_on_the_seeded_database(pg_dsn: str) -> None:
    owner = _login(pg_dsn, "cv_owner", "cv_owner_test_pw")
    with _conn(pg_dsn) as c:
        assert c.execute("SELECT count(*) FROM roles").fetchone() != (0,)  # 0002's seed
        _alembic(owner, "downgrade", _PARENT)
        try:
            unread = _reads_everything(c)
            assert unread == sorted(_relations(c, "rp")) + sorted(_relations(c, "S"))
            defaults = c.execute(
                "SELECT count(*) FROM pg_default_acl d CROSS JOIN aclexplode(d.defaclacl) a "
                "WHERE a.grantee = 'cv_backup'::regrole"
            ).fetchone()
            assert defaults == (0,)
        finally:
            _alembic(owner, "upgrade", "head")
        assert _reads_everything(c) == []


def test_the_upgrade_refuses_while_cv_restore_can_log_in(pg_dsn: str) -> None:
    owner = _login(pg_dsn, "cv_owner", "cv_owner_test_pw")
    with _conn(pg_dsn) as superuser:
        _alembic(owner, "downgrade", _PARENT)
        try:
            superuser.execute("ALTER ROLE cv_restore LOGIN")
            refused = _alembic(owner, "upgrade", _REVISION, check=False)
            assert refused.returncode != 0
            assert "cv_restore can log in" in refused.stderr
            assert _RESTORE_PW not in refused.stderr + refused.stdout
        finally:
            superuser.execute("ALTER ROLE cv_restore NOLOGIN")
            _alembic(owner, "upgrade", "head")
        assert _reads_everything(superuser) == []
