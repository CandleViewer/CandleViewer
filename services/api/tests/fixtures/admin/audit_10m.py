"""The 10 M-row audit dataset (E42-Q01, #962): the plan's AUDIT-10M handle.

Ten million synthetic `audit_log` rows for the search budget (AD-S04-01), generated inside Postgres
by E42-K01's set-based SQL (`bench/audit_index/ci_spike.py`, imported, never copied), so the
dataset is never stored (#962's technical notes). What is deterministic: the row count; the time
span (from 2026-01-01, 365 days, evenly spaced); the 50 users (`user_00` to `user_49`); and, after
`setseed`, each row's action, severity, outcome, environment and state, on the same Postgres
version. `record_id`, `session_id` and `request_id` come from `gen_random_uuid()`, so they differ
on every load; the plan's cases never name one.

`chained=True` (the default) inserts through the chain trigger, so a verify over the rows passes;
E42-K01 measured 0.18 to 0.27 ms a row that way. `chained=False` is K01's bulk load with the
secondary indexes kept: the trigger off for the load only, inside one transaction with the inserts
and a read of its state before DISABLE and after ENABLE, so an error, a cancellation or a killed
loader rolls the trigger state back with the rows. It needs the table's owner, and writes
placeholder hashes (`prev_hash` is 64 zeros on every row, as K01's SQL writes it), so a verify
reports the first row; use it for the search budget alone. Audit rows can never be removed (C-5.7),
so the loader opens only a database named for tests (`seed.is_test_database`); anywhere else it
raises `FixtureRefused` before reading or writing a row. No test loads 10 M rows.
"""

from __future__ import annotations

from typing import Any, Final

import psycopg

from bench.audit_index.ci_spike import generate_rows_sql, seed_users_sql
from tests.fixtures.admin.seed import FixtureCheckError, connect_test_database

ROWS: Final = 10_000_000
#: Rows per `INSERT ... SELECT`; K01 loaded 1 M at a time, smaller keeps each statement short.
BATCH: Final = 250_000
#: Postgres `setseed` takes a value in [-1, 1].
SEED: Final = 0.42
#: The dataset's actor labels, K01's `user_00` to `user_49`. No other seed may use this label shape:
#: a row so labelled is counted as the dataset's.
OWN_LABEL: Final = "^user_[0-4][0-9]$"
#: One loader at a time. Outside `int4`, so never the chain's own key (`hashtext('audit_log')`).
_LOCK: Final = 962 << 32
_SETSEED: Final = "SELECT setseed(%s)"
#: The dataset's rows, and how many of them hold the genesis `prev_hash` (64 zeros).
_OWN: Final = (
    "SELECT count(*), count(*) FILTER (WHERE prev_hash = repeat('0', 64)) FROM audit_log"
    " WHERE actor_label ~ %s"
)
_GUARD: Final = (
    "SELECT tgenabled::text FROM pg_trigger"
    " WHERE tgrelid = 'audit_log'::regclass AND tgname = 'trg_audit_chain'"
)
_DISABLE: Final = "ALTER TABLE audit_log DISABLE TRIGGER trg_audit_chain"
_ENABLE: Final = "ALTER TABLE audit_log ENABLE TRIGGER trg_audit_chain"


def batches(rows: int = ROWS, size: int = BATCH) -> list[tuple[int, int]]:
    """Inclusive `(first, last)` ranges covering 0 to `rows - 1` once each, in order: K01 numbers
    its rows `g` from 0, so the data is K01's."""
    if rows < 1 or size < 1:
        raise ValueError("rows and the batch size must be at least 1")
    return [(first, min(first + size, rows) - 1) for first in range(0, rows, size)]


def statements(rows: int = ROWS, size: int = BATCH, *, chained: bool = True) -> list[str]:
    """The load's SQL, in order: the users the rows reference, one insert per batch."""
    inserts = [generate_rows_sql(a, b, rows, chained) for a, b in batches(rows, size)]
    return [seed_users_sql(), *inserts]


def _own_rows(conn: psycopg.Connection[Any]) -> tuple[int, int]:
    row = conn.execute(_OWN, (OWN_LABEL,)).fetchone()
    return (0, 0) if row is None else (int(row[0]), int(row[1]))


def _require_chain_trigger(conn: psycopg.Connection[Any], *, rolled_back: bool = False) -> None:
    """`FixtureCheckError` unless the chain trigger is enabled (`tgenabled = 'O'`): one found off
    is reported, never repaired here. `rolled_back`: the read follows the bulk load's own ENABLE,
    inside its transaction, which this error rolls back, restoring the trigger as it was."""
    guard = conn.execute(_GUARD).fetchone()
    if guard is None or guard[0] != "O":
        recovery = (
            "the load rolled back with its rows, so the trigger is as it was before it"
            if rolled_back
            else "enable it with: ALTER TABLE audit_log ENABLE TRIGGER trg_audit_chain"
        )
        raise FixtureCheckError(f"trg_audit_chain is not enabled on audit_log; {recovery}")


def _require_mode(present: int, genesis: int, chained: bool) -> None:
    """`FixtureCheckError` when the rows present were loaded in the other mode. A bulk set holds the
    genesis `prev_hash` on every row; a chained set on at most its first, and only when the chain
    was empty then: more than one genesis row is a bulk set, fewer than all is a chained one. A
    single row tells nothing."""
    other = (genesis > 1) if chained else (genesis < present)
    if other:
        loaded, asked = ("bulk", "chained") if chained else ("chained", "bulk")
        raise FixtureCheckError(
            f"AUDIT-10M: its {present} rows were loaded {loaded}, and this call asks for {asked}; "
            "audit rows can never be removed (C-5.7), so load the other mode into a fresh "
            "test database"
        )


def _run(conn: psycopg.Connection[Any], seed: float, sql: list[str]) -> None:
    conn.execute(_SETSEED, (seed,))  # bound, never formatted into the text
    for statement in sql:
        conn.execute(statement)


def load_audit_10m(
    dsn: str, rows: int = ROWS, size: int = BATCH, *, seed: float = SEED, chained: bool = True
) -> int:
    """Load the dataset into a test database over psycopg `dsn`; the dataset's rows after. A
    second run, in the mode of the first, finds them all and loads nothing; the other mode is
    refused. The load runs on one connection (`setseed` holds for one session) that holds an
    advisory lock, so two loaders never both load; `ANALYZE audit_log` follows it. The chain
    trigger is read before the load and after it, in the bulk load's own transaction, and every
    run ends with it enabled, or `FixtureCheckError` (a bulk load then commits nothing)."""
    if not -1.0 <= seed <= 1.0:
        raise ValueError("Postgres setseed takes a value in [-1, 1]")
    sql = statements(rows, size, chained=chained)
    with connect_test_database(dsn) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK,))  # held to the connection's close
        present, genesis = _own_rows(conn)
        if present == rows:
            _require_chain_trigger(conn)
            _require_mode(present, genesis, chained)
            return rows
        if present:
            _require_chain_trigger(conn)  # a partial set is reported with the trigger's state first
            raise FixtureCheckError(
                f"AUDIT-10M: {present} of its {rows} rows are present; audit rows can never be "
                "removed (C-5.7), so load it into a fresh test database"
            )
        if chained:
            _require_chain_trigger(conn)
            _run(conn, seed, sql)  # each batch commits, holding the chain lock for its rows
            _require_chain_trigger(conn)
        else:
            with conn.transaction():  # an error, a cancellation or a kill rolls all of it back
                _require_chain_trigger(conn)  # read before DISABLE, in the same transaction
                conn.execute(_DISABLE)
                _run(conn, seed, sql)
                conn.execute(_ENABLE)
                _require_chain_trigger(conn, rolled_back=True)  # after ENABLE, before the commit
        conn.execute("ANALYZE audit_log")
        count, _ = _own_rows(conn)
    if count != rows:
        raise FixtureCheckError(f"AUDIT-10M: audit_log holds {count} of its rows, not {rows}")
    return count
