"""Integration: the #3998 boot check of the runtime role's guarded privileges on real Postgres 16.

Bootstrapped with the shipped `infra/scripts/pg_bootstrap.sql` and migrated to head as `cv_owner`
(the CI `migrations` order), `cv_app`, the app's login, holds none of the pinned privileges, so
the check passes in `live`. `GRANT DELETE ON exchange_accounts TO cv_app` is the violation it names
and refuses in `live`; the test revokes it again. `cv_owner` holds every pinned privilege as the
tables' owner and the container's superuser as a superuser: each is reported, and is no violation
outside `live`. A database migrated to head before the roles exist (the guards' no-op branch)
keeps every relation's ACL at its default. `testcontainers` in CI only; the unit tests are
`tests/unit/storage/test_guarded_privileges.py`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.errors import GuardedPrivilegesHeld
from candleviewer.storage.guarded_privileges import (
    GUARDED_PAIRS,
    HeldPrivilege,
    PrivilegeReport,
    check_guarded_privileges,
)
from candleviewer.storage.repositories.guarded_privileges_sqlalchemy import (
    SqlAlchemyGuardedPrivileges,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_ROLELESS = "roleless"
_GRANT = "GRANT DELETE ON exchange_accounts TO cv_app"
_REVOKE = "REVOKE DELETE ON exchange_accounts FROM cv_app"


def _login(dsn: str, role: str) -> str:
    """`dsn` logged in as a bootstrap role (test-only password `<role>_test_pw`)."""
    return re.sub(r"://[^@]+@", f"://{role}:{role}_test_pw@", dsn)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


def _conn(dsn: str) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _alembic_head(dsn: str) -> None:
    subprocess.run(  # fixed argv: literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of `candleviewer`, set up like production: `pg_bootstrap.sql`, then head as
    `cv_owner`. First, before the roles exist, `roleless` is migrated to head as the superuser."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        with _conn(dsn) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_ROLELESS)))
        _alembic_head(_database(dsn, _ROLELESS))
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        _alembic_head(_login(dsn, "cv_owner"))
        yield dsn


@asynccontextmanager
async def _read_as(dsn: str) -> AsyncIterator[SqlAlchemyGuardedPrivileges]:
    """The app's read on its own pool, logged in as `dsn` says."""
    relational = SqlAlchemyRelationalRepository(dsn, "guarded-privileges-it")
    try:
        yield SqlAlchemyGuardedPrivileges(relational)
    finally:
        await relational.dispose()


async def test_cv_app_at_head_holds_no_guarded_privilege_and_live_starts(pg_dsn: str) -> None:
    async with _read_as(_login(pg_dsn, "cv_app")) as reader:
        assert await reader.held() == PrivilegeReport(False, ())
        await check_guarded_privileges(reader.held, live=True, gauge=None, timeout_s=10.0)


async def test_a_delete_granted_back_is_named_and_refused_in_live(pg_dsn: str) -> None:
    with _conn(_login(pg_dsn, "cv_owner")) as owner:
        owner.execute(_GRANT)
        try:
            async with _read_as(_login(pg_dsn, "cv_app")) as reader:
                held = (HeldPrivilege("exchange_accounts", "DELETE", via_owner=False),)
                assert await reader.held() == PrivilegeReport(False, held)
                with pytest.raises(GuardedPrivilegesHeld, match=r"exchange_accounts\.DELETE$"):
                    await check_guarded_privileges(
                        reader.held, live=True, gauge=None, timeout_s=10.0
                    )
        finally:
            owner.execute(_REVOKE)
    async with _read_as(_login(pg_dsn, "cv_app")) as reader:
        assert (await reader.held()).held == ()


@pytest.mark.parametrize("superuser", [False, True], ids=["cv_owner", "container-superuser"])
async def test_an_owner_or_superuser_holds_every_pair_and_is_refused_only_in_live(
    pg_dsn: str, superuser: bool
) -> None:
    async with _read_as(pg_dsn if superuser else _login(pg_dsn, "cv_owner")) as reader:
        report = await reader.held()
        assert report.superuser is superuser
        assert sorted((h.table, h.privilege, h.via_owner) for h in report.held) == [
            (table, privilege, True) for table, privilege in GUARDED_PAIRS
        ]
        await check_guarded_privileges(reader.held, live=False, gauge=None, timeout_s=10.0)
        with pytest.raises(GuardedPrivilegesHeld):
            await check_guarded_privileges(reader.held, live=True, gauge=None, timeout_s=10.0)


def test_head_on_a_cluster_without_the_roles_leaves_every_relation_acl_untouched(
    pg_dsn: str,
) -> None:
    with _conn(_database(pg_dsn, _ROLELESS)) as c:
        version = c.execute("SELECT version_num FROM alembic_version").fetchall()
        granted = c.execute(
            "SELECT relname FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relacl IS NOT NULL ORDER BY 1"
        ).fetchall()
        tables = c.execute(
            "SELECT count(*) FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(%s)",
            (sorted({table for table, _ in GUARDED_PAIRS}),),
        ).fetchone()
    assert len(version) == 1 and tables == (len({table for table, _ in GUARDED_PAIRS}),)
    assert granted == []
