"""Integration (E43-T10, #1238 ruling BQ-10): the offline chain check on Postgres 16.

The roles come from the shipped `pg_bootstrap.sql` and the schema is migrated as `cv_owner`, as in
`test_audit_guard_cv_app.py`; the checked database is a copy of it (`TEMPLATE`) whose name marks
it for tests, so the corrupted-chain fixture (#962) may load into it. The entry point then runs
on the `cv_ro` login and must name the fixture's victim; and a write is refused both to `cv_ro`
itself and to any login on the tool's read-only sessions. Needs Docker (testcontainers) and
`psql`; CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import sqlalchemy as sa
from psycopg.errors import InsufficientPrivilege
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from candleviewer import audit_chain_verify as entry
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyAuditVerifyDatabase,
)
from candleviewer.storage.repositories.relational_sqlalchemy import sqlstate_of
from tests.fixtures.admin.corrupt_chain import seed_corrupted_chain
from tests.integration.audit.test_audit_guard_cv_app import (
    _as,
    _bootstrap_roles,
    _exec,
    _migrate_as_owner,
)

pytestmark = pytest.mark.integration

_PROBE = "INSERT INTO audit_checkpoints (id, head_id, head_hash, row_count) "
_PROBE += "VALUES (gen_random_uuid(), 999999, repeat('0', 64), 0)"


@pytest.fixture(scope="module")
def pg() -> Iterator[str]:
    """The superuser DSN of `verify_test`, a copy of the bootstrapped, migrated `candleviewer`."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql")
        _bootstrap_roles(dsn)
        _migrate_as_owner(dsn)
        server = dsn.rsplit("/", 1)[0]  # a template copy needs no session on the template
        _exec(
            f"{server}/postgres", "CREATE DATABASE verify_test TEMPLATE candleviewer OWNER cv_owner"
        )
        yield f"{server}/verify_test"


def test_the_entry_point_on_cv_ro_names_the_fixtures_victim(
    pg: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    superuser = pg.replace("postgresql://", "postgresql+asyncpg://", 1)
    victim = asyncio.run(seed_corrupted_chain(superuser, tmp_path))
    monkeypatch.setenv("CV_AUDIT_VERIFY_DSN", _as(pg, "cv_ro", "postgresql+asyncpg"))
    assert entry.main([]) == 1
    out = capsys.readouterr().out
    assert f"FAIL chain: first_bad_id={victim} kind=entry_hash_mismatch" in out
    for section in ("grants", "triggers", "fields"):  # cv_app S+I, cv_ro exactly SELECT, live
        assert f"PASS {section}" in out
    assert "cv_ro_test_pw" not in out


def test_cv_ro_may_not_write_the_audit_tables(pg: str) -> None:
    with pytest.raises(InsufficientPrivilege):
        _exec(_as(pg, "cv_ro"), _PROBE)


def test_the_tools_sessions_refuse_a_write_whatever_the_login(pg: str) -> None:
    """`cv_app` may append a checkpoint; on the tool's read-only session it may not (25006)."""

    async def attempt() -> str | None:
        database = SqlAlchemyAuditVerifyDatabase(
            _as(pg, "cv_app", "postgresql+asyncpg"),
            statement_timeout_ms=5_000,
            max_entry_bytes=65_536,
        )
        try:
            async with database._relational.engine.connect() as conn:
                await conn.execute(sa.text(_PROBE))
        except DBAPIError as exc:
            return sqlstate_of(exc)
        finally:
            await database.dispose()
        return None

    assert asyncio.run(attempt()) == "25006"
    with psycopg.connect(pg) as conn:
        assert conn.execute(
            "SELECT count(*) FROM audit_checkpoints WHERE head_id = 999999"
        ).fetchone() == (0,)
