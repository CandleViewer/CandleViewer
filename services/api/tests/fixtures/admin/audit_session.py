"""The pool and the audit writer the later admin seeds write through (E42-Q01, #962).

`checked_pool` opens a pool on the DSN it is given and reads the database's name first: a database
not named for tests is `FixtureRefused` before any statement but that read, so no row is read or
written there. `audit_session` builds the real `AuditWriter` over that pool, as `corrupt_chain`
does, so an entry can land only in the database that was checked. `emit_at` appends a record stamped
at a given instant, by the writer's own `build()` (the redactor) and `ingest()`. `read_audit_db` is
the same refusal for a check's reads.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping

from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.fixtures.admin.seed import refuse_unless_test_database


@asynccontextmanager
async def checked_pool(dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """A pool on `dsn` whose database is named for tests, disposed on exit."""
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        async with relational.engine.connect() as conn:
            await refuse_unless_test_database(conn)
        yield relational
    finally:
        await relational.dispose()


@asynccontextmanager
async def audit_session(
    dsn: str, wal_path: Path
) -> AsyncIterator[tuple[SqlAlchemyRelationalRepository, AuditWriter]]:
    """The checked pool and a started writer over it: flushed on a clean exit, always stopped."""
    async with checked_pool(dsn) as relational:
        writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(wal_path))
        try:
            await writer.start()
            yield relational, writer
            await writer.flush(60)
        finally:
            await writer.stop(5)


async def emit_at(writer: AuditWriter, action: str, at: datetime, **fields: Any) -> None:
    """One record as `emit` writes it, but stamped `at`: `build()` redacts, `ingest()` appends."""
    await writer.ingest_counted(writer.build(action, **fields).model_copy(update={"event_ts": at}))


async def read_audit_db(dsn: str, *reads: sa.Select[Any]) -> list[list[RowMapping]]:
    """The rows of each of `reads` on a checked pool; the name is read before any of them."""
    async with checked_pool(dsn) as relational, relational.engine.connect() as conn:
        return [list((await conn.execute(read)).mappings().all()) for read in reads]
