"""Composition of the recorder `RetentionManager` (E16-T06).

Maps the storage adapters (`storage.cold.retention_ops`) onto the recorder's ports — `storage`
may not import `recorder` (import-linter M10), so this top-level module bridges them, exactly
like `rolloff_wiring.py`. Only on the `real` storage backend; the nightly loop is scheduled
behind `retention_enabled` (C-4.13, default off).

Policy facts come from Postgres (`recorded_symbols`, `retention_policies`): by a row's `action`
(`read_policy_row`, the roll-off's reading too, #2188) `retain_days` is the hot window, under the
§7 matrix seed's total horizon per stream (shipped in-package, `recorder/retention_defaults.py`; no
column for it yet — the policy-write API is E16-T08), or for `drop` the total horizon itself. A
build failure or invalid settings return `None` (purge -> 503); the API never fails to boot
because of recorder config.
`applies_to_pinned` has no column either, so policy runs never touch pinned data; the only path
that can is the step-up purge with `include_pinned`.

Replay guard (G7, #2674): data an open replay session reads is never dropped, compacted or
downsampled. `ReplayRetentionGuard` asks `replay_sessions.live_covering` (every state but
`destroyed`, created within `CV_REPLAY_MAX_LIFETIME_S`) and backs the recorder lease
(`PgRetentionFacts.lease`, any replayable stream of the symbol), `replay_session_for` (the E07
reaper's port, per stream) and the cold-tier idle guards (the partition path's stream, symbol
and range). A read that fails or times out keeps the data this pass (`GUARD_UNVERIFIED`), logs
ids only and counts `replay_retention_guard_errors_total{where}`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast

import sqlalchemy as sa
import structlog

from candleviewer.observability.metrics import Counter
from candleviewer.recorder.retention import (
    ColdPartition,
    HotDay,
    PolicyRow,
    RetentionConfig,
    RetentionManager,
)
from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS, canonical_stream
from candleviewer.recorder.rolloff import AuditEmitter
from candleviewer.settings import Settings
from candleviewer.storage.cold.compactor import Compactor, IdleGuard
from candleviewer.storage.cold.layout import DatasetRegistry, stream_dir_name
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.retention_ops import (
    ArchiveRowVerifier,
    ColdRetentionStore,
    FileRetentionCheckpoint,
    QuestDbRetentionHotStore,
    partition_range,
)
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.models import StreamKind
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.replay_sessions import ALL_REPLAY_STREAMS
from candleviewer.storage.repositories.replay_sessions_sqlalchemy import (
    SqlAlchemyReplaySessionRepository,
)
from candleviewer.storage.retention.locks import PgAdvisoryRunLock
from candleviewer.storage.retention.policy import read_policy_row
from candleviewer.storage.retention.ports import Partition

#: Audit actor for every reaper record (C-2.9): a system principal, never a user.
RETENTION_ACTOR = "system:retention"


def logger() -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


_SYMBOLS = sa.text(
    "SELECT symbol::text AS symbol, pinned FROM recorded_symbols WHERE removed_at IS NULL"
)
_POLICIES = sa.text(
    "SELECT scope, symbol::text AS symbol, stream::text AS stream, retain_days, "
    "action::text AS action FROM retention_policies WHERE enabled"
)


#: What the replay guard answers when it could not read the sessions: not a session id (those are
#: uuids) but never None, so every caller keeps the data this pass (fail closed, never drop blind).
GUARD_UNVERIFIED: Final = "unverified"
#: Bound on one guard decision, every stream it reads (C-2.18).
GUARD_TIMEOUT_S: Final = 10.0
GuardSite = Literal["lease", "reaper", "compaction", "downsample"]
GUARD_SITES: Final[tuple[GuardSite, ...]] = ("lease", "reaper", "compaction", "downsample")
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: On-disk stream directory -> the stream name a session stores; derived streams are absent.
_REPLAYED_DIRS: Final = {
    stream_dir_name(k): k.value for k in StreamKind if k.value in ALL_REPLAY_STREAMS
}
_ALL_DIRS: Final = frozenset(stream_dir_name(k) for k in StreamKind)

replay_retention_guard_errors_total = Counter(
    "replay_retention_guard_errors_total",
    "Replay retention guard reads that failed; the partition was kept this pass.",
    ["where"],
)
for _site in GUARD_SITES:
    replay_retention_guard_errors_total.labels(where=_site)


class CoveringSessions(Protocol):
    async def live_covering(
        self, symbol: str, stream: str, lo: datetime, hi: datetime, *, created_after: datetime
    ) -> str | None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _partition_target(root: Path, partition_dir: Path) -> tuple[str, str, int, int] | None:
    """`(symbol, stream, lo_us, hi_us)` of a cold partition directory, or None for a stream no
    session replays. Raises `ValueError` for a path it cannot read (the guard keeps that)."""
    parts = partition_dir.relative_to(root).parts
    if not parts or parts[0] not in _ALL_DIRS:
        raise ValueError("not a stream partition")
    stream = _REPLAYED_DIRS.get(parts[0])
    if stream is None:
        return None
    values = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
    rng, symbol = partition_range(values), values.get("symbol")
    if rng is None or not symbol:
        raise ValueError("no symbol or time key")
    return symbol, stream, rng[0], rng[1]


class ReplayRetentionGuard:
    """G7: the id of an open replay session reading `symbol` over `[lo_us, hi_us)`, else None."""

    def __init__(
        self,
        sessions: CoveringSessions,
        *,
        max_lifetime: timedelta,
        clock: Callable[[], datetime] = _utc_now,
        timeout_s: float = GUARD_TIMEOUT_S,
    ) -> None:
        self._sessions, self._lifetime = sessions, max_lifetime
        self._clock, self._timeout_s = clock, timeout_s

    async def covering(
        self, symbol: str, streams: Iterable[str], lo_us: int, hi_us: int, *, site: GuardSite
    ) -> str | None:
        try:
            now = self._clock()
            if now.tzinfo is None:
                raise ValueError("the guard clock must be tz-aware UTC")
            born = now - self._lifetime  # G6: an older session is destroyed by the sweep
            lo, hi = _EPOCH + timedelta(microseconds=lo_us), _EPOCH + timedelta(microseconds=hi_us)
            async with asyncio.timeout(self._timeout_s):
                for stream in streams:
                    got = await self._sessions.live_covering(
                        symbol, stream, lo, hi, created_after=born
                    )
                    if got is not None:
                        return got
        except Exception as exc:  # CancelledError is not an Exception: it propagates
            return self._unverified(site, symbol, type(exc).__name__)
        return None

    def _unverified(self, site: GuardSite, symbol: str, error: str) -> str:
        replay_retention_guard_errors_total.labels(where=site).inc()
        logger().warning(
            "replay_retention_guard_failed_closed", where=site, symbol=symbol, error=error
        )
        return GUARD_UNVERIFIED

    def partition_guard(self, root: Path, *, site: GuardSite) -> IdleGuard:
        """The compactor / downsampler `IdleGuard` over partition directories under `root`."""

        async def guard(partition_dir: Path) -> str | None:
            try:
                target = _partition_target(root, partition_dir)
            except ValueError:
                return self._unverified(site, "", "UnreadablePartitionPath")
            if target is None:
                return None
            symbol, stream, lo_us, hi_us = target
            return await self.covering(symbol, (stream,), lo_us, hi_us, site=site)

        return guard


def replay_retention_guard(
    settings: Settings, relational: SqlAlchemyRelationalRepository
) -> ReplayRetentionGuard:
    return ReplayRetentionGuard(
        SqlAlchemyReplaySessionRepository(relational),
        max_lifetime=timedelta(seconds=settings.replay_max_lifetime_s),
    )


def cold_idle_guard(
    settings: Settings,
    relational: SqlAlchemyRelationalRepository | None,
    root: Path,
    *,
    site: GuardSite,
) -> IdleGuard | None:
    """None without Postgres: replay sessions exist only there (`_attach_replay_sessions`)."""
    if relational is None:
        return None
    return replay_retention_guard(settings, relational).partition_guard(root, site=site)


def build_compactor(
    settings: Settings,
    relational: SqlAlchemyRelationalRepository | None,
    registry: DatasetRegistry,
) -> Compactor:
    """The weekly compaction's `Compactor` (E16-T05), behind the replay guard."""
    guard = cold_idle_guard(settings, relational, registry.root, site="compaction")
    events = LoggingSystemEventSink()
    return Compactor(events=events) if guard is None else Compactor(guard, events=events)


class SystemRetentionAudit:
    """`AuditPort` over the hash-chained `AuditWriter.emit`, as `system:retention`."""

    def __init__(self, emitter: AuditEmitter) -> None:
        self._emitter = emitter

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        phase = detail.get("phase")
        # Plain values of `AuditOutcome`/`Severity` (StrEnum, validated by `AuditEmission`):
        # this module may not import `audit` (C-3.3 write-only boundary).
        outcome = "failure" if phase == "failed" else "success"
        await self._emitter.emit(
            action,
            actor_label=RETENTION_ACTOR,
            outcome=outcome,
            severity="error" if phase == "failed" else "info",
            reason="intent" if phase == "intent" else None,
            object_kind="recorded_data",
            object_label=f"{detail.get('stream', '')}:{detail.get('partition', '')}",
            after_state=dict(detail),
        )


class PgRetentionFacts:
    """Read-only facts; the pin check is a fresh query on every call (never cached)."""

    def __init__(
        self, relational: SqlAlchemyRelationalRepository, guard: ReplayRetentionGuard
    ) -> None:
        self._rel, self._guard = relational, guard
        self._warned: set[tuple[str | None, str, int]] = set()

    async def replay_session_for(self, part: Partition) -> str | None:
        """`storage.retention.ports.RetentionFacts.replay_session_for` (G7): an open session
        replaying `part`'s stream of its symbol over its range; None for a derived stream."""
        if part.stream.value not in ALL_REPLAY_STREAMS:
            return None
        rng = part.range
        return await self._guard.covering(
            part.symbol, (part.stream.value,), rng.start_us, rng.end_us, site="reaper"
        )

    async def lease(self, symbol: str, lo_us: int, hi_us: int) -> str | None:
        """The recorder `LeaseCheck`: held while a session replays ANY stream of `symbol` over
        the range (E16's check has no stream, so it keeps the symbol's other streams too)."""
        return await self._guard.covering(symbol, ALL_REPLAY_STREAMS, lo_us, hi_us, site="lease")

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
            stream = canonical_stream(str(r["stream"]))  # DB `funding` -> `funding_rates`
            symbol = None if r["scope"] == "default" else str(r["symbol"])
            seeded = STREAM_DEFAULTS.get(stream)
            if seeded is None:
                continue  # unknown stream: no row -> resolution keeps it forever
            # By the row's `action` (`read_policy_row`, as the roll-off reads it) `retain_days` is
            # the total horizon (`drop`), or the hot window under the §7 total (never shorter).
            reading = read_policy_row(str(r["action"]), int(r["retain_days"]))
            total = reading.total_days
            if total is None:
                total = seeded[1] if seeded[1] is None else max(seeded[1], reading.hot_days)
            elif seeded[1] is None and (symbol, stream, total) not in self._warned:
                # §7 keeps this stream forever: the row is its first delete, by intent. Said once.
                self._warned.add((symbol, stream, total))
                logger().warning(
                    "retention_drop_finite_total", symbol=symbol, stream=stream, retain_days=total
                )
            out[(symbol, stream)] = PolicyRow(symbol, stream, reading.hot_days, total)
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
    hot, total = settings.recorder_hot_days, settings.recorder_retention_days
    if not 1 <= hot <= total <= 3650:  # review M3: refuse, never build a misconfigured reaper
        logger().error("retention_manager_not_built", reason="invalid_recorder_retention_days")
        return None
    try:
        return _build(settings, audit, relational)
    except Exception as exc:  # review H3: recorder config must never take the API down
        logger().error("retention_manager_not_built", error=type(exc).__name__)
        return None


def _build(
    settings: Settings, audit: AuditEmitter, relational: SqlAlchemyRelationalRepository
) -> RetentionManager:
    host, _, port = settings.questdb_pg.partition(":")
    pg = LazyPgWire(
        host,
        int(port or 8812),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
        name="retention",
    )
    registry = DatasetRegistry(settings.parquet_root)
    events = LoggingSystemEventSink()
    facts = PgRetentionFacts(relational, replay_retention_guard(settings, relational))
    return RetentionManager(
        hot=_Hot(QuestDbRetentionHotStore(pg)),
        cold=_Cold(ColdRetentionStore(registry)),
        facts=facts,
        verifier=ArchiveRowVerifier(pg, registry),
        watermarks=FileWatermarkStore(registry, events),
        audit=SystemRetentionAudit(audit),
        events=events,
        # Cross-process: one pass / purge per volume (pg_try_advisory_lock on a held connection).
        lock=PgAdvisoryRunLock(relational.engine),
        checkpoint=FileRetentionCheckpoint(registry),
        lease=facts.lease,  # G7: an open replay session's data is skipped, retried next pass
        config=RetentionConfig(
            hard_default=(settings.recorder_hot_days, settings.recorder_retention_days)
        ),
    )
