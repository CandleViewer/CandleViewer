"""Integration (E29-T04 #913 slice 3C): `load_trade_grants` on real Postgres 16.

It reads every grant row of the user with its trade right, a frozen and a soft-revoked one
included (21 Sec.3.1.3), so the order route's check can refuse them. Not run locally (no docker);
CI `integration` runs it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', 'active')"
)
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label, is_enabled) "
    "VALUES (CAST(:id AS uuid), 'bybit', CAST(:env AS exchange_env), 'main', :uid, :label, :on)"
)
_GRANT = sa.text(
    "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, can_trade, frozen, "
    "frozen_at) VALUES (CAST(:user AS uuid), CAST(:account AS uuid), :view, :trade, :frozen, "
    "CASE WHEN :frozen THEN now() END)"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        env = {**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, env=env, check=True
        )
        yield dsn


@pytest.fixture
async def db(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyRelationalRepository, AsyncEngine]]:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    try:
        yield rel, engine
    finally:
        await rel.dispose()
        await engine.dispose()


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


async def _account(engine: AsyncEngine, env: str = "demo", *, on: bool = True) -> uuid.UUID:
    account = uuid.uuid4()
    uid, label = str(account.int % 10**12), f"a-{account.hex[:12]}"
    await _exec(engine, _ACCOUNT, id=str(account), env=env, uid=uid, label=label, on=on)
    return account


async def test_load_trade_grants_reads_each_grant_row_with_its_trade_right(
    db: tuple[SqlAlchemyRelationalRepository, AsyncEngine],
) -> None:
    rel, engine = db
    user = uuid.uuid4()
    await _exec(engine, _USER, id=str(user), email=f"{user.hex}@x.invalid", name=user.hex[:12])
    rows = {  # (can_view, can_trade, frozen): a trade, a view-only, a frozen and a revoked grant
        await _account(engine): (True, True, False),
        await _account(engine): (True, False, False),
        await _account(engine): (True, True, True),
        await _account(engine): (False, False, False),
    }
    for account, (view, trade, frozen) in rows.items():
        flags = {"view": view, "trade": trade, "frozen": frozen}
        await _exec(engine, _GRANT, user=str(user), account=str(account), **flags)
    grants = await SqlAlchemyScopeSource(rel).load_trade_grants(user)
    assert {account: tuple(flags) for account, *flags in grants} == rows
    assert await SqlAlchemyScopeSource(rel).load_trade_grants(uuid.uuid4()) == []
