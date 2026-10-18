"""Integration: the admin incident list on real Postgres 16, end to end (E42-T05).

The list is served now that something writes the `incidents` table: what `PgSystemEventWriter`
writes, on its own or behind the health registry's transitions, is what the composition root's own
`build_admin_incidents` serves and what `/admin/overview` counts. Not run locally (no docker); the
same file was run on a scratch Postgres 16.4 first. CI integration lane."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.wiring import system_event_redactor
from candleviewer.admin_wiring import AdminCountsAdapter, build_admin_incidents
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.observability.health_probes import (
    ComponentState,
    HealthRegistry,
    ProbeResult,
    SystemEvent,
)
from candleviewer.settings import Settings
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import SqlAlchemyAdminCounts
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(  # bounded, so a stuck migration fails the module instead of hanging it
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env=env,
            check=True,
            timeout=120,
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield relational
    finally:
        await relational.dispose()


class _Probe:
    """A Postgres probe whose state the test sets, as the real `register_real_probes` reports."""

    name, timeout = "postgres", 1.0

    def __init__(self) -> None:
        self.state = ComponentState.HEALTHY

    async def check(self) -> ProbeResult:
        down = self.state is ComponentState.DOWN
        return ProbeResult(self.state, "postgres unreachable" if down else "")


async def test_what_the_writers_record_is_what_the_wired_list_serves_and_the_overview_counts(
    pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    writer = PgSystemEventWriter(rel, redact_details=system_event_redactor())
    for n in range(40):  # the ticket's scenario: forty errors of one fault
        message = f"parquet write failed for BTCUSDT segment {n}"
        await writer.write(SystemEvent("recorder", "parquet_write", "error", message, {}))
    registry, probe = HealthRegistry(events=writer), _Probe()
    registry.register(probe)
    for state in (ComponentState.HEALTHY, ComponentState.DOWN, ComponentState.HEALTHY):
        probe.state = state
        await registry.refresh()  # one outage: an error row, then a recovery at `info`
    settings = Settings(storage_backend="real", pg_dsn=SecretStr(pg_dsn))
    service = build_admin_incidents(
        settings, system_settings=SqlAlchemySystemSettings(rel), now=lambda: NOW
    )
    page = await service.page(status="open", cursor=None, limit=10)
    shown = {(r.component, r.title, r.occurrences, r.severity) for r in page.items}
    assert shown == {
        ("recorder", "parquet write failed for <symbol> segment <n>", 40, "error"),
        ("db", "postgres healthy -> down: postgres unreachable", 1, "error"),
    }
    assert page.next_cursor is None
    counts = AdminCountsAdapter(SqlAlchemyAdminCounts(rel, env=settings.environment.value))
    assert await counts.open_incidents() == 2  # the overview tile: the table, not raw events
