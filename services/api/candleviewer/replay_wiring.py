"""Composition of the replay read path (E26-T02).

Turns settings into the `ReplayTiers` a `ReplaySource` reads through and the `ReadAheadConfig`
that bounds it. QuestDB is read over one lazily opened, lock-serialised PGWire connection, and
Parquet through the `CV_COLD_ROOT` registry. The Parquet reader is also the manifest coverage
that `source_tier="auto"` routes on (never the roll-off watermark), and gaps come from
`recording_gaps`. Each reader's deadline sits below the merge's, so a slow read fails typed in
its tier first. Only on the `real` storage backend: the replay session service (E26-T01/T05)
builds the tiers once and opens one `ReplaySource` per session.
"""

from __future__ import annotations

from candleviewer.replay import ReadAheadConfig, ReplayTiers
from candleviewer.settings import Settings
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.questdb.recorded_reader import QuestDbRecordedReader
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.recorded import RecordingGapReader


def readahead_config(settings: Settings) -> ReadAheadConfig:
    """`ReadAheadConfig` from `CV_REPLAY_READAHEAD_EVENTS`, `CV_REPLAY_READAHEAD_BYTES` and
    `CV_REPLAY_MEMORY_CEILING_BYTES`."""
    return ReadAheadConfig(
        readahead_events=settings.replay_readahead_events,
        readahead_bytes=settings.replay_readahead_bytes,
        memory_ceiling_bytes=settings.replay_memory_ceiling_bytes,
    )


def build_replay_tiers(settings: Settings, gaps: RecordingGapReader | None) -> ReplayTiers | None:
    """The real storage ports, or `None` off the `real` backend or without a gap reader."""
    if settings.storage_backend != "real" or gaps is None:
        return None
    host, _, port = settings.questdb_pg.partition(":")
    pg = LazyPgWire(
        host,
        int(port or 8812),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
    )
    cold = ParquetRecordedReader(DatasetRegistry(settings.parquet_root))
    return ReplayTiers(hot=QuestDbRecordedReader(pg), cold=cold, coverage=cold, gaps=gaps)
