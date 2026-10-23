"""Integration (#492 S4): `SqlAlchemyRetentionPolicies` on real Postgres 16. The migration's seeded
defaults list; a replace swaps the whole set in one transaction, global and per-symbol rows alike;
a row the table refuses rolls the replace back, so the old set stays."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories import retention_policies_sqlalchemy as policies
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture  # a fresh, migrated database per test: the seeded defaults included
def dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        root, env = Path(__file__).resolve().parents[3], {**os.environ, "CV_PG_DSN": base}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env,
                       check=True)  # fmt: skip
        yield base.replace("+psycopg", "+asyncpg")


@pytest.fixture
def store(dsn: str) -> policies.SqlAlchemyRetentionPolicies:
    return policies.SqlAlchemyRetentionPolicies(SqlAlchemyRelationalRepository(dsn))


def _row(stream: str, days: int, action: str = "archive_parquet",
         symbol: str | None = None) -> dict[str, Any]:  # fmt: skip
    return {"stream": stream, "retain_days": days, "action": action, "symbol": symbol}


def _set(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(r["scope"], r["symbol"], r["stream"], r["retain_days"], r["action"]) for r in rows]


async def test_the_seeded_defaults_then_a_whole_replace(
    store: policies.SqlAlchemyRetentionPolicies,
) -> None:
    seeded = await store.list_policies()
    assert ("default", None, "trades", 30, "archive_parquet") in _set(seeded) and len(seeded) == 8
    new = [_row("trades", 60), _row("orderbook_delta", 3, "drop", "ETHUSDT")]
    after = await store.replace(new, actor=None)
    assert _set(after) == [("default", None, "trades", 60, "archive_parquet"),
                           ("symbol", "ETHUSDT", "orderbook_delta", 3, "drop")]  # fmt: skip
    assert _set(await store.list_policies()) == _set(after)
    assert all(r["updated_at"].tzinfo is not None for r in after)


async def test_a_failing_row_leaves_the_old_set(
    store: policies.SqlAlchemyRetentionPolicies,
) -> None:
    before = await store.replace([_row("trades", 45), _row("klines", 90)], actor=None)
    with pytest.raises(Exception, match="rp_days"):  # the table's CHECK refuses 0 days
        await store.replace([_row("trades", 10), _row("tickers", 0)], actor=None)
    assert await store.list_policies() == before
