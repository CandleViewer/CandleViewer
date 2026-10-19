"""Integration: a backup delete on Postgres 16 at head (E42-T05 #966 BK-12), through
`BackupDeletion` over the real `SqlAlchemyBackups`, with the artefact remover and the audit trail
faked: the row is marked once and kept, the list serves it with `deleted_at`, the freshness reloads
the kind, and the kind's last verified backup is refused by the real `usable_count`.
testcontainers, CI-only; run before the PR on a scratch Postgres 16.4 (stand-in)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.deletion import BackupDeletion, DeleteRecord, DeleteRefused
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.metrics import BackupFreshness
from candleviewer.api.admin_backups import backup_payload
from candleviewer.observability.metrics import Gauge
from candleviewer.storage.repositories.backups_sqlalchemy import SqlAlchemyBackups
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._delete_fakes import Remover, Trail

pytestmark = pytest.mark.integration

T0, H, USER = datetime(2026, 10, 19, 6, 0, tzinfo=UTC), timedelta(hours=1), UUID(int=77)
NEWER, OLDER = UUID(int=1), UUID(int=2)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(  # bounded, so a stuck migration fails the module instead of hanging it
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3], env=env, check=True, timeout=120,
        )  # fmt: skip
        plain = url.replace("postgresql+psycopg2", "postgresql")
        with psycopg.connect(plain, autocommit=True) as c:
            c.execute("INSERT INTO users (id, email, username, password_hash, status) VALUES"
                      " (%s, 'ops@x.test', 'ops', '$argon2id$x', 'active')", (USER,))  # fmt: skip
            for bid, ago in ((NEWER, 1), (OLDER, 3)):  # two verified `pg_dump`s
                c.execute(
                    "INSERT INTO backups (id, kind, status, target_path, started_at, finished_at,"
                    " verified_at, checksum_sha256) VALUES (%s, 'pg_dump', 'verified', %s, %s, %s,"
                    " %s, %s)",
                    (bid, f"/srv/cv/backups/{bid}.age", T0 - ago * H, T0 - ago * H + H / 4,
                     T0 - ago * H + H / 2, "a" * 64),
                )  # fmt: skip
        yield plain


@pytest.fixture
async def store(pg_dsn: str) -> AsyncIterator[SqlAlchemyBackups]:
    rel = SqlAlchemyRelationalRepository(pg_dsn.replace("postgresql", "postgresql+asyncpg", 1))
    try:
        yield SqlAlchemyBackups(rel)
    finally:
        await rel.dispose()


async def test_mark_deleted_sets_deleted_at_once_and_list_shows_it(
    pg_dsn: str, store: SqlAlchemyBackups
) -> None:
    gate, log, trail = BackupJobGate(), list[tuple[str, bool]](), Trail()
    remover = Remover(gate, log)
    gauge = Gauge("cv_backup_last_success_age_seconds", "age", ["kind"], registry=None)
    freshness = BackupFreshness(store, now=lambda: T0, gauge=gauge)
    await freshness.start()
    deletion = BackupDeletion(store, remover, gate=gate, audit=trail, freshness=freshness,
                              now=lambda: T0)  # fmt: skip
    who = replace(principal("owner"), user_id=USER)  # a user `deleted_by` can reference

    async def write_ahead(record: DeleteRecord) -> None:
        await deletion.audit_delete(who, record)

    async def delete(bid: UUID) -> Any:
        try:
            await deletion.delete(bid, who, UUID(int=0xC0FFEE), write_ahead)
        except DeleteRefused as refused:
            return refused.rule
        return None

    assert await delete(NEWER) is None
    marked = await store.get(NEWER)
    assert marked is not None and (marked.deleted_at, marked.status) == (T0, "verified")
    with psycopg.connect(pg_dsn) as c:
        assert c.execute("SELECT deleted_by FROM backups WHERE id = %s", (NEWER,)).fetchone() == (
            USER,
        )
    assert (await delete(NEWER), await store.get(NEWER)) == ("backup_deleted", marked)  # once
    assert await delete(OLDER) == "last_usable_backup"  # the kind's last verified backup stays
    page = await BackupCatalogue(store, now=lambda: T0).page(
        kind="pg_dump", status=None, cursor=None, limit=10
    )
    served = {item["id"]: item["deleted_at"] for item in map(backup_payload, page.items)}
    assert served == {str(NEWER): T0.isoformat().replace("+00:00", "Z"), str(OLDER): None}
    assert remover.removed == [(NEWER, f"/srv/cv/backups/{NEWER}.age")]
    assert [r["reason"] for r in trail.records] == [None, "backup_deleted", "last_usable_backup"]
    ages = {s.labels["kind"]: s.value for f in gauge.collect() for s in f.samples}
    assert ages == {"pg_dump": (T0 - (T0 - 3 * H + H / 4)).total_seconds()}  # reloaded: the older
