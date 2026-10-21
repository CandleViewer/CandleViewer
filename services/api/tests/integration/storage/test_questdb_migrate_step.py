"""Integration (#3897): the deploy's migrate step on a fresh QuestDB container, the ticket's first
two scenarios. Postgres is not part of them, so the Alembic step and the migration lock are no-ops
here (the order of the steps is the unit test's). The third scenario, drift, is the unit test's exit
status for `StorageSchemaDrift` over the runner's own detection on a real engine
(`test_questdb_hot_tier.py`).
"""

from __future__ import annotations

from contextlib import nullcontext

import pytest
from structlog.testing import capture_logs

from candleviewer.settings import Settings
from candleviewer.storage.migrate import MigrateExit, Steps, run
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from candleviewer.storage.questdb.runner import applied_migrations
from tests.integration.storage.test_questdb_hot_tier import (
    DDL_DIR,
    _AsyncpgExecutor,
    _connect,
    questdb_container,  # noqa: F401 -- pytest fixture re-export
)

pytestmark = pytest.mark.integration

_NO_POSTGRES = Steps(upgrade=lambda _settings: None, lock=lambda _settings: nullcontext())


def _settings(qdb: tuple[str, int, int]) -> Settings:
    host, pg_port, _ = qdb
    return Settings(questdb_pg=f"{host}:{pg_port}")  # the container's default PG-wire login


async def test_the_migrate_step_creates_every_table_and_records_every_file(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
) -> None:
    assert await run(_settings(questdb_container), DDL_DIR, _NO_POSTGRES) is MigrateExit.OK
    host, pg_port, _ = questdb_container
    conn = await _connect(host, pg_port)
    try:
        executor = _AsyncpgExecutor(conn)
        tables = {r["table_name"] for r in await conn.fetch("SELECT table_name FROM tables()")}
        recorded = await applied_migrations(executor)  # waits for the WAL apply of the records
    finally:
        await conn.close()
    assert {t.name for t in parse_ddl_dir(DDL_DIR)} <= tables
    assert recorded == {path.name for path in DDL_DIR.glob("*.sql")}


async def test_a_second_run_applies_nothing_and_exits_zero(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
) -> None:
    settings = _settings(questdb_container)
    assert await run(settings, DDL_DIR, _NO_POSTGRES) is MigrateExit.OK
    with capture_logs() as logs:
        assert await run(settings, DDL_DIR, _NO_POSTGRES) is MigrateExit.OK
    assert [line["event"] for line in logs] == ["storage_migrate_done"]  # no file was applied
    assert logs[0]["questdb_files_applied"] == 0
