"""Composition of the nightly roll-off (E16-T05).

Builds `RollOffJob` with its real adapters: the QuestDB PGWire hot partitions,
the cold archiver over the existing exporter, the file watermark store, the
`retention_policies` resolver and the `system:rolloff` audit adapter over the
hash-chained `AuditWriter`. Only on the `real` storage backend; the nightly
loop is scheduled separately behind `retention_enabled` (C-4.13).
"""

from __future__ import annotations

from candleviewer.recorder.rolloff import AuditEmitter, RollOffJob, SystemAuditAdapter
from candleviewer.settings import Settings
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.questdb_source import QuestDbHotTierSource
from candleviewer.storage.cold.rolloff_ops import ColdArchiver, QuestDbHotPartitions
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.models import StreamKind
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.retention.locks import InProcessRunLock


def build_rolloff_job(
    settings: Settings,
    audit: AuditEmitter,
    recorder_repo: SqlAlchemyRecorderRepository | None,
) -> RollOffJob | None:
    if settings.storage_backend != "real" or recorder_repo is None:
        return None
    host, _, port = settings.questdb_pg.partition(":")
    pg = LazyPgWire(
        host,
        int(port or 8812),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
    )
    registry = DatasetRegistry(settings.parquet_root)
    events = LoggingSystemEventSink()
    repo = recorder_repo

    async def hot_days(symbol: str, stream: StreamKind) -> int | None:
        return await repo.resolve_policy(symbol, stream.value)

    return RollOffJob(
        hot=QuestDbHotPartitions(pg),
        archiver=ColdArchiver(registry, QuestDbHotTierSource(pg), events=events),
        watermarks=FileWatermarkStore(registry),
        hot_days=hot_days,
        audit=SystemAuditAdapter(audit),
        events=events,
        lock=InProcessRunLock(),
    )
