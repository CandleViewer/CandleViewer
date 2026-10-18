"""Integration, ADR-0037 S2a2 (#3009): records the audit lane journaled while the sink refused reach
`audit_log` after a restart once and in order, the chain verifies, and the segments the marker
passed are gone. Real Postgres 16 via testcontainers (needs Docker); the key is a test vector."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.lane import AuditLane
from candleviewer.audit.lane_journal import LaneFiles, LaneJournal, LaneKeys, segment_name
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration
_KEYS = LaneKeys(bytes(range(32)))


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3],
            env={**os.environ, "CV_PG_DSN": dsn.replace("+asyncpg", "+psycopg")},
            check=True,
        )
        yield dsn


async def _boot(tmp: Path, writer: AuditWriter) -> AuditLane:
    lane = AuditLane(LaneJournal(LaneFiles(tmp / "lane"), _KEYS, segment_max_bytes=1), writer)
    await lane.start()
    return lane


async def _drained(lane: AuditLane) -> None:
    async with asyncio.timeout(60):
        while lane.confirmed != lane.journal.end:  # noqa: ASYNC110 - the drain task moves it
            await asyncio.sleep(0)


async def _logouts(lane: AuditLane, writer: AuditWriter, ns: range) -> list[str]:
    records = [writer.build("auth.logout", actor_label="owner", object_id=str(n)) for n in ns]
    for record in records:
        await lane.append(record)
    return [str(record.record_id) for record in records]


async def _scenario(dsn: str, tmp: Path) -> tuple[bool, list[str]]:
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        repo = SqlAlchemyAuditRepository(relational)
        writer = AuditWriter(repo, str(tmp / "audit.wal"))
        await writer.start()
        lane = await _boot(tmp, writer)
        ids = await _logouts(lane, writer, range(2))  # drained while the sink accepts
        await _drained(lane)
        await writer.stop(5)  # from here the sink refuses: `AuditWriterStopped`
        ids += await _logouts(lane, writer, range(2, 5))
        await lane.close()  # the restart
        writer = AuditWriter(repo, str(tmp / "audit.wal"))
        await writer.start()  # the sink is back
        lane = await _boot(tmp, writer)
        await _drained(lane)
        await lane.close()
        await writer.flush(60)
        await writer.stop(5)
        return (await AuditQueryService(repo).verify()).verified, ids
    finally:
        await relational.dispose()


def test_lane_records_reach_audit_log_once_across_a_refusing_sink_and_a_restart(
    pg_dsn: str, tmp_path: Path
) -> None:
    verified, ids = asyncio.run(_scenario(pg_dsn, tmp_path))
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql")) as conn:
        rows = conn.execute("SELECT action, record_id::text FROM audit_log ORDER BY id").fetchall()
    lane = ("audit.lane_started", "audit.lane_resumed")

    assert verified
    assert [a for a, _ in rows] == [*lane, *["auth.logout"] * 5, "audit.lane_resumed"]
    assert [r for a, r in rows if a == "auth.logout"] == ids
    assert sorted(os.listdir(tmp_path / "lane")) == ["confirmed", segment_name(8)]
