"""Integration (E43-T10, #1238 ruling BQ-10) on Postgres 16: roles from `pg_bootstrap.sql`, the
schema migrated as `cv_owner`, checked on a test-named `TEMPLATE` copy holding the corrupted-chain
fixture (#962). The entry point on `cv_ro` names its victim; a write is refused to `cv_ro` and to
any login on the tool's read-only sessions. Needs Docker and `psql`; CI `integration` runs it."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
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

Cap = pytest.CaptureFixture[str]
MP = pytest.MonkeyPatch

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
    pg: str, tmp_path: Path, monkeypatch: MP, capsys: Cap
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


def _check_on_cv_ro(pg: str, monkeypatch: MP, capsys: Cap) -> tuple[int, str]:
    monkeypatch.setenv("CV_AUDIT_VERIFY_DSN", _as(pg, "cv_ro", "postgresql+asyncpg"))
    status = entry.main(["--check"])
    return status, capsys.readouterr().out


@contextmanager
def _changed(pg: str, change: Sequence[str], restore: Sequence[str]) -> Iterator[None]:
    for statement in change:
        _exec(pg, statement)
    try:
        yield
    finally:
        for statement in restore:
            _exec(pg, statement)


@pytest.mark.parametrize(
    ("change", "restore", "lines"),
    [
        (
            ["ALTER TABLE audit_log ENABLE REPLICA TRIGGER trg_audit_append"],
            ["ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append"],
            "FAIL triggers: trg_audit_append on audit_log: disabled",
        ),
        (
            ["ALTER TABLE audit_checkpoints DISABLE TRIGGER trg_audit_ckpt_no_truncate"],
            ["ALTER TABLE audit_checkpoints ENABLE TRIGGER trg_audit_ckpt_no_truncate"],
            "FAIL triggers: trg_audit_ckpt_no_truncate on audit_checkpoints: disabled",
        ),
        (
            ["GRANT UPDATE (reason) ON audit_log TO cv_app"],
            ["REVOKE UPDATE (reason) ON audit_log FROM cv_app"],
            "FAIL grants: cv_app on audit_log: extra ['UPDATE'], missing []",
        ),
        (
            ["GRANT INSERT (head_id) ON audit_checkpoints TO cv_ro"],
            ["REVOKE INSERT (head_id) ON audit_checkpoints FROM cv_ro"],
            "FAIL grants: cv_ro on audit_checkpoints: extra ['INSERT'], missing []",
        ),
        (
            ["GRANT REFERENCES (id) ON audit_log TO PUBLIC"],
            ["REVOKE REFERENCES (id) ON audit_log FROM PUBLIC"],
            "FAIL grants: cv_app on audit_log: extra ['REFERENCES'], missing []\n"
            "FAIL grants: cv_ro on audit_log: extra ['REFERENCES'], missing []",
        ),
        (
            [
                "CREATE ROLE cv_verify_extra NOLOGIN",
                "GRANT UPDATE ON audit_log TO cv_verify_extra",
                "GRANT cv_verify_extra TO cv_ro WITH INHERIT FALSE",
            ],
            [
                "REVOKE cv_verify_extra FROM cv_ro",
                "REVOKE UPDATE ON audit_log FROM cv_verify_extra",
                "DROP ROLE cv_verify_extra",
            ],
            "FAIL grants: cv_ro on audit_log: extra ['UPDATE'], missing []",
        ),
        (
            ["ALTER DATABASE verify_test SET session_replication_role = replica"],
            ["ALTER DATABASE verify_test RESET session_replication_role"],
            "FAIL triggers: session_replication_role 'replica' (session)\n"
            "FAIL triggers: session_replication_role 'replica' (this database, role any)",
        ),
        (
            ["ALTER ROLE cv_app SET session_replication_role = replica"],
            ["ALTER ROLE cv_app RESET session_replication_role"],
            "FAIL triggers: session_replication_role 'replica' (all databases, role cv_app)",
        ),
        (  # every catalogue read names its schema
            [
                "ALTER ROLE cv_ro SET search_path = public, pg_catalog; CREATE VIEW public."
                "pg_trigger AS SELECT oid, tgrelid, tgname, CAST('O' AS \"char\") AS tgenabled, "
                "tgisinternal FROM pg_catalog.pg_trigger; GRANT SELECT ON public.pg_trigger TO "
                "cv_ro; CREATE FUNCTION public.has_table_privilege(oid, oid, text) RETURNS boolean "
                "LANGUAGE sql AS 'SELECT false'; ALTER TABLE audit_log DISABLE TRIGGER "
                "trg_audit_append"
            ],
            [
                "ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append; DROP FUNCTION public."
                "has_table_privilege(oid, oid, text); DROP VIEW public.pg_trigger; ALTER ROLE "
                "cv_ro RESET search_path"
            ],
            "FAIL triggers: trg_audit_append on audit_log: disabled",
        ),
    ],
)
def test_the_live_check_names_every_state_that_does_not_hold(
    pg: str, monkeypatch: MP, capsys: Cap, change: list[str], restore: list[str], lines: str
) -> None:
    with _changed(pg, change, restore):
        status, out = _check_on_cv_ro(pg, monkeypatch, capsys)
    assert status == 1 and lines in out, out
    assert f"RESULT: FAIL ({lines.count('FAIL ')} FAIL)" in out
    status, out = _check_on_cv_ro(pg, monkeypatch, capsys)  # restored
    assert status == 0 and "RESULT: PASS (0 FAIL)" in out, out


def test_a_guard_trigger_that_always_fires_passes(pg: str, monkeypatch: MP, capsys: Cap) -> None:
    change = ["ALTER TABLE audit_log ENABLE ALWAYS TRIGGER trg_audit_append"]
    restore = ["ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append"]
    with _changed(pg, change, restore):
        status, out = _check_on_cv_ro(pg, monkeypatch, capsys)
    assert status == 0 and "PASS triggers" in out, out


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
