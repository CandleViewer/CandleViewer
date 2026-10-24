"""Integration (E42-Q01, #962): the audit-writer seeds of slice B4b on a migrated Postgres 16:
AUDIT-SECRET-MARKER, AUDIT-CONCURRENT, BACKUP-TAMPERED and BACKUP-THEN-REVOKED.

Each seed passes its own check, a second seed writes no row, and a database not named for tests is
refused, before a table is touched: the refused database here is empty, so a seed that went on
would fail on a missing table, not with `FixtureRefused`. Audit rows can never be removed (C-5.7)
and each backup handle is a world of its own, so each test runs in a database cloned from the
migrated `test` one and named for tests. The marker entry is read back as the Owner's raw read and
the export's batch read it, and neither holds the marker; the two backups' records are read back
with the app's own evidence reader, as the restore guard reads them. Needs Docker (testcontainers);
CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.ext.asyncio import create_async_engine

from candleviewer.admin.backups.evidence import AuditRunEvidence
from candleviewer.admin.backups.ports import RunRecord
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.fixtures.admin.backup_worlds import (
    BOUND_DIGEST,
    check_backup_tampered,
    check_backup_then_revoked,
    seed_backup_tampered,
    seed_backup_then_revoked,
)
from tests.fixtures.admin.concurrent_rows import ROUNDS, check_concurrent_rows, seed_concurrent_rows
from tests.fixtures.admin.handles import BACKUP_TAMPERED, BACKUP_THEN_REVOKED
from tests.fixtures.admin.secret_marker import (
    ACTION,
    ACTOR,
    MARKER,
    check_secret_marker,
    seed_secret_marker,
)
from tests.fixtures.admin.seed import (
    FixtureCheckError,
    FixtureRefused,
    backup_row,
    check_admin_world,
    check_backups,
    seed_admin_world,
    seed_backups,
)
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; database and login `test`
_NOW = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


def _rows(dsn: str, query: str, *params: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_sync(dsn)) as conn:
        return conn.execute(query, params).fetchall()


def _files(directory: Path) -> list[Path]:
    return sorted(directory.iterdir())


def _create(pg_dsn: str, name: str, template: str | None = None) -> str:
    """The asyncpg DSN of a new database `name` on the container, cloned from `template` when
    given. A template has no other connection while it is copied, so this connects through
    `postgres`."""
    server = pg_dsn.rsplit("/", 1)[0]
    statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
    if template is not None:
        statement += sql.SQL(" TEMPLATE {}").format(sql.Identifier(template))
    with psycopg.connect(f"{_sync(server)}/postgres", autocommit=True) as conn:
        conn.execute(statement)
    return f"{server}/{name}"


@pytest.fixture
def fresh(pg_dsn: str) -> str:
    """A migrated database of the test's own, named for tests."""
    return _create(pg_dsn, f"b4b_{uuid.uuid4().hex[:12]}_test", template=pg_dsn.rsplit("/", 1)[1])


@pytest.fixture
def other_dsn(pg_dsn: str) -> str:
    """An empty database whose name does not mark it for tests."""
    return _create(pg_dsn, f"b4b_{uuid.uuid4().hex[:12]}")


_LOG = "SELECT count(*) FROM audit_log"
#: The audit rows, and each backup, grant and role row with its version: `xmin` changes when a row
#: is rewritten, even to equal values. Each aggregate is ordered by its own text.
_STATE = (
    "SELECT (SELECT count(*) FROM audit_log),"
    " (SELECT array_agg(t ORDER BY t) FROM (SELECT id::text || xmin::text AS t FROM backups) b),"
    " (SELECT array_agg(t ORDER BY t) FROM"
    "  (SELECT user_id::text || exchange_account_id::text || xmin::text AS t"
    "   FROM user_account_access) g),"
    " (SELECT array_agg(t ORDER BY t) FROM"
    "  (SELECT user_id::text || role_id::text || xmin::text AS t FROM user_roles) r)"
)


async def _in_world(dsn: str, *runs: Callable[[Any], Awaitable[object]]) -> None:
    """Each of `runs` on a connection of its own to `dsn`, in a transaction."""
    engine = create_async_engine(dsn)
    try:
        for run in runs:
            async with engine.begin() as conn:
                await run(conn)
    finally:
        await engine.dispose()


@asynccontextmanager
async def _evidence(dsn: str) -> AsyncIterator[AuditRunEvidence]:
    """The app's own reader of a backup's run records, over the real audit query service."""
    relational = SqlAlchemyRelationalRepository(dsn)
    query = AuditQueryService(SqlAlchemyAuditRepository(relational))
    try:
        yield AuditRunEvidence(query)
    finally:
        query.close()
        await relational.dispose()


async def test_the_secret_marker_is_stored_redacted_and_a_second_seed_writes_no_row(
    fresh: str, tmp_path: Path
) -> None:
    await seed_secret_marker(fresh, tmp_path)
    await check_secret_marker(fresh)
    await seed_secret_marker(fresh, tmp_path)
    assert await asyncio.to_thread(_rows, fresh, _LOG) == [(1,)]


async def test_the_owners_read_and_the_exports_batch_of_the_marker_entry_hold_no_marker(
    fresh: str, tmp_path: Path
) -> None:
    await seed_secret_marker(fresh, tmp_path)
    relational = SqlAlchemyRelationalRepository(fresh)
    repository = SqlAlchemyAuditRepository(relational)
    query = AuditQueryService(repository)
    try:
        page = await query.query(restrict_to_actor=None, owner=True, raw=True, actions=[ACTION])
        [entry] = page.items
        batch = await repository.fetch_export_batch(after_id=0, to_id=entry.id, limit=10)
    finally:
        query.close()
        await relational.dispose()
    assert entry.actor_username == ACTOR
    assert entry.detail == {
        "before": {"api_key": REDACTION_MARKER},
        "after": {"api_secret": REDACTION_MARKER},
    }
    assert (MARKER in page.model_dump_json(), MARKER in repr(batch), len(batch)) == (
        False,
        False,
        1,
    )


async def test_concurrent_rows_pass_their_check_and_a_second_seed_writes_none(
    fresh: str,
) -> None:
    first, last = await seed_concurrent_rows(fresh, now=_NOW)
    await check_concurrent_rows(fresh)
    assert await seed_concurrent_rows(fresh, now=_NOW) == (first, last)
    assert await asyncio.to_thread(_rows, fresh, _LOG) == [(2 * ROUNDS,)]


async def test_the_tampered_records_digest_is_not_the_rows_and_the_backup_is_a_world_of_its_own(
    fresh: str, tmp_path: Path
) -> None:
    await seed_backup_tampered(fresh, tmp_path, now=_NOW)
    await check_backup_tampered(fresh)
    async with _evidence(fresh) as evidence:
        bound = await evidence.bound_digest(BACKUP_TAMPERED.id)
    assert bound == BOUND_DIGEST != BACKUP_TAMPERED.checksum_sha256
    before = await asyncio.to_thread(_rows, fresh, _STATE)
    await seed_backup_tampered(fresh, tmp_path, now=_NOW)
    assert await asyncio.to_thread(_rows, fresh, _STATE) == before
    with pytest.raises(FixtureCheckError, match="not the fixture's"):  # B2's check is strict
        await _in_world(fresh, check_backups)


async def test_the_revoked_backups_records_bind_its_digest_and_covers_to_and_revocations_follow(
    fresh: str, tmp_path: Path
) -> None:
    await _in_world(fresh, lambda conn: seed_admin_world(conn, now=_NOW))
    await seed_backup_then_revoked(fresh, tmp_path, now=_NOW)
    await check_backup_then_revoked(fresh)
    async with _evidence(fresh) as evidence:
        record = await evidence.run_record(BACKUP_THEN_REVOKED.id)
        verification = await evidence.verification(BACKUP_THEN_REVOKED.id)
    covers_to = backup_row(BACKUP_THEN_REVOKED, _NOW)["finished_at"]
    assert record == RunRecord(BACKUP_THEN_REVOKED.checksum_sha256, covers_to)
    assert verification.passed
    before = await asyncio.to_thread(_rows, fresh, _STATE)
    await seed_backup_then_revoked(fresh, tmp_path, now=_NOW)
    assert await asyncio.to_thread(_rows, fresh, _STATE) == before
    with pytest.raises(FixtureCheckError, match=r"OWNER-2: roles are .*MGR-M: a grant is"):
        await _in_world(fresh, lambda conn: check_admin_world(conn, now=_NOW))  # by design


async def test_a_backup_world_refuses_a_catalogue_that_holds_seed_backups_rows_and_writes_nothing(
    fresh: str, tmp_path: Path
) -> None:
    await _in_world(fresh, lambda conn: seed_backups(conn, now=_NOW))
    before = await asyncio.to_thread(_rows, fresh, _STATE)
    with pytest.raises(FixtureCheckError, match="shares no database with another backup"):
        await seed_backup_tampered(fresh, tmp_path, now=_NOW)
    assert await asyncio.to_thread(_rows, fresh, _STATE) == before  # no record, no row touched
    await _in_world(fresh, check_backups)  # and B2's strict check still holds


_REFUSED: dict[str, Callable[[str, Path], Awaitable[object]]] = {
    "seed the marker": lambda dsn, wal: seed_secret_marker(dsn, wal),
    "check the marker": lambda dsn, wal: check_secret_marker(dsn),
    "seed the concurrent rows": lambda dsn, wal: seed_concurrent_rows(dsn, now=_NOW),
    "check the concurrent rows": lambda dsn, wal: check_concurrent_rows(dsn),
    "seed the tampered backup": lambda dsn, wal: seed_backup_tampered(dsn, wal, now=_NOW),
    "check the tampered backup": lambda dsn, wal: check_backup_tampered(dsn),
    "seed the revoked backup": lambda dsn, wal: seed_backup_then_revoked(dsn, wal, now=_NOW),
    "check the revoked backup": lambda dsn, wal: check_backup_then_revoked(dsn),
}


@pytest.mark.parametrize("run", list(_REFUSED))
async def test_a_database_not_named_for_tests_is_refused_before_a_table_is_touched(
    other_dsn: str, tmp_path: Path, run: str
) -> None:
    with pytest.raises(FixtureRefused):
        await _REFUSED[run](other_dsn, tmp_path)
    assert await asyncio.to_thread(_files, tmp_path) == []  # no WAL file either
