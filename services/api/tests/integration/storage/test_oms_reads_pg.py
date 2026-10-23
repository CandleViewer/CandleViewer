"""Integration (E29-T04 #913 slice 3C): the OMS's account read on real Postgres 16.

The account read answers an account whatever its status, with only its `active`, unrevoked key
(21 Sec.3.2.2). `load_trade_grants` is `test_trade_grants_pg.py`'s. Not run locally (no docker);
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
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from candleviewer.storage.repositories.trading_accounts_sqlalchemy import (
    SqlAlchemyTradingAccountReads,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label, is_enabled) "
    "VALUES (CAST(:id AS uuid), 'bybit', CAST(:env AS exchange_env), 'main', :uid, :label, :on)"
)
_DELETE = sa.text("UPDATE exchange_accounts SET deleted_at = now() WHERE id = CAST(:id AS uuid)")
_KEY = sa.text(
    "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, secret_enc, "
    "enc_nonce, dek_ref, permission_snapshot, status, revoked_at) VALUES (CAST(:id AS uuid), "
    "CAST(:account AS uuid), :label, '\\x01', 'AB12', '\\x02', :nonce, 'dek', "
    "CAST(:snapshot AS jsonb), CAST(:status AS key_status), CASE WHEN :revoked THEN now() END)"
)
_SNAPSHOT = '{"uid": "1", "permissions": {"ContractTrade": ["Order"]}}'


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


async def _key(engine: AsyncEngine, account: uuid.UUID, status: str, *, revoked: bool) -> uuid.UUID:
    key = uuid.uuid4()
    await _exec(
        engine, _KEY, id=str(key), account=str(account), label=f"k-{key.hex[:8]}",
        nonce=bytes(12), snapshot=_SNAPSHOT, status=status, revoked=revoked,
    )  # fmt: skip
    return key


async def test_the_account_read_answers_its_status_and_its_one_active_unrevoked_key(
    db: tuple[SqlAlchemyRelationalRepository, AsyncEngine],
) -> None:
    rel, engine = db
    keyed, keyless = await _account(engine), await _account(engine, "live", on=False)
    await _key(engine, keyed, "active", revoked=True)
    active = await _key(engine, keyed, "active", revoked=False)
    await _key(engine, keyless, "pending", revoked=False)
    await _exec(engine, _DELETE, id=str(keyless))
    reads = SqlAlchemyTradingAccountReads(rel)
    uid = str(keyed.int % 10**12)
    assert await reads.read_account(keyed) == TradingAccountRow(keyed, "demo", uid, False, active)
    gone = await reads.read_account(keyless)
    assert gone is not None and (gone.environment, gone.deleted, gone.active_key_id) == (
        "live", True, None
    )  # fmt: skip
    assert await reads.read_account(uuid.uuid4()) is None
