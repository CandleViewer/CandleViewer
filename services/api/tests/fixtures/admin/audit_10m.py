"""The 10 M-row audit dataset (E42-Q01, #962): the plan's AUDIT-10M handle.

Ten million synthetic `audit_log` rows for the search budget (AD-S04-01), generated inside Postgres
by E42-K01's set-based SQL (`bench/audit_index/ci_spike.py`, imported, never copied), so the
dataset is never stored (#962's technical notes). What is deterministic: the row count; the time
span (from 2026-01-01, 365 days, evenly spaced); the 50 users (`user_00` to `user_49`); and, after
`setseed`, each row's action, severity, outcome, environment and state, on the same Postgres
version. `record_id`, `session_id` and `request_id` come from `gen_random_uuid()`, so they differ
on every load; the plan's cases never name one.

`chained=True` (the default) inserts through the chain trigger, so a verify over the rows passes;
E42-K01 measured 0.18 to 0.27 ms a row that way. `chained=False` is K01's bulk load: the trigger off
for the load only (the database's superuser, as the test container's), placeholder hashes, so a
verify reports the first row; use it for the search budget alone. Audit rows can never be removed
(C-5.7), so the loader opens only a database named for tests (`seed.is_test_database`); anywhere
else it raises `FixtureRefused` before reading or writing a row. No test loads 10 M rows.
"""

from __future__ import annotations

from typing import Any, Final

import psycopg

from bench.audit_index.ci_spike import generate_rows_sql, seed_users_sql
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused, is_test_database

ROWS: Final = 10_000_000
#: Rows per `INSERT ... SELECT`; K01 loaded 1 M at a time, smaller keeps each statement short.
BATCH: Final = 250_000
#: Postgres `setseed` takes a value in [-1, 1].
SEED: Final = 0.42
#: The dataset's rows: K01's actor labels, `user_00` to `user_49`, which no other handle writes.
_OWN: Final = "SELECT count(*) FROM audit_log WHERE actor_label ~ '^user_[0-9]{2}$'"


def batches(rows: int = ROWS, size: int = BATCH) -> list[tuple[int, int]]:
    """Inclusive `(first, last)` ranges covering 1 to `rows` once each, in order."""
    if rows < 1 or size < 1:
        raise ValueError("rows and the batch size must be at least 1")
    return [(first, min(first + size - 1, rows)) for first in range(1, rows + 1, size)]


def statements(
    rows: int = ROWS, size: int = BATCH, *, seed: float = SEED, chained: bool = True
) -> list[str]:
    """The load's SQL, in order: the seed, the users the rows reference, one insert per batch."""
    if not -1.0 <= seed <= 1.0:
        raise ValueError("Postgres setseed takes a value in [-1, 1]")
    inserts = [generate_rows_sql(a, b, rows, chained) for a, b in batches(rows, size)]
    return [f"SELECT setseed({seed!r})", seed_users_sql(), *inserts]


def _connect(dsn: str) -> psycopg.Connection[Any]:
    """A connection to a database named for tests, or `FixtureRefused` before any read."""
    conn = psycopg.connect(dsn, autocommit=True)
    row = conn.execute("SELECT current_database()").fetchone()
    name = "" if row is None else str(row[0])
    if not is_test_database(name):
        conn.close()
        raise FixtureRefused(f"refusing database {name!r}: not a test database")
    return conn


def _own_rows(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute(_OWN).fetchone()
    return 0 if row is None else int(row[0])


def load_audit_10m(
    dsn: str, rows: int = ROWS, size: int = BATCH, *, seed: float = SEED, chained: bool = True
) -> int:
    """Load the dataset into a test database over psycopg `dsn`; the dataset's rows after. A
    second run finds them all and loads nothing. `setseed` holds for one session, so the load
    runs on one connection."""
    sql = statements(rows, size, seed=seed, chained=chained)
    with _connect(dsn) as conn:
        present = _own_rows(conn)
        if present == rows:
            return rows
        if present:
            raise FixtureCheckError(
                f"AUDIT-10M: {present} of its {rows} rows are present; audit rows can never be "
                "removed (C-5.7), so load it into a fresh test database"
            )
        if not chained:
            conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_chain")
        try:
            for statement in sql:
                conn.execute(statement)
        finally:
            if not chained:
                conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_chain")
        count = _own_rows(conn)
    if count != rows:
        raise FixtureCheckError(f"AUDIT-10M: audit_log holds {count} of its rows, not {rows}")
    return count
