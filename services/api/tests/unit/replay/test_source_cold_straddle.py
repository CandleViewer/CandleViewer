"""Ticket AC 2 and the DoD digest on a real cold tier (E26-T02).

The corpus is generated, not recorded: `_replay_rows` builds two hours of trades and book deltas
shaped as QuestDB stores them. The production exporter writes it to Parquet, as roll-off does,
and `source_tier="auto"` routes on those real manifests (ADR-0035 decision 4). An archived window
whose rows are gone from QuestDB replays from Parquet byte-identically to a QuestDB read, matching
the committed digest. A window straddling the archive edge is refused before any read.
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
    SourceTier,
)
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import event_from_row
from candleviewer.storage.testing import (
    InMemoryRecordedTier,
    StaticArchiveCoverage,
    StaticGapReader,
)
from tests.unit.replay._events import digest
from tests.unit.storage.cold._replay_rows import H0, HOUR, SYMBOL, MemHotSource, generated_rows

#: SHA-256 of the canonical replay of `generated_rows()` (840 events). A change here means the
#: replay order or the stored-row mapping changed, which is a determinism break (C-2.15).
EXPECTED_DIGEST = "6d9a1f9fdd93f42eae63d4f7b8f3f68bc4e1a8de02ffa3f7375b9fed46056de6"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
STREAMS = (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA)
HOURS = [TimeRange(start_us=H0 + h * HOUR, end_us=H0 + (h + 1) * HOUR) for h in (0, 1)]


def _request(tier: SourceTier) -> ReplayRequest:
    return ReplayRequest.model_validate(
        {
            "symbols": (SYMBOL,),
            "streams": STREAMS,
            "start": EPOCH + timedelta(microseconds=H0),
            "end": EPOCH + timedelta(microseconds=H0 + 2 * HOUR),
            "source_tier": tier,
        }
    )


async def _archived(root: Path, hours: list[TimeRange]) -> ParquetRecordedReader:
    """Export `hours` with the production exporter: real part files and manifests."""
    registry = DatasetRegistry(root)
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource(generated_rows()))
    for hour in hours:
        await exporter.export_partition(SYMBOL, StreamKind.TRADES, hour)
        label = f"{(hour.start_us - H0) // HOUR:02d}"
        await exporter.export_partition(
            SYMBOL, StreamKind.ORDERBOOK_DELTA, hour, partition_extra={"hour": label}
        )
    return ParquetRecordedReader(registry)


def _hot(window: TimeRange) -> InMemoryRecordedTier:
    return InMemoryRecordedTier(
        event_from_row(stream, row)
        for stream, rows in generated_rows().items()
        for row in rows
        if window.start_us <= int(str(row["ts"])) < window.end_us
    )


async def _replay(source: ReplaySource) -> list[ReplayItem]:
    async with source:
        return [item async for item in source]


async def test_an_archived_window_dropped_from_questdb_replays_to_the_committed_digest(
    tmp_path: Path,
) -> None:
    cold = await _archived(tmp_path / "cold", HOURS)
    dropped = InMemoryRecordedTier()  # roll-off dropped both hours from QuestDB
    archived = ReplayTiers(hot=dropped, cold=cold, coverage=cold, gaps=StaticGapReader())
    everything = _hot(TimeRange(start_us=H0, end_us=H0 + 2 * HOUR))
    single = ReplayTiers(
        hot=everything, cold=everything, coverage=StaticArchiveCoverage(), gaps=StaticGapReader()
    )
    windows = ReadAheadConfig(window_us=7 * 60_000_000)  # read windows cross the hour boundary

    got = await _replay(ReplaySource(_request("auto"), archived, config=windows))
    want = await _replay(ReplaySource(_request("questdb"), single))

    assert len(got) == 840 and dropped.reads == 0
    assert digest(got) == digest(want) == EXPECTED_DIGEST


async def test_a_window_straddling_the_archive_edge_is_refused_before_any_read(
    tmp_path: Path,
) -> None:
    cold = await _archived(tmp_path / "cold", HOURS[:1])
    still_hot = _hot(HOURS[1])
    tiers = ReplayTiers(hot=still_hot, cold=cold, coverage=cold, gaps=StaticGapReader())

    with pytest.raises(ReplayTierStraddle) as raised:
        await _replay(ReplaySource(_request("auto"), tiers))

    assert (raised.value.stream, raised.value.archived) == (StreamKind.TRADES, (HOURS[0],))
    assert still_hot.reads == 0
