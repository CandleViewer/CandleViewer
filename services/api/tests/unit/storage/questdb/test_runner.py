"""Unit tests for `candleviewer.storage.questdb.runner` (E07-T03).

Covers DDL-runner idempotency (second run applies nothing) and the
column-drift guard, against a fake in-memory `QuestDbExecutor` — no docker
needed for these unit-level behaviours (integration tests exercise the real
engine separately).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.storage.errors import StorageSchemaDrift
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from candleviewer.storage.questdb.runner import (
    applied_migrations,
    assert_no_schema_drift,
    run_migrations,
)

DDL_DIR = Path(__file__).resolve().parents[6] / "backend" / "db" / "questdb"


async def _no_sleep(_: float) -> None:
    return None


class _FakeExecutor:
    """An in-memory stand-in for a QuestDB PGWire connection.

    Tracks executed DDL statements and a `_cv_migrations` row set in plain
    Python collections, and derives `table_columns()` responses from the
    same DDL files this module parses — so the drift test can perturb one
    column and see the guard fire.
    """

    def __init__(self) -> None:
        self.executed: list[str] = []
        self._migrations: set[str] = set()
        self._table_columns: dict[str, set[str]] = {
            t.name: set(t.columns) for t in parse_ddl_dir(DDL_DIR)
        }

    async def execute(self, sql: str, *args: object) -> None:
        self.executed.append(sql)
        if sql.strip().upper().startswith("INSERT INTO _CV_MIGRATIONS"):
            self._migrations.add(str(args[0]))

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        if "_cv_migrations" in sql:
            return [{"filename": name} for name in sorted(self._migrations)]
        if "table_columns" in sql:
            # sql looks like: SELECT column FROM table_columns('trades')
            name = sql.split("'")[1]
            return [{"column": col} for col in sorted(self._table_columns.get(name, set()))]
        return []


@pytest.mark.asyncio
async def test_run_migrations_applies_every_file_on_first_run() -> None:
    executor = _FakeExecutor()
    applied = await run_migrations(executor, DDL_DIR)
    assert applied == [
        "0001_core_tables.sql",
        "0002_footprint_cells.sql",
        "0003_bars_integrity_columns.sql",
        "0004_bars_key_by_index.sql",
        "0005_liquidations_batch_index.sql",
        "0006_orderbook_replay_columns.sql",
        "0007_heatmap_cells_column_fields.sql",
    ]


@pytest.mark.asyncio
async def test_run_migrations_second_run_applies_nothing() -> None:
    executor = _FakeExecutor()
    await run_migrations(executor, DDL_DIR)
    executor.executed.clear()
    applied_second = await run_migrations(executor, DDL_DIR)
    assert applied_second == []
    # No *data* table DDL re-issued on the idempotent second run (only the
    # always-idempotent `_cv_migrations` bootstrap statement, which itself
    # contains `CREATE TABLE`, runs again).
    assert not any(
        "CREATE TABLE" in stmt.upper() and "_CV_MIGRATIONS" not in stmt.upper()
        for stmt in executor.executed
    )


@pytest.mark.asyncio
async def test_applied_migrations_reflects_recorded_filenames() -> None:
    executor = _FakeExecutor()
    await run_migrations(executor, DDL_DIR)
    names = await applied_migrations(executor)
    assert names == {
        "0001_core_tables.sql",
        "0002_footprint_cells.sql",
        "0003_bars_integrity_columns.sql",
        "0004_bars_key_by_index.sql",
        "0005_liquidations_batch_index.sql",
        "0006_orderbook_replay_columns.sql",
        "0007_heatmap_cells_column_fields.sql",
    }


@pytest.mark.asyncio
async def test_assert_no_schema_drift_passes_when_columns_match() -> None:
    executor = _FakeExecutor()
    await assert_no_schema_drift(executor, DDL_DIR)  # no raise


@pytest.mark.asyncio
async def test_assert_no_schema_drift_raises_on_missing_column() -> None:
    executor = _FakeExecutor()
    executor._table_columns["trades"].discard("notional")
    with pytest.raises(StorageSchemaDrift, match="trades"):
        await assert_no_schema_drift(executor, DDL_DIR, sleep=_no_sleep)


@pytest.mark.asyncio
async def test_assert_no_schema_drift_raises_on_extra_column() -> None:
    executor = _FakeExecutor()
    executor._table_columns["trades"].add("unexpected_column")
    with pytest.raises(StorageSchemaDrift, match="extra"):
        await assert_no_schema_drift(executor, DDL_DIR, sleep=_no_sleep)


def test_0003_runner_splits_one_alter_add_column_per_statement() -> None:
    from candleviewer.storage.questdb.runner import parse_ddl_file_statements

    stmts = parse_ddl_file_statements(DDL_DIR / "0003_bars_integrity_columns.sql")
    assert len(stmts) == 12  # 6 tables x (source, row_checksum)
    for stmt in stmts:
        assert stmt.upper().count("ADD COLUMN") == 1 and "," not in stmt
    for table in ("time", "tick", "volume", "range", "renko", "delta"):
        mine = [x for x in stmts if f"bars_{table} " in x]
        assert sorted(("source" in x, "row_checksum" in x) for x in mine) == [
            (False, True),
            (True, False),
        ]


def test_multi_column_add_file_yields_one_alter_per_column(tmp_path: Path) -> None:
    from candleviewer.storage.questdb.runner import parse_ddl_file_statements

    (tmp_path / "0001.sql").write_text(
        "ALTER TABLE t ADD COLUMN a LONG;\nALTER TABLE t ADD COLUMN b SYMBOL CAPACITY 8 CACHE;\n",
        encoding="utf-8",
    )
    stmts = parse_ddl_file_statements(tmp_path / "0001.sql")
    assert stmts == [
        "ALTER TABLE t ADD COLUMN a LONG;",
        "ALTER TABLE t ADD COLUMN b SYMBOL CAPACITY 8 CACHE;",
    ]


@pytest.mark.asyncio
async def test_drift_check_waits_for_wal_apply_then_passes() -> None:
    executor = _FakeExecutor()
    executor._table_columns["bars_tick"].discard("row_checksum")
    reads = 0
    real_fetch = executor.fetch

    async def lagging_fetch(sql: str, *args: object) -> list[dict[str, object]]:
        nonlocal reads
        if "table_columns('bars_tick')" in sql:
            reads += 1
            if reads == 3:  # the WAL apply job catches up
                executor._table_columns["bars_tick"].add("row_checksum")
        return await real_fetch(sql, *args)

    executor.fetch = lagging_fetch  # type: ignore[method-assign]
    await assert_no_schema_drift(executor, DDL_DIR, sleep=_no_sleep)
    assert reads == 3


@pytest.mark.asyncio
async def test_persistent_drift_still_raises_after_settle_window() -> None:
    executor = _FakeExecutor()
    executor._table_columns["bars_tick"].discard("row_checksum")
    with pytest.raises(StorageSchemaDrift, match="row_checksum"):
        await assert_no_schema_drift(executor, DDL_DIR, sleep=_no_sleep)
