"""Integration: the reconciliation pass's own reads and its watermark on real Postgres 16 (E29-T06
#914 PR 2b; 24 Sec.8.5 `gap_from`; 21 Sec.3.2.1, Sec.3.3.6). The watermark moves forward only and
only on its own account's live row, and `stored` answers the account's own `exec_id`s alone.
`testcontainers` in CI; run on the VPS when its load allows.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.reconcile_sqlalchemy import SqlAlchemyReconcileStore
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_T0 = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#914)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=180,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _account(c: Conn, *, deleted: bool = False) -> UUID:
    aid, uid = uuid.uuid4(), str(uuid.uuid4().int % 10**15)
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        (str(aid), uid, f"acct {uid}"),
    )
    if deleted:
        c.execute("UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s", (str(aid),))
    return aid


def _fill(account: UUID, exec_id: str) -> NewExecution:
    return NewExecution(
        exchange_account_id=account, exec_id=exec_id, symbol="BTCUSDT", side="Buy",
        exec_qty=Decimal("0.1"), exec_price=Decimal(63000), exec_value=Decimal(6300),
        exec_type="Funding", is_maker=False, exec_ts=_T0, order_link_id=None,
        exec_fee=Decimal("0.01"), fee_rate=Decimal("0.0001"), fee_currency="USDT", closed_pnl=None,
    )  # fmt: skip


async def test_the_watermark_moves_forward_only_and_only_on_its_own_live_row(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        mine, other, gone = _account(c), _account(c), _account(c, deleted=True)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "oms")
    store = SqlAlchemyReconcileStore(rel, statement_timeout_ms=2000)
    try:
        assert await store.last_reconciled(mine) is None
        assert await store.advance(mine, _T0) is True
        assert await store.advance(mine, _T0 - timedelta(minutes=5)) is True  # never back
        assert await store.last_reconciled(mine) == _T0
        assert await store.advance(mine, _T0 + timedelta(seconds=30)) is True
        assert await store.last_reconciled(mine) == _T0 + timedelta(seconds=30)
        assert await store.last_reconciled(other) is None  # another account's row is untouched
        assert await store.advance(gone, _T0) is False  # a deleted account takes no mark
        assert await store.last_reconciled(gone) is None
    finally:
        await rel.dispose()


async def test_stored_answers_the_accounts_own_exec_ids_alone(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        mine, other = _account(c), _account(c)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "oms")
    fills = SqlAlchemyExecutionStore(rel, statement_timeout_ms=2000)
    store = SqlAlchemyReconcileStore(rel, statement_timeout_ms=2000)
    try:
        assert await fills.insert(_fill(mine, "e1"))
        assert await fills.insert(_fill(other, "e2"))
        assert await store.stored(mine, ["e1", "e2", "e3"]) == frozenset({"e1"})
        assert await store.stored(other, ["e1", "e2"]) == frozenset({"e2"})
        assert await store.live_for_account(mine) == ()
    finally:
        await rel.dispose()
