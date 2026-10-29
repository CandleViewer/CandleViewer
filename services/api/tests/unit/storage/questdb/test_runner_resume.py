"""Unit tests for the runner's resume guard (#3093).

QuestDB 8.1.1 has no transactional DDL and rejects `ADD COLUMN IF NOT EXISTS`, so a run that dies
between a file's statements and its `_cv_migrations` record leaves effects without the record. The
next run must finish the file with no error and must not drop a `bars_*` table that already has the
shape 0004 re-creates. No docker: `_Engine` models only what was measured on `questdb/questdb:8.1.1`
(2026-10-21): a plain duplicate `ADD COLUMN` raises, `table_columns()` of an absent table raises and
shows an `ALTER` only once the table's WAL apply ran, `DROP TABLE` drops the rows, and
`CREATE TABLE IF NOT EXISTS` and `DEDUP ENABLE UPSERT KEYS` can be repeated. The real engine is
`tests/integration/storage/test_questdb_ddl_resume.py`.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from candleviewer.storage.errors import StorageSchemaDrift, StorageWalNotApplied
from candleviewer.storage.questdb.ddl import (
    add_column_target,
    drop_target,
    parse_ddl_dir,
    parse_ddl_file,
)
from candleviewer.storage.questdb.runner import (
    assert_no_schema_drift,
    parse_ddl_file_statements,
    run_migrations,
)

DDL_DIR = Path(__file__).resolve().parents[6] / "backend" / "db" / "questdb"
FILES = sorted(DDL_DIR.glob("*.sql"))
NAMES = [path.name for path in FILES]
FINAL = {table.name: table for table in parse_ddl_dir(DDL_DIR)}
BARS = [f"bars_{kind}" for kind in ("time", "tick", "volume", "range", "renko", "delta")]


def _statements_through(files: int) -> int:
    return sum(len(parse_ddl_file_statements(path)) for path in FILES[:files])


async def _no_sleep(_: float) -> None:
    return None


class Crash(ConnectionError):
    """The process or the connection died: the statement after `crash_after` never ran."""


@dataclass
class _Table:
    columns: dict[str, str]  # name -> TYPE, as the DDL left the table
    keys: set[str]
    rows: int = 0
    behind: int = 0  # ALTERs the WAL apply job has not applied yet
    suspended: bool = False
    applied: dict[str, str] = field(init=False)  # what `table_columns()` shows

    def __post_init__(self) -> None:
        self.applied = dict(self.columns)


_CREATE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\) TIMESTAMP", re.IGNORECASE)
_KEYS = re.compile(r"DEDUP UPSERT KEYS\s*\(([^)]*)\)", re.IGNORECASE)
_ADD = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+) (\w+)", re.IGNORECASE)
_DEDUP = re.compile(r"ALTER TABLE (\w+) DEDUP ENABLE UPSERT KEYS\s*\(([^)]*)\)", re.IGNORECASE)


def _keys(raw: str) -> set[str]:
    return {key.strip().strip('"').lower() for key in raw.split(",")}


class _Engine:
    """The QuestDB the runner talks to. Once `crash_after` DDL statements ran, the next statement
    (a DDL one or a record's INSERT) raises `Crash` and never reaches the engine."""

    def __init__(self, spell: Callable[[str], str] = str) -> None:
        self.spell = spell  # `str` is as measured; the sweep also spells in other cases
        self.tables: dict[str, _Table] = {}
        self.records: list[str] = []
        self.executed: list[str] = []
        self.ddl = 0
        self.crash_after: int | None = None

    async def execute(self, sql: str, *args: object) -> None:
        text = " ".join(sql.split())
        if text.upper().startswith("CREATE TABLE IF NOT EXISTS _CV_MIGRATIONS"):
            return  # the record table's bootstrap
        if self.crash_after is not None and self.ddl >= self.crash_after:
            raise Crash
        self.executed.append(text)
        if text.upper().startswith("INSERT INTO _CV_MIGRATIONS"):
            self.records.append(str(args[0]))
            return
        self.ddl += 1
        if m := _CREATE.match(text):
            defs = [column.split() for column in m[2].split(",")]
            columns = {name.strip('"').lower(): kind.upper() for name, kind, *_ in defs}
            keys = _KEYS.search(text)
            self.tables.setdefault(m[1].lower(), _Table(columns, _keys(keys[1]) if keys else set()))
        elif text.upper().startswith("DROP TABLE IF EXISTS"):
            self.tables.pop(text.rstrip(";").split()[-1].lower(), None)
        elif m := _ADD.match(text):
            if (table := self.tables.get(m[1].lower())) is None:
                raise RuntimeError(f"table '{m[1]}' does not exist")
            if m[2].lower() in table.columns:
                raise RuntimeError(f"column '{m[2]}' already exists")
            table.columns[m[2].lower()] = m[3].upper()
            table.behind += 1
        elif m := _DEDUP.match(text):
            self.tables[m[1].lower()].keys = _keys(m[2])
        else:
            raise AssertionError(f"the fake does not know: {text[:60]}")

    @staticmethod
    def _apply(table: _Table) -> None:
        if table.behind and not table.suspended:
            table.behind, table.applied = 0, dict(table.columns)

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        if "wal_tables" in sql:
            if (table := self.tables.get(str(args[0]))) is None:
                return []  # not a WAL table: nothing to wait for (the record table is not modelled)
            behind = table.behind
            self._apply(table)  # the apply job runs between two polls
            return [{"writerTxn": 0, "sequencerTxn": behind, "suspended": table.suspended}]
        if "FROM tables()" in sql:
            return [{"table_name": args[0]}] if args[0] in self.tables else []
        if "table_columns" in sql:
            if (table := self.tables.get(sql.split("'")[1])) is None:
                raise RuntimeError("exception in function factory")  # 8.1.1: an absent table raises
            spell = self.spell
            shown = [
                {"column": spell(name), "type": spell(kind), "upsertKey": name in table.keys}
                for name, kind in table.applied.items()
            ]
            self._apply(table)  # the apply job keeps running while the client reads
            return shown
        assert "_cv_migrations" in sql, sql
        return [{"filename": name} for name in self.records]


async def _migrated(*, records_kept: int) -> _Engine:
    """Every file ran and the six `bars_*` tables hold 3 rows each, but `_cv_migrations` kept only
    the first `records_kept` records."""
    engine = _Engine()
    await run_migrations(engine, DDL_DIR, sleep=_no_sleep)
    for name in BARS:
        engine.tables[name].rows = 3
    engine.records = NAMES[:records_kept]
    engine.executed.clear()
    return engine


@pytest.mark.parametrize("spell", [str, str.title, str.lower])
@pytest.mark.parametrize("statements_before_the_crash", range(_statements_through(len(FILES)) + 1))
async def test_a_rerun_after_a_crash_finishes_every_file_and_keeps_the_rows(
    statements_before_the_crash: int, spell: Callable[[str], str]
) -> None:
    engine = _Engine(spell)
    engine.crash_after = statements_before_the_crash
    with pytest.raises(Crash):
        await run_migrations(engine, DDL_DIR, sleep=_no_sleep)
    engine.crash_after = None
    already_final = [n for n, t in engine.tables.items() if set(t.columns) == set(FINAL[n].columns)]
    for name in already_final:
        engine.tables[name].rows = 1  # rows written after the crash, as the recorder writes them

    await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert sorted(engine.records) == NAMES
    await assert_no_schema_drift(engine, DDL_DIR, sleep=_no_sleep)
    assert {n: t.keys for n, t in engine.tables.items()} == {
        n: set(t.dedup_keys) for n, t in FINAL.items()
    }
    assert [n for n in already_final if engine.tables[n].rows != 1] == []
    assert await run_migrations(engine, DDL_DIR, sleep=_no_sleep) == []


async def test_a_lost_0004_record_does_not_drop_the_populated_bars_tables() -> None:
    engine = await _migrated(records_kept=3)

    applied = await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert applied == NAMES[3:]
    assert not [s for s in engine.executed if s.startswith("DROP")]
    assert [engine.tables[name].rows for name in BARS] == [3] * 6


async def test_0004_still_recreates_the_old_shape_bars_tables(tmp_path: Path) -> None:
    """Owner decision, path B (#1778 item R): a table without 0004's columns is dropped."""
    for path in FILES[:3]:
        shutil.copy(path, tmp_path / path.name)
    engine = _Engine()
    await run_migrations(engine, tmp_path, sleep=_no_sleep)
    for name in BARS:
        engine.tables[name].rows = 3

    await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert [engine.tables[name].rows for name in BARS] == [0] * 6
    assert all({"generation", "index"} <= set(engine.tables[name].applied) for name in BARS)


async def test_a_bars_table_with_0004_columns_but_the_old_upsert_keys_is_recreated() -> None:
    """QuestDB cannot re-key in place: only the re-created table has 0004's keys."""
    engine = await _migrated(records_kept=3)
    engine.tables["bars_time"].keys = {"ts", "symbol", "bar_param"}

    await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert engine.tables["bars_time"].rows == 0
    assert engine.tables["bars_time"].keys == {"ts", "symbol", "bar_param", "generation", "index"}


async def test_a_table_widened_after_0004_keeps_its_rows_when_the_0004_record_is_lost() -> None:
    """A superset check, not equality: a later additive file must not make a lost record wipe it."""
    engine = await _migrated(records_kept=3)
    widened = engine.tables["bars_time"]
    widened.columns["later"] = widened.applied["later"] = "LONG"
    widened.keys.add("later")

    await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert engine.tables["bars_time"].rows == 3


async def test_a_drop_the_file_does_not_re_create_runs_as_written(tmp_path: Path) -> None:
    create = "CREATE TABLE IF NOT EXISTS t (ts TIMESTAMP) TIMESTAMP(ts) PARTITION BY DAY WAL;\n"
    (tmp_path / "0001.sql").write_text(create, encoding="utf-8")
    engine = _Engine()
    await run_migrations(engine, tmp_path, sleep=_no_sleep)
    (tmp_path / "0002.sql").write_text("DROP TABLE IF EXISTS t;\n", encoding="utf-8")

    assert await run_migrations(engine, tmp_path, sleep=_no_sleep) == ["0002.sql"]
    assert "t" not in engine.tables


async def test_a_column_present_with_another_type_is_drift_and_its_file_stays_unrecorded() -> None:
    engine = await _migrated(records_kept=5)
    deltas = engine.tables["orderbook_deltas"]
    deltas.columns["ts_match"] = deltas.applied["ts_match"] = "LONG"  # the DDL adds TIMESTAMP

    with pytest.raises(StorageSchemaDrift, match=r"orderbook_deltas\.ts_match") as exc:
        await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert "LONG" in str(exc.value) and "TIMESTAMP" in str(exc.value)
    assert engine.records == NAMES[:5]


async def test_an_ilp_shaped_table_stops_the_run_at_0003_before_any_drop() -> None:
    engine = await _migrated(records_kept=2)
    for table in engine.tables.values():
        table.keys = set()  # ILP creates the DDL's columns and no upsert keys (#3897)

    with pytest.raises(StorageSchemaDrift, match="table bars_time lacks its DDL upsert keys"):
        await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert engine.records == NAMES[:2] and not [s for s in engine.executed if s.startswith("DROP")]


async def test_the_guard_reads_columns_only_after_the_alter_was_applied() -> None:
    """`table_columns()` lags an ALTER until the WAL apply ran (32 of 80 immediate reads on 8.1.1):
    a guard that read at once would see the column absent, re-issue the ADD COLUMN and fail."""
    engine = _Engine()
    engine.crash_after = _statements_through(5)  # 0005's two statements ran, its record did not
    with pytest.raises(Crash):
        await run_migrations(engine, DDL_DIR, sleep=_no_sleep)
    assert engine.tables["liquidations"].behind == 1  # the ALTER is not applied yet
    engine.crash_after = None
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    await run_migrations(engine, DDL_DIR, sleep=record)  # "already exists" if it read too early

    # The record read's and the guard's, then one before each 0007 ALTER after its first: each
    # waits for the one before it on `heatmap_cells` to be applied.
    assert engine.records == NAMES and slept == [0.02] * 5


async def test_a_suspended_data_table_stops_the_run_before_any_drop() -> None:
    engine = await _migrated(records_kept=3)
    engine.tables["bars_time"].suspended = True
    engine.tables["bars_time"].behind = 1

    with pytest.raises(StorageWalNotApplied) as exc:
        await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    assert (exc.value.reason, exc.value.table) == ("suspended", "bars_time")
    assert not [s for s in engine.executed if s.startswith("DROP")]


async def test_a_resumed_file_logs_each_skipped_statement_and_one_warning_with_names_only() -> None:
    engine = await _migrated(records_kept=3)  # 0004 to 0007 re-run over their own effects

    with capture_logs() as logs:
        await run_migrations(engine, DDL_DIR, sleep=_no_sleep)

    skipped = [log for log in logs if log["event"] == "questdb_statement_skipped"]
    resumed = [log for log in logs if log["event"] == "questdb_migration_resumed"]
    assert {s["log_level"] for s in skipped} == {"info"}  # the lines the runbook points to
    assert [(s["filename"], s["kind"], s["table"], s.get("column")) for s in skipped] == [
        *[(NAMES[3], "drop_table", table.name, None) for table in parse_ddl_file(FILES[3])],
        (NAMES[4], "add_column", "liquidations", "batch_index"),
        (NAMES[5], "add_column", "orderbook_deltas", "prev_update_id"),
        (NAMES[5], "add_column", "orderbook_deltas", "ts_match"),
        (NAMES[5], "add_column", "orderbook_snapshots", "ts_match"),
        *[
            (NAMES[6], "add_column", "heatmap_cells", column)
            for column in ("estimated", "samples", "off_window_bid_qty", "off_window_ask_qty")
        ],
    ]
    assert [(r["filename"], r["log_level"], r["statements_skipped"]) for r in resumed] == [
        (NAMES[3], "warning", 6),
        (NAMES[4], "warning", 1),
        (NAMES[5], "warning", 3),
        (NAMES[6], "warning", 4),
    ]
    # Names and counts only, never a value (C-12.6).
    assert {frozenset(s) - {"column"} for s in skipped} == {
        frozenset({"event", "log_level", "filename", "kind", "table"})
    }
    assert {frozenset(r) for r in resumed} == {
        frozenset({"event", "log_level", "filename", "statements_skipped"})
    }


async def test_a_first_run_skips_nothing_and_logs_no_resume() -> None:
    with capture_logs() as logs:
        await run_migrations(_Engine(), DDL_DIR, sleep=_no_sleep)
    assert {line["event"] for line in logs} == {"questdb_migration_applied"}


#: The statements QuestDB 8.1.1 accepts again with no effect: `run_migrations` runs them as is.
_RERUNNABLE = (
    re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s", re.IGNORECASE),
    re.compile(r"ALTER\s+TABLE\s+\w+\s+DEDUP\s+ENABLE\s+UPSERT\s+KEYS\s*\(", re.IGNORECASE),
)


@pytest.mark.parametrize("path", FILES, ids=NAMES)
def test_every_shipped_statement_has_a_resume_rule(path: Path) -> None:
    """A new statement kind needs a rule in the runner's guard and here, or this fails."""
    recreated = {table.name for table in parse_ddl_file(path)}
    unruled = [
        stmt
        for stmt in parse_ddl_file_statements(path)
        if not any(pattern.match(stmt) for pattern in _RERUNNABLE)
        and add_column_target(stmt) is None
        and drop_target(stmt) not in recreated
    ]
    assert unruled == []
