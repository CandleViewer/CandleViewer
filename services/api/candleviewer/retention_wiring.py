"""Composition of the recorder `RetentionManager` (E16-T06).

Maps the storage adapters (`storage.cold.retention_ops`) onto the recorder's ports — `storage`
may not import `recorder` (import-linter M10), so this top-level module bridges them, exactly
like `rolloff_wiring.py`. Only on the `real` storage backend; the nightly loop is scheduled
behind `retention_enabled` (C-4.13, default off).

Policy facts come from Postgres (`recorded_symbols`, `retention_policies`): `retain_days` is the
hot window (as E16-T05's roll-off reads it); the total horizon is the §7 matrix seed's
`cold_days` per stream (no column for it yet — the policy-write API is E16-T08).
`applies_to_pinned` has no column either, so policy runs never touch pinned data; the only path
that can is the step-up purge with `include_pinned`.

Replay/backtest leases: `replay_sessions` does not exist yet (E26). Until it lands the lease
check reads an empty set — the same documented posture as the compactor idle guard.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa

from candleviewer.recorder.retention import (
    ColdPartition,
    HotDay,
    PolicyRow,
    RetentionConfig,
    RetentionManager,
)
from candleviewer.recorder.rolloff import AuditEmitter
from candleviewer.settings import Settings
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.retention_ops import (
    ColdRetentionStore,
    FileRetentionCheckpoint,
    QuestDbRetentionHotStore,
)
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.models import StreamKind
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.retention.locks import PgAdvisoryRunLock
from candleviewer.storage.retention.policy import load_defaults

#: Audit actor for every reaper record (C-2.9): a system principal, never a user.
RETENTION_ACTOR = "system:retention"

_SYMBOLS = sa.text(
    "SELECT symbol::text AS symbol, pinned FROM recorded_symbols WHERE removed_at IS NULL"
)
_POLICIES = sa.text(
    "SELECT scope, symbol::text AS symbol, stream::text AS stream, retain_days "
    "FROM retention_policies WHERE enabled"
)


class SystemRetentionAudit:
    """`AuditPort` over the hash-chained `AuditWriter.emit`, as `system:retention`."""

    def __init__(self, emitter: AuditEmitter) -> None:
        self._emitter = emitter

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        await self._emitter.emit(
            action,
            actor_label=RETENTION_ACTOR,
            object_kind="recorded_data",
            object_label=f"{detail.get('stream', '')}:{detail.get('partition', '')}",
            after_state=dict(detail),
        )


class PgRetentionFacts:
    """Read-only facts; the pin check is a fresh query on every call (never cached)."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational
        self._cold_days = {r.stream.value: r.cold_days for r in load_defaults()}

    async def _all(self, stmt: sa.TextClause) -> list[dict[str, Any]]:
        async with self._rel.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt)).mappings().all()
            await uow.commit()
        return [dict(r) for r in rows]

    async def symbols(self) -> list[str]:
        return sorted(str(r["symbol"]) for r in await self._all(_SYMBOLS))

    async def pinned(self) -> set[str]:
        return {str(r["symbol"]) for r in await self._all(_SYMBOLS) if r["pinned"]}

    async def policies(self) -> Mapping[tuple[str | None, str], PolicyRow]:
        out: dict[tuple[str | None, str], PolicyRow] = {}
        for r in await self._all(_POLICIES):
            stream = str(r["stream"])
            symbol = None if r["scope"] == "default" else str(r["symbol"])
            total = self._cold_days.get(stream)
            out[(symbol, stream)] = PolicyRow(symbol, stream, int(r["retain_days"]), total)
        return out


class _Hot:
    def __init__(self, store: QuestDbRetentionHotStore) -> None:
        self._s = store

    async def days(self, stream: StreamKind, before_us: int) -> list[HotDay]:
        return [
            HotDay(d.start_us, d.rows_by_symbol, d.bytes)
            for d in await self._s.days(stream, before_us)
        ]

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> bool:
        return await self._s.drop_day(stream, day_start_us)


class _Cold:
    def __init__(self, store: ColdRetentionStore) -> None:
        self._s = store

    async def partitions(self, symbol: str, stream: StreamKind) -> list[ColdPartition]:
        return [
            ColdPartition(p.key, p.start_us, p.end_us, p.rows, p.bytes)
            for p in await self._s.partitions(symbol, stream)
        ]

    async def delete(self, symbol: str, stream: StreamKind, key: str) -> bool:
        return await self._s.delete(symbol, stream, key)


def build_retention_manager(
    settings: Settings,
    audit: AuditEmitter,
    relational: SqlAlchemyRelationalRepository | None,
) -> RetentionManager | None:
    if settings.storage_backend != "real" or relational is None:
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
    return RetentionManager(
        hot=_Hot(QuestDbRetentionHotStore(pg)),
        cold=_Cold(ColdRetentionStore(registry)),
        facts=PgRetentionFacts(relational),
        watermarks=FileWatermarkStore(registry, events),
        audit=SystemRetentionAudit(audit),
        events=events,
        # Cross-process: one pass / purge per volume (pg_try_advisory_lock on a held connection).
        lock=PgAdvisoryRunLock(relational.engine),
        checkpoint=FileRetentionCheckpoint(registry),
        config=RetentionConfig(
            hard_default=(settings.recorder_hot_days, settings.recorder_retention_days)
        ),
    )
