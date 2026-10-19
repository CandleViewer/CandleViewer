"""Composition of the replay read path (E26-T02).

Turns settings into the `ReplayTiers` a `ReplaySource` reads through and the `ReadAheadConfig`
that bounds it. QuestDB is read over one lazily opened, lock-serialised PGWire connection, and
Parquet through the `CV_PARQUET_ROOT` registry. The Parquet reader is also the manifest coverage
that `source_tier="auto"` routes on (never the roll-off watermark), and gaps come from
`recording_gaps`. Each reader's deadline sits below the merge's, so a slow read fails typed in
its tier first. Only on the `real` storage backend: the replay session service (E26-T01/T05)
builds the wiring once per process, so every session shares the cold reader's verified-file
cache and scan slots, opens one `ReplaySource` per session over `ReplayWiring.tiers`, and calls
`ReplayWiring.aclose()` when the app stops, which closes the QuestDB connection and the cold
reader's scan pool.
"""

from __future__ import annotations

from dataclasses import dataclass

from candleviewer.replay import ReadAheadConfig, ReplayTiers
from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Settings
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


@dataclass(frozen=True, slots=True)
class ReplayWiring:
    """The tiers a `ReplaySource` reads through, and what they hold open: one QuestDB
    connection and the cold reader's scan pool, both released by `aclose()`."""

    tiers: ReplayTiers
    pg: LazyPgWire
    cold: ParquetRecordedReader

    async def aclose(self) -> None:
        """At app stop: the cold reader refuses new scans and its queued ones fail typed (a
        running scan finishes, or is stopped by its read), then the QuestDB connection closes."""
        self.cold.shutdown()
        await self.pg.close()


def build_replay_wiring(settings: Settings, gaps: RecordingGapReader | None) -> ReplayWiring | None:
    """The real storage ports, or `None` off the `real` backend or without a gap reader."""
    if settings.storage_backend != "real" or gaps is None:
        return None
    host, _, port = settings.questdb_pg.partition(":")
    pg = LazyPgWire(
        host,
        int(port or QUESTDB_PG_DEFAULT_PORT),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
    )
    cold = ParquetRecordedReader(DatasetRegistry(settings.parquet_root))
    tiers = ReplayTiers(hot=QuestDbRecordedReader(pg), cold=cold, coverage=cold, gaps=gaps)
    return ReplayWiring(tiers=tiers, pg=pg, cold=cold)
