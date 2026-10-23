"""The corrupted audit chain (E42-Q01, #962): the plan's AUDIT-CORRUPT handle.

A test-only chain with one of its own entries altered behind it, so `POST /admin/audit/verify`
reports that entry as `first_bad_id` (#962's AC). The entries go through the real append path, so
the trigger chains them, by a writer this module builds on the DSN it was given: no entry can land
in a database other than the one checked. The alteration needs the table's owner, as an attacker
holding the owner role would: the test container's user. It is permanent, as audit rows can never be
removed, so it loads only into a database named for tests (`seed.is_test_database`): anywhere else
it raises `FixtureRefused` before it writes a row, on the alteration's connection and on the
writer's pool alike.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

import psycopg

from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.fixtures.admin.seed import (
    FixtureCheckError,
    connect_test_database,
    refuse_unless_test_database,
)

#: The fixture's own entries, told apart from the app's by their actor label.
ENTRIES: Final = 7
ACTOR: Final = "fixture-chain"
ACTION: Final = "orders.submit"
#: The entry altered, by its position among the fixture's own entries (0 is the first).
VICTIM_POSITION: Final = 3
FORGED: Final = "fixture: altered behind the chain"
#: The writer's WAL file, in the directory the caller gives.
WAL_NAME: Final = "fixture-chain.wal"


def _entries(conn: psycopg.Connection[Any]) -> list[tuple[int, str | None]]:
    """The fixture's own entries in chain order: each one's id and reason."""
    rows = conn.execute(
        "SELECT id, reason FROM audit_log WHERE actor_label = %s ORDER BY id", (ACTOR,)
    )
    return [(int(row[0]), row[1]) for row in rows.fetchall()]


def _count(dsn: str) -> int:
    with connect_test_database(dsn) as conn:
        return len(_entries(conn))


def _alter(conn: psycopg.Connection[Any]) -> int:
    """Alter the victim behind the chain unless it already is, and check that the append-only
    trigger is enabled after; the victim's id. The trigger is off inside one transaction only, so
    a failure, a lost connection among them, rolls the whole alteration back."""
    entries = _entries(conn)
    if len(entries) != ENTRIES:
        raise FixtureCheckError(f"the chain holds {len(entries)} fixture entries, not {ENTRIES}")
    victim, reason = entries[VICTIM_POSITION]
    if reason != FORGED:
        with conn.transaction():
            conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_append")
            conn.execute("UPDATE audit_log SET reason = %s WHERE id = %s", (FORGED, victim))
            conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append")
    guard = conn.execute(
        "SELECT tgenabled::text FROM pg_trigger"
        " WHERE tgrelid = 'audit_log'::regclass AND tgname = 'trg_audit_append'"
    ).fetchone()
    if guard is None or guard[0] != "O":  # 'O': enabled; a leaked 'D' is reported, not hidden
        raise FixtureCheckError("trg_audit_append is not enabled on audit_log")
    return victim


def _alter_in(dsn: str) -> int:
    with connect_test_database(dsn) as conn:
        return _alter(conn)


async def _append(dsn: str, wal_dir: Path, positions: Iterable[int]) -> None:
    """The entries at `positions` through a writer on `dsn`, whose own pool is checked first: it
    is the pool the rows go through, so the check holds whatever else `dsn` reached."""
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        async with relational.engine.connect() as conn:
            await refuse_unless_test_database(conn)
        writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(wal_dir / WAL_NAME))
        try:
            await writer.start()
            for i in positions:
                await writer.emit(ACTION, actor_label=ACTOR, object_id=f"fixture-{i}")
            await writer.flush(60)
        finally:
            await writer.stop(5)
    finally:
        await relational.dispose()


async def seed_corrupted_chain(dsn: str, wal_dir: Path) -> int:
    """The fixture's entries, then the victim altered behind the chain: its id, the `first_bad_id`
    a verify must report. `dsn` is the SQLAlchemy asyncpg URL of a migrated test database, as the
    suites' `pg_dsn`; the entries go through a writer built here, its WAL in `wal_dir`. A second
    run writes no entry and alters nothing, and answers the same id."""
    sync = dsn.replace("postgresql+asyncpg", "postgresql")
    present = await asyncio.to_thread(_count, sync)
    if present < ENTRIES:
        await _append(dsn, wal_dir, range(present, ENTRIES))
    return await asyncio.to_thread(_alter_in, sync)
