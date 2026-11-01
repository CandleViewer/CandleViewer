"""Idempotent QuestDB DDL runner keyed on `_cv_migrations` (E07-T03).

`docs/plan/21-database-schema.md` Sec.9.1: "QuestDB DDL lives in
`backend/db/questdb/NNNN_*.sql`, applied by a small idempotent runner keyed
on a `_cv_migrations` table inside QuestDB." Not run at API boot, and never by a
request handler: applying it becomes an explicit deploy step next to `alembic
upgrade head` (#3897; 20-architecture.md §6.2).

Also performs the column-drift guard: compares the live `tables()`/
`table_columns()` listing against the parsed DDL files and raises
`StorageSchemaDrift` rather than let a write path touch a mismatched shape.

`_cv_migrations` is a WAL table, so `applied_migrations` waits for QuestDB's apply job
(`wait_for_wal_apply`) before it reads: a stale read re-ran the newest file's DDL (#3064).

A run that dies between a file's statements and its record (QuestDB has no transactional DDL)
leaves effects with no record: `run_migrations` skips each `ADD COLUMN` (on a table with its DDL
upsert keys) and each re-created table's `DROP TABLE` whose effect is already live (#3093).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import structlog

from candleviewer.storage.errors import (
    StorageSchemaDrift,
    StorageWalNotApplied,
    WalNotAppliedReason,
)
from candleviewer.storage.questdb.ddl import (
    TableDef,
    add_column_target,
    drop_target,
    parse_ddl_dir,
    parse_ddl_file,
)
from candleviewer.storage.sql_identifiers import checked_identifier


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


_MIGRATIONS_TABLE = "_cv_migrations"

_CREATE_MIGRATIONS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} (
  ts          TIMESTAMP,
  filename    SYMBOL CAPACITY 256 CACHE,
  applied_at  TIMESTAMP
) TIMESTAMP(ts) PARTITION BY YEAR WAL
  DEDUP UPSERT KEYS(ts, filename);
"""


# Bind params are values, not identifiers, so the query is a fixed literal;
# the check keeps it in lockstep with `_MIGRATIONS_TABLE`.
_SELECT_APPLIED = "SELECT filename FROM _cv_migrations"
if checked_identifier(_MIGRATIONS_TABLE) not in _SELECT_APPLIED.split():  # pragma: no cover
    raise RuntimeError("_SELECT_APPLIED out of sync with _MIGRATIONS_TABLE")


class QuestDbExecutor(Protocol):
    """The minimal surface the runner needs from a PGWire connection —
    kept as a `Protocol` so tests can supply an in-memory fake instead of a
    real `asyncpg` connection (no docker available for unit tests)."""

    async def execute(self, sql: str, *args: object) -> None: ...

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]: ...


#: Wall clock for the whole wait, every poll included. Generous: the apply job is shared with every
#: other WAL table (a recorder backlog, a bulk import), so a busy server must not read as a failure.
WAL_APPLY_TIMEOUT_S = 30.0
#: Poll backoff: doubles from 20 ms and caps at 250 ms (a healthy apply takes a few milliseconds).
WAL_POLL_MIN_S = 0.02
WAL_POLL_MAX_S = 0.25
_TRUTHY = frozenset({"true", "t", "1"})

# A fixed literal: the table name is a bind value, never interpolated into the statement.
_SELECT_WAL_STATUS = "SELECT writerTxn, sequencerTxn, suspended FROM wal_tables() WHERE name = $1"


def _txns_behind(row: dict[str, object]) -> int | None:
    """Txns committed to the sequencer that the apply job has not applied yet (`None`: unreadable).

    `sequencerTxn <= 0` means nothing was ever committed, so nothing can be pending whatever
    `writerTxn` reports for an untouched table.
    """
    try:
        writer, sequencer = int(str(row["writerTxn"])), int(str(row["sequencerTxn"]))
    except (KeyError, ValueError):
        return None
    return max(0, sequencer - writer) if sequencer > 0 else 0


def _wal_not_applied(
    table: str, reason: WalNotAppliedReason, start: float, clock: Callable[[], float]
) -> StorageWalNotApplied:
    """One structured warning per failed wait (never per poll), then the typed error."""
    waited = clock() - start
    logger().warning(
        "questdb_wal_not_applied", table=table, reason=reason, waited_s=round(waited, 3)
    )
    return StorageWalNotApplied(
        f"questdb WAL apply of {table!r} did not catch up after {waited:.1f}s",
        reason=reason,
        table=table,
        waited_s=waited,
    )


async def wait_for_wal_apply(
    executor: QuestDbExecutor,
    table: str,
    *,
    timeout_s: float = WAL_APPLY_TIMEOUT_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Return once QuestDB's WAL apply job has caught up with `table`'s sequencer.

    A write to a WAL table is acknowledged once committed to the sequencer, and a SELECT sees it
    only after the apply job ran: `wal_tables()` shows `writerTxn` below `sequencerTxn` until then.
    A reader that must see an earlier write (the `_cv_migrations` record) waits here first. No
    `wal_tables()` row means not a WAL table: nothing to wait for.

    Bounded by `timeout_s` of wall clock, every poll included (a hung query too), with an
    exponential backoff. Raises `StorageWalNotApplied`: `timeout` at the bound, `suspended` at once
    (it never catches up; an operator must resume it), `unexpected_shape` at once when the row has
    no readable txns (fail closed: guessing "caught up" would reopen the race). Cancellation
    propagates.
    """
    start, delay = clock(), WAL_POLL_MIN_S
    try:
        async with asyncio.timeout(timeout_s) as bound:
            while True:
                rows = await executor.fetch(_SELECT_WAL_STATUS, table)
                if not rows:
                    return
                behind = _txns_behind(rows[0])
                if behind is None:
                    raise _wal_not_applied(table, "unexpected_shape", start, clock)
                if behind == 0:
                    return
                if str(rows[0].get("suspended")).lower() in _TRUTHY:
                    raise _wal_not_applied(table, "suspended", start, clock)
                if clock() - start >= timeout_s:
                    raise _wal_not_applied(table, "timeout", start, clock)
                await sleep(delay)
                delay = min(delay * 2, WAL_POLL_MAX_S)
    except TimeoutError:
        # Only the bound's own expiry is a `timeout`; a TimeoutError raised by the driver inside a
        # poll is a storage failure and keeps its cause.
        if not bound.expired():
            raise
        raise _wal_not_applied(table, "timeout", start, clock) from None


async def applied_migrations(
    executor: QuestDbExecutor,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> set[str]:
    """Filenames already recorded in `_cv_migrations`, read once the WAL apply has caught up.

    A stale read missed the newest record: the second pass re-ran its file and the plain
    `ADD COLUMN` failed with "column 'batch_index' already exists" (#3064).
    """
    await executor.execute(_CREATE_MIGRATIONS_TABLE)
    await wait_for_wal_apply(executor, _MIGRATIONS_TABLE, sleep=sleep)
    rows = await executor.fetch(_SELECT_APPLIED)
    return {str(row["filename"]) for row in rows}


# A fixed literal: the table name is a bind value, never interpolated into the statement.
_SELECT_TABLE = "SELECT table_name FROM tables() WHERE table_name = $1"


@dataclass(frozen=True, slots=True)
class _LiveTable:
    """A table as `table_columns()` shows it once its WAL apply has caught up."""

    columns: Mapping[str, str]  # lower-case column name -> TYPE
    upsert_keys: frozenset[str]


async def _live_table(
    executor: QuestDbExecutor, table: str, sleep: Callable[[float], Awaitable[None]]
) -> _LiveTable | None:
    """The live shape of `table`; `None` when it does not exist.

    The WAL apply is awaited first: `table_columns()` lags an accepted `ALTER` until the apply
    job ran (32 of 80 immediate reads on 8.1.1). It raises for a missing table, so `tables()`
    is asked before it.
    """
    await wait_for_wal_apply(executor, table, sleep=sleep)
    if not await executor.fetch(_SELECT_TABLE, table):
        return None
    # `checked_identifier` admits a plain identifier only, and `table` is parsed from our own DDL.
    query = f"SELECT \"column\", type, upsertKey FROM table_columns('{checked_identifier(table)}')"  # noqa: S608  # nosec B608 - checked identifier from trusted DDL files (#3093)
    rows = await executor.fetch(query)
    return _LiveTable(
        columns={str(row["column"]).lower(): str(row["type"]).upper() for row in rows},
        upsert_keys=frozenset(
            str(row["column"]).lower() for row in rows if str(row["upsertKey"]).lower() in _TRUTHY
        ),
    )


async def _effect_present(
    executor: QuestDbExecutor,
    stmt: str,
    recreated: Mapping[str, TableDef],
    first_keys: Mapping[str, frozenset[str]],
    sleep: Callable[[float], Awaitable[None]],
) -> dict[str, str] | None:
    """The log fields of `stmt` when a crashed earlier pass already applied its effect, else `None`.

    - `ADD COLUMN t.c TYPE` (8.1.1 rejects `IF NOT EXISTS`): skipped when `c` is on `t` with that
      type and `t` has the upsert keys its first `CREATE` declares (ILP sets none); a column of
      another type, or a table without those keys, is `StorageSchemaDrift`, never a skip. Those
      keys are the first `CREATE`'s because keys only grow: a future re-key that removes one makes
      a resumed `ADD COLUMN` on that table raise `StorageSchemaDrift` (exit 9), never skip.
    - `DROP TABLE t` of a table the same file re-creates (0004): skipped when `t` already has every
      column and upsert key of that re-creation, so the rows written since survive. A superset, not
      an equality: a later additive file must not make a lost record wipe the table. An old-shape
      table is still dropped and re-created (owner decision, path B, #1778 item R).

    `CREATE TABLE IF NOT EXISTS` and `DEDUP ENABLE UPSERT KEYS` can be repeated on 8.1.1, and every
    other statement runs as written (`test_runner_resume.py` fails for a statement with no rule).
    """
    if (add := add_column_target(stmt)) is not None:
        table, column, column_type = add
        live = await _live_table(executor, table, sleep)
        if live is None or column not in live.columns:
            return None
        if live.columns[column] != column_type:
            raise StorageSchemaDrift(
                f"questdb column {table}.{column} is {live.columns[column]}, "
                f"the DDL adds {column_type}"
            )
        if not first_keys.get(table, frozenset()) <= live.upsert_keys:
            raise StorageSchemaDrift(
                f"questdb table {table} lacks its DDL upsert keys (storage-migrate runbook, Run it)"
            )
        return {"kind": "add_column", "table": table, "column": column}
    if (dropped := drop_target(stmt)) is not None and dropped in recreated:
        live = await _live_table(executor, dropped, sleep)
        want = recreated[dropped]
        if (
            live is not None
            and set(want.columns) <= set(live.columns)
            and set(want.dedup_keys) <= live.upsert_keys
        ):
            return {"kind": "drop_table", "table": dropped}
    return None


async def run_migrations(
    executor: QuestDbExecutor,
    ddl_dir: Path,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[str]:
    """Apply every `NNNN_*.sql` file not already recorded, in filename order.

    Returns the list of filenames newly applied this call (empty on a
    no-op second run — the idempotency acceptance criterion). Each file's
    statements are executed individually (`CREATE TABLE IF NOT EXISTS` makes
    per-statement idempotency redundant but harmless) and the file is
    recorded in `_cv_migrations` only after every statement in it succeeds.
    A file a crash cut short is finished: a statement whose effect is already live is skipped
    and logged (`_effect_present`, after a WAL-apply wait that `sleep` also paces), and the
    file logs one `questdb_migration_resumed` warning (#3093).
    `sleep` is the backoff between WAL-apply polls of the record read (injectable for tests).
    """
    already = await applied_migrations(executor, sleep=sleep)
    newly_applied: list[str] = []
    # `Path.glob` on a small local `backend/db/questdb/` directory at boot is
    # not a hot-path blocking call in the C-2.18 sense; kept sync for
    # simplicity, run once per process start.
    sql_paths = sorted(ddl_dir.glob("*.sql"))  # noqa: ASYNC240
    tables = [table for path in sql_paths for table in parse_ddl_file(path)]  # once per run
    first_keys = {t.name: frozenset(t.dedup_keys) for t in reversed(tables)}  # earliest wins
    for sql_path in sql_paths:
        if sql_path.name in already:
            continue
        recreated = {t.name: t for t in tables if t.source_file == sql_path.name}
        skipped = 0
        for stmt in parse_ddl_file_statements(sql_path):
            effect = await _effect_present(executor, stmt, recreated, first_keys, sleep)
            if effect is not None:
                skipped += 1
                logger().info("questdb_statement_skipped", filename=sql_path.name, **effect)
                continue
            await executor.execute(stmt)
        if skipped:
            logger().warning(
                "questdb_migration_resumed", filename=sql_path.name, statements_skipped=skipped
            )
        await executor.execute(
            # `_MIGRATIONS_TABLE` is a module constant; `$1` binds the value.
            f"INSERT INTO {_MIGRATIONS_TABLE} (ts, filename, applied_at) "  # noqa: S608  # nosec B608 - module constant identifier, not user input
            "VALUES (now(), $1, now())",
            sql_path.name,
        )
        newly_applied.append(sql_path.name)
        logger().info("questdb_migration_applied", filename=sql_path.name)
    return newly_applied


def parse_ddl_file_statements(path: Path) -> list[str]:
    """Re-read a `.sql` file and return each `CREATE TABLE ... ;` statement
    verbatim (not the parsed `TableDef`) so the runner executes exactly what
    is on disk, byte for byte, rather than a reconstruction.

    `--` line comments are stripped before the paren-depth scan below: a
    comment containing an unbalanced `(` or `)` (e.g. a prose aside spanning
    lines) would otherwise desynchronise the depth counter and corrupt
    statement boundaries sent to QuestDB.
    """
    stripped_lines = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        idx = line.find("--")
        stripped_lines.append(line if idx == -1 else line[:idx] + "\n")
    text = "".join(stripped_lines)
    statements: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        current.append(char)
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth == 0:
            stmt = "".join(current).strip()
            if stmt and not stmt.startswith("--"):
                statements.append(stmt)
            current = []
    return statements


#: WAL tables apply `ALTER ... ADD COLUMN` asynchronously (the WAL apply job), so right after a
#: migration `table_columns()` can briefly lag the DDL that was accepted. The drift guard therefore
#: re-reads for a bounded time before declaring drift (a real mismatch still raises).
DRIFT_SETTLE_ATTEMPTS = 20
DRIFT_SETTLE_DELAY_S = 0.25


async def assert_no_schema_drift(
    executor: QuestDbExecutor,
    ddl_dir: Path,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Compare the live column set of every DDL-defined table against the
    parsed `.sql` files; raise `StorageSchemaDrift` on any mismatch that persists
    after the WAL-apply settle window.

    Uses `table_columns('<name>')`, QuestDB's introspection function, rather
    than string-matching `tables()` output.
    """
    expected = parse_ddl_dir(ddl_dir)
    for table in expected:
        # `table.name` comes from parsing our own trusted `.sql` files, never
        # from user input. `column` is a SQL keyword in QuestDB and must be
        # double-quoted when referenced as an identifier in the SELECT list.
        query = f"SELECT \"column\" FROM table_columns('{table.name}')"  # noqa: S608  # nosec B608 - table.name from trusted parsed DDL files, not user input
        expected_columns = set(table.columns)
        for attempt in range(DRIFT_SETTLE_ATTEMPTS):
            rows = await executor.fetch(query)
            live_columns = {str(row["column"]).lower() for row in rows}
            if live_columns == expected_columns:
                break
            if attempt < DRIFT_SETTLE_ATTEMPTS - 1:
                await sleep(DRIFT_SETTLE_DELAY_S)
        else:
            missing = expected_columns - live_columns
            extra = live_columns - expected_columns
            raise StorageSchemaDrift(
                f"questdb table {table.name!r} column drift: "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )


def expected_tables(ddl_dir: Path) -> list[TableDef]:
    """Convenience re-export for callers (e.g. the reader's query-builder
    lint tests) that want the parsed DDL without importing `ddl` directly."""
    return parse_ddl_dir(ddl_dir)
