"""Integration (#3874): `StorageService` on the real backend, against a Postgres container, a
QuestDB container and a temporary cold root. The ticket's scenarios: the service starts with every
tier ready; an unreachable QuestDB fails the start closed, naming the tier and writing nothing;
and a recorded `publicTrade` batch written through the started service is drained by `stop()`,
read back from the hot tier by a fresh start, and exported to the cold tier with a checksum
manifest that verifies.

The QuestDB DDL is applied here, as the other QuestDB integration tests do: the service does not
apply it at boot (20-architecture.md §6.2).
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.trades import parse_trade_frame
from candleviewer.observability.health import HealthStatus
from candleviewer.settings import Settings
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.health import TierState
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.repositories.rows import TradeRow
from candleviewer.storage.service import StorageService
from tests._corpus import frames
from tests.integration.storage.test_questdb_hot_tier import (
    DDL_DIR,
    _AsyncpgExecutor,
    _connect,
    questdb_container,  # noqa: F401 -- pytest fixture re-export
    wait_for_row_count,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext

pytestmark = pytest.mark.integration

_RECORDED = "ws/recorded_publicTrade_BTCUSDT.jsonl"
_DAY_US = 86_400_000_000
_GRACE_S = 15.0


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _settings(pg_dsn: str, qdb: tuple[str, int, int], root: Path) -> Settings:
    host, pg_port, ilp_port = qdb
    return Settings(
        storage_backend="real",
        pg_dsn=SecretStr(pg_dsn),
        questdb_pg=f"{host}:{pg_port}",
        questdb_ilp=f"{host}:{ilp_port}",
        parquet_root=str(root),
    )


def _ctx(settings: Settings) -> AppContext:
    return cast("AppContext", SimpleNamespace(settings=settings))


def _recorded_trades() -> list[TradeRow]:
    """The recorded capture's prints, once per trade id (the table de-duplicates on it)."""
    prints: dict[str, TradePrint] = {}
    for raw in frames(_RECORDED):
        for p in parse_trade_frame(raw) or ():
            prints.setdefault(p.trade_id, p)
    return [
        TradeRow(
            ts_us=p.ts_event_us,
            symbol=p.symbol,
            price=str(p.price),
            qty=str(p.qty),
            side=p.side,
            trade_id=p.trade_id,
        )
        for p in prints.values()
    ]


def _entries(path: Path) -> list[Path]:
    return list(path.iterdir())


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_real_start_reports_every_tier_ready(
    pg_dsn: str,
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
    tmp_path: Path,
) -> None:
    service = StorageService(backend="real")
    await service.start(_ctx(_settings(pg_dsn, questdb_container, tmp_path)))
    try:
        report = service.tier_health()
        assert [(t.tier, t.state) for t in report.tiers] == [
            ("postgres", TierState.OK),
            ("questdb", TierState.OK),
            ("cold", TierState.OK),
        ]
        assert service.health().status is HealthStatus.OK
    finally:
        await service.stop(grace_s=_GRACE_S)
    assert service.health().status is HealthStatus.STOPPED


async def test_real_start_with_questdb_unreachable_fails_closed_naming_it(
    pg_dsn: str, tmp_path: Path
) -> None:
    unreachable = ("127.0.0.1", _closed_port(), _closed_port())
    service = StorageService(backend="real")
    with pytest.raises(StorageTierUnavailable, match="'questdb'") as refused:
        await service.start(_ctx(_settings(pg_dsn, unreachable, tmp_path)))
    assert "postgresql" not in str(refused.value)  # no DSN in the error (C-12.6)
    assert service.health().status is HealthStatus.STOPPED
    assert _entries(tmp_path) == []  # nothing written


async def test_recorded_batch_round_trips_through_the_hot_and_cold_tiers(
    pg_dsn: str,
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
    tmp_path: Path,
) -> None:
    host, pg_port, _ = questdb_container
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        rows = _recorded_trades()
        settings = _settings(pg_dsn, questdb_container, tmp_path)
        writing = StorageService(backend="real")
        await writing.start(_ctx(settings))
        try:
            await writing.market_data.write_trades(rows)
        finally:
            await writing.stop(grace_s=_GRACE_S)  # drains the ILP writer
        await wait_for_row_count(conn, "trades", len(rows))
    finally:
        await conn.close()

    day = min(r.ts_us for r in rows) // _DAY_US * _DAY_US
    assert max(r.ts_us for r in rows) < day + _DAY_US  # one partition day
    rng = TimeRange(start_us=day, end_us=day + _DAY_US)
    reading = StorageService(backend="real")
    await reading.start(_ctx(settings))
    try:
        back = await reading.market_data.read_trades("BTCUSDT", rng)
        assert sorted(r.trade_id for r in back) == sorted(r.trade_id for r in rows)
        run = await reading.cold.export_partition("BTCUSDT", StreamKind.TRADES, rng)
        assert run.row_count == len(rows)
        assert await reading.cold.verify_checksums(run)
        listed = await reading.cold.list_manifest("BTCUSDT", StreamKind.TRADES)
        assert run.run_id in {m.run_id for m in listed}
    finally:
        await reading.stop(grace_s=_GRACE_S)
