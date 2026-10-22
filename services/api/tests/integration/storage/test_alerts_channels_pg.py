"""Integration (#4143) on real Postgres 16 through asyncpg, the production driver: an alert's
`channels` survive a create and an update. The adapter bound `array_literal(...)`'s string into
`CAST(:channels AS alert_channel[])`, which asyncpg refuses (sqlstate 22000, "a sized iterable
container expected"), so every alert write failed; unit tests use a fake unit of work and never saw
it. Needs docker (testcontainers); exercised by CI `integration`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.alerts_sqlalchemy import SqlAlchemyAlertRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[3]  # services/api: where `alembic.ini` lives


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        sync = dsn.replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": sync},
            check=True,
        )
        yield dsn


@pytest_asyncio.fixture
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyAlertRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "alerts-channels-it")
    try:
        yield SqlAlchemyAlertRepository(rel)
    finally:
        await rel.dispose()


def _owner(dsn: str) -> str:
    """An invited user (no role, so the owner floor is not involved); returns its id."""
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, %s)",
            (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}", "$argon2id$x"),
        )
    return uid


async def test_an_alert_with_two_channels_is_created_and_updated(
    pg_dsn: str, repo: SqlAlchemyAlertRepository
) -> None:
    ir: dict[str, object] = {"conditions": {}}
    digest = "a" * 64
    row = await repo.create(
        owner_user_id=_owner(pg_dsn),
        name="Breakout",
        condition_ir=ir,
        condition_hash=digest,
        channels=("in_app", "email"),  # no webhook: that needs an encrypted URL
    )
    assert row.channels == ("in_app", "email")
    kept = ("name", "condition_ir", "condition_hash", "trigger_mode", "cooldown_seconds")
    fields = {k: getattr(row, k) for k in (*kept, "expires_at", "severity", "message_template")}
    updated = await repo.update(
        row.id, if_match=row.updated_at, **fields, channels=("desktop", "in_app")
    )
    assert updated.channels == ("desktop", "in_app")
    again = await repo.get(row.id)
    assert again is not None and again.channels == ("desktop", "in_app")
