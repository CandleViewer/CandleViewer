"""Integration (#3093): a crash between a DDL file's statements and its `_cv_migrations` record.

The runner records a file after its last statement and QuestDB 8.1.1 has no transactional DDL, so a
process that dies in between leaves a file's effects without its record. The next run must finish
the file with no error and must not drop a table that already has the shape `0004` re-creates:
`bars_*` rows are derived but costly to rebuild. Real engine (the `questdb_container` of
`test_questdb_hot_tier.py`): the refusals are QuestDB's own, `table_columns()` lags an ALTER and
names the types the guard compares. The crash sweep over every statement is the in-memory
`tests/unit/storage/questdb/test_runner_resume.py`.

Row counts use `conn.fetch`, never `conn.fetchval`: with asyncpg 0.31 a `fetchval` leaves the
connection so that the next DDL `execute` on it raises `AttributeError`, the statement having run.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import asyncpg
import pytest
from structlog.testing import capture_logs

from candleviewer.storage.questdb.runner import (
    assert_no_schema_drift,
    parse_ddl_file_statements,
    run_migrations,
    wait_for_wal_apply,
)
from tests.integration.storage.test_questdb_hot_tier import (
    DDL_DIR,
    _AsyncpgExecutor,
    _connect,
    questdb_container,  # noqa: F401 -- pytest fixture re-export
)

pytestmark = pytest.mark.integration

_FILES = sorted(DDL_DIR.glob("*.sql"))
_NAMES = [path.name for path in _FILES]
_BARS = [f"bars_{kind}" for kind in ("time", "tick", "volume", "range", "renko", "delta")]
#: One row for each of the six fixed tables, built once from the closed list above.
_BAR_ROW = {
    table: f"INSERT INTO {table} "  # noqa: S608  # nosec B608 - a name from the fixed list above
    '(ts, symbol, bar_param, generation, "index", open, high, low, close) '
    "VALUES (now(), 'BTCUSDT', '1m', 0, 1, 1.0, 2.0, 0.5, 1.5)"
    for table in _BARS
}


def _statements_through(files: int) -> int:
    return sum(len(parse_ddl_file_statements(path)) for path in _FILES[:files])


class _DiesAfter:
    """The process or the connection dies after `n` DDL statements: the next `execute` (a DDL
    statement, or a record's INSERT) never reaches QuestDB."""

    def __init__(self, inner: _AsyncpgExecutor, n: int) -> None:
        self._inner, self._left = inner, n

    async def execute(self, sql: str, *args: object) -> None:
        head = sql.lstrip().upper()
        if not head.startswith("CREATE TABLE IF NOT EXISTS _CV_MIGRATIONS"):  # the bootstrap
            if self._left == 0:
                raise ConnectionResetError("the migrate process died here")
            if not head.startswith("INSERT INTO _CV_MIGRATIONS"):
                self._left -= 1
        await self._inner.execute(sql, *args)

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        return await self._inner.fetch(sql, *args)


async def _rows(conn: asyncpg.Connection, table: str) -> int:
    await wait_for_wal_apply(_AsyncpgExecutor(conn), table)
    query = f"SELECT count() AS n FROM {table}"  # noqa: S608  # nosec B608 - test literal (#3093)
    return int((await conn.fetch(query))[0]["n"])


async def _bars_with_0004_shape(conn: asyncpg.Connection) -> list[str]:
    live = {row["table_name"] for row in await conn.fetch("SELECT table_name FROM tables()")}
    shaped = []
    for table in (name for name in _BARS if name in live):
        await wait_for_wal_apply(_AsyncpgExecutor(conn), table)
        query = f"SELECT \"column\" FROM table_columns('{table}')"  # noqa: S608  # nosec B608 - test literal (#3093)
        if {"generation", "index"} <= {row["column"] for row in await conn.fetch(query)}:
            shaped.append(table)
    return shaped


async def test_a_rerun_of_0004_without_its_record_keeps_the_populated_bars_tables(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
    tmp_path: Path,
) -> None:
    """The owner's data-loss path (#3093, 2026-10-17): 0004 and 0005 ran, their records were never
    written and the six `bars_*` tables hold bars. Before the fix the re-run dropped them."""
    host, pg_port, _ = questdb_container
    conn = await _connect(host, pg_port)
    try:
        executor = _AsyncpgExecutor(conn)
        for path in _FILES[:3]:
            shutil.copy(path, tmp_path / path.name)
        assert len(await run_migrations(executor, tmp_path)) == 3
        for name in _NAMES[3:5]:
            for statement in parse_ddl_file_statements(DDL_DIR / name):
                await conn.execute(statement)
        for table in _BARS:
            await conn.execute(_BAR_ROW[table])
        assert [await _rows(conn, table) for table in _BARS] == [1] * 6

        with capture_logs() as logs:
            applied = await run_migrations(executor, DDL_DIR)

        assert applied == _NAMES[3:]
        assert [await _rows(conn, table) for table in _BARS] == [1] * 6
        await assert_no_schema_drift(executor, DDL_DIR)
        assert await run_migrations(executor, DDL_DIR) == []
        resumed = [log["filename"] for log in logs if log["event"] == "questdb_migration_resumed"]
        assert resumed == _NAMES[3:5]  # 0004 and 0005 were finished, 0006 ran from scratch
    finally:
        await conn.close()


@pytest.mark.parametrize(
    ("statements_before_the_crash", "bars_kept"),
    [
        (_statements_through(2) + 6, 0),
        (_statements_through(3) + 1, 0),
        (_statements_through(3) + 4, 2),
        (_statements_through(4), 6),
        (_statements_through(6), 6),
    ],
    ids=[
        "inside-0003",
        "0004-after-a-drop",
        "inside-0004",
        "0004-before-its-record",
        "0006-before-its-record",
    ],
)
async def test_a_run_that_dies_between_statements_resumes_and_keeps_its_rows(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
    statements_before_the_crash: int,
    bars_kept: int,
) -> None:
    host, pg_port, _ = questdb_container
    conn = await _connect(host, pg_port)
    try:
        executor = _AsyncpgExecutor(conn)
        with pytest.raises(ConnectionResetError):
            await run_migrations(_DiesAfter(executor, statements_before_the_crash), DDL_DIR)
        kept = await _bars_with_0004_shape(conn)  # rows written after the crash, into each one
        assert len(kept) == bars_kept
        for table in kept:
            await conn.execute(_BAR_ROW[table])

        await run_migrations(executor, DDL_DIR)  # no `column ... already exists`

        assert [await _rows(conn, table) for table in kept] == [1] * bars_kept
        await assert_no_schema_drift(executor, DDL_DIR)
        assert await run_migrations(executor, DDL_DIR) == []
    finally:
        await conn.close()
