"""The corrupted audit chain (E42-Q01, #962): the plan's AUDIT-CORRUPT handle.

A test-only chain with one of its own entries altered behind it, so `POST /admin/audit/verify`
reports that entry as `first_bad_id` (#962's AC). The entries go through the real append path, so
the trigger chains them. The alteration needs the database's superuser, as an attacker holding
the owner role would: the test container's user. It loads only into a database named for tests
(`seed.is_test_database`); anywhere else it raises `FixtureRefused` before reading or writing a row.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final, Protocol

import psycopg

from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused, is_test_database

#: The fixture's own entries, told apart from the app's by their actor label.
ENTRIES: Final = 7
ACTOR: Final = "fixture-chain"
ACTION: Final = "orders.submit"
#: The entry altered, by its position among the fixture's own entries (0 is the first).
VICTIM_POSITION: Final = 3
FORGED: Final = "fixture: altered behind the chain"


class _Writer(Protocol):  # `AuditWriter`'s append path
    async def emit(self, action: str, **fields: Any) -> None: ...

    async def flush(self, timeout_s: float) -> Any: ...


def _connect(dsn: str) -> psycopg.Connection[Any]:
    """A connection to a database named for tests, or `FixtureRefused` before any read."""
    conn = psycopg.connect(dsn, autocommit=True)
    row = conn.execute("SELECT current_database()").fetchone()
    name = "" if row is None else str(row[0])
    if not is_test_database(name):
        conn.close()
        raise FixtureRefused(f"refusing database {name!r}: not a test database")
    return conn


def _own_ids(dsn: str) -> list[int]:
    with _connect(dsn) as conn:
        rows = conn.execute("SELECT id FROM audit_log WHERE actor_label = %s ORDER BY id", (ACTOR,))
        return [int(r[0]) for r in rows.fetchall()]


def _alter(dsn: str) -> int:
    """Alter the victim behind the chain unless it already is; its id."""
    with _connect(dsn) as conn:
        rows = conn.execute("SELECT id FROM audit_log WHERE actor_label = %s ORDER BY id", (ACTOR,))
        ids = [int(r[0]) for r in rows.fetchall()]
        if len(ids) != ENTRIES:
            raise FixtureCheckError(f"the chain holds {len(ids)} fixture entries, not {ENTRIES}")
        victim = ids[VICTIM_POSITION]
        row = conn.execute("SELECT reason FROM audit_log WHERE id = %s", (victim,)).fetchone()
        if row is None or row[0] != FORGED:
            conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_append")
            try:
                conn.execute("UPDATE audit_log SET reason = %s WHERE id = %s", (FORGED, victim))
            finally:
                conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append")
        return victim


async def seed_corrupted_chain(writer: _Writer, dsn: str) -> int:
    """The fixture's entries through `writer`, then the victim altered behind the chain: its id,
    the `first_bad_id` a verify must report. `dsn` is a psycopg one, for the superuser's
    alteration. A second run writes no entry and alters nothing, and answers the same id."""
    present = await asyncio.to_thread(_own_ids, dsn)
    for i in range(len(present), ENTRIES):
        await writer.emit(ACTION, actor_label=ACTOR, object_id=f"fixture-{i}")
    await writer.flush(60)
    return await asyncio.to_thread(_alter, dsn)
