"""E26-T02 ticket AC 2 and DoD on real QuestDB plus Parquet (docker required).

The generated two-hour corpus goes to QuestDB over ILP; `replay_wiring` composes the real tiers,
and `auto` reads one tier chosen from the cold manifests (ADR-0035 decision 4): (1) nothing
archived reads QuestDB; (2) the first hour exported is a straddle, refused; (3) both hours
exported and their day dropped by roll-off's own `drop_day`, the watermark never advanced
(#2347), must read Parquet, where watermark routing would read a hole. Digests match the unit
test's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from candleviewer.replay import (
    ReadAheadConfig,
    ReplayItem,
    ReplayRequest,
    ReplaySource,
    ReplayTiers,
    ReplayTierStraddle,
)
from candleviewer.replay_wiring import ReplayWiring, build_replay_wiring
from candleviewer.settings import Settings
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.questdb_source import QuestDbHotTierSource
from candleviewer.storage.cold.rolloff_ops import QuestDbHotPartitions
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.testing import StaticGapReader
from tests.integration.storage import test_questdb_hot_tier as hot_tier
from tests.unit.replay._events import digest
from tests.unit.replay.test_source_cold_straddle import EXPECTED_DIGEST
from tests.unit.storage.cold._replay_rows import H0, HOUR, SYMBOL, generated_rows

pytestmark = pytest.mark.integration

#: The QuestDB container fixture the hot-tier suite already maintains.
questdb_container = hot_tier.questdb_container

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
STREAMS = (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA)
TABLES = {StreamKind.TRADES: "trades", StreamKind.ORDERBOOK_DELTA: "orderbook_deltas"}
REQUEST = ReplayRequest.model_validate(
    {
        "symbols": (SYMBOL,),
        "streams": STREAMS,
        "start": EPOCH + timedelta(microseconds=H0),
        "end": EPOCH + timedelta(microseconds=H0 + 2 * HOUR),
    }
)


async def _replay(tiers: ReplayTiers) -> list[ReplayItem]:
    config = ReadAheadConfig(window_us=7 * 60_000_000)  # read windows cross the hour boundary
    async with ReplaySource(REQUEST, tiers, config=config) as source:
        return [item async for item in source]


async def _export(exporter: ColdExporter, hour: int) -> None:
    rng = TimeRange(start_us=H0 + hour * HOUR, end_us=H0 + (hour + 1) * HOUR)
    await exporter.export_partition(SYMBOL, StreamKind.TRADES, rng)
    await exporter.export_partition(
        SYMBOL, StreamKind.ORDERBOOK_DELTA, rng, partition_extra={"hour": f"{hour:02d}"}
    )


@pytest.mark.asyncio
async def test_auto_reads_one_tier_by_manifest_coverage_on_real_questdb_and_parquet(
    questdb_container: tuple[str, int, int],
    tmp_path: Path,
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await hot_tier._connect(host, pg_port)
    wiring: ReplayWiring | None = None
    try:
        await run_migrations(hot_tier._AsyncpgExecutor(conn), hot_tier.DDL_DIR)
        rows = generated_rows()
        # A later day keeps 2026-10-01 off the active partition, as for roll-off's old days.
        later = {s: rows[s][0] | {"symbol": "ETHUSDT", "ts": H0 + 24 * HOUR} for s in TABLES}
        writer = IlpWriter(hot_tier._AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
        await writer.start()
        for stream, table in TABLES.items():
            await writer.write_rows(table, [*rows[stream], later[stream]], "ts")
        await writer.stop()
        await hot_tier.wait_for_row_count(conn, "trades", 361)
        await hot_tier.wait_for_row_count(conn, "orderbook_deltas", 481)
        settings = Settings(  # type: ignore[call-arg]  # pydantic-settings kwarg
            _env_file=None,
            storage_backend="real",
            questdb_pg=f"{host}:{pg_port}",
            parquet_root=str(tmp_path / "cold"),
        )
        DatasetRegistry(settings.parquet_root).ensure_tree()
        wiring = build_replay_wiring(settings, StaticGapReader())
        assert wiring is not None
        tiers = wiring.tiers
        pg = hot_tier._AsyncpgExecutor(conn)
        exporter = ColdExporter(DatasetRegistry(settings.parquet_root), QuestDbHotTierSource(pg))

        from_questdb = await _replay(tiers)  # 1. nothing archived yet
        await _export(exporter, 0)
        with pytest.raises(ReplayTierStraddle):  # 2. half archived: never stitched
            await _replay(tiers)
        await _export(exporter, 1)
        for stream, table in TABLES.items():  # 3. the day leaves QuestDB, watermark untouched
            await QuestDbHotPartitions(pg).drop_day(stream, H0)
            await hot_tier.wait_for_row_count(conn, table, 1)
        from_parquet = await _replay(tiers)

        assert len(from_questdb) == len(from_parquet) == 840
        assert digest(from_questdb) == digest(from_parquet) == EXPECTED_DIGEST
    finally:
        if wiring is not None:
            await wiring.aclose()
        await conn.close()
