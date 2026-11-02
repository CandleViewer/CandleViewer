"""Integration: `0004_instruments` + `SqlAlchemyInstrumentsRepository` +
`InstrumentsRefreshScheduler` against real Postgres 16 (testcontainers).
Covers "Catalogue loaded at startup" (persist + reload), "Tick size changes"
(new `instrument_versions` row) and "Refresh fails" (`stale_since` set).
Upstream is a fake fetcher over neutral fixture rows — no network.

Not run locally (no docker); exercised by the integration CI job.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments_refresh import (
    InstrumentRefreshError,
    InstrumentsRefreshScheduler,
)
from candleviewer.storage.repositories.instruments_sqlalchemy import (
    SqlAlchemyInstrumentsRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


def _row(tick: str = "0.10") -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "baseCoin": "BTC",
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "status": "Trading",
        "launchTime": "1585699200000",
        "priceScale": "2",
        "priceFilter": {"tickSize": tick},
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "100"},
        "leverageFilter": {"maxLeverage": "100.00"},
        "fundingInterval": 480,
    }


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


async def test_persist_version_stale_and_reload(pg_dsn: str) -> None:
    pages: list[Any] = [[_row()], [_row("0.50")], RuntimeError("down")]

    async def fetch(now_us: Callable[[], int]) -> InstrumentsFetchResult:
        item = pages.pop(0) if len(pages) > 1 else pages[0]
        if isinstance(item, Exception):
            raise item
        return parse_instruments(list(item), fetched_at_us=now_us())

    async def _nosleep(_: float) -> None:
        return None

    relational = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyInstrumentsRepository(relational)
    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch, repository=repo, sleep=_nosleep, max_retries=1
    )
    try:
        await sched.refresh_now()
        await sched.refresh_now()
        with pytest.raises(InstrumentRefreshError):
            await sched.refresh_now()
        reloaded = await repo.load_all()
        assert [r["symbol"] for r in reloaded] == ["BTCUSDT"]
        assert reloaded[0]["metadata_version"] == 2
    finally:
        await relational.dispose()

    sync_dsn = pg_dsn.replace("postgresql+asyncpg", "postgresql")
    with psycopg.connect(sync_dsn) as conn:
        versions = conn.execute(
            "SELECT metadata_version, changed_fields FROM instrument_versions"
        ).fetchall()
        stale = conn.execute("SELECT stale_since FROM instruments").fetchone()
    assert versions == [(2, ["tick_size"])]
    assert stale is not None and stale[0] is not None
