"""Composition root of the statechart persistence stores (E50-T62 #3793): adapters from the
statechart's DTOs to the M10 row stores of `statechart_sqlalchemy`, and back.

`storage` may not import `statechart` (C-3.4; the `SqlAlchemyAuditRepository` precedent), so this
module, which imports both, maps `MachineKey`, `JournalEntry`, `SealedSnapshot` with its `Seal`
and `MachineEventRow` to and from the store records; the dependency graph gains no edge. Nothing
here is wired yet and nothing has a `start()`: E50-T63 builds `Persister`, `Restorer` and the sink
over these adapters.

- `SnapshotAdapter` is the one snapshot adapter: `persistence.SnapshotRepo.write_snapshot`,
  `replay.sessions_service.SnapshotSource.load` and `admin.inspector.SnapshotStore.snapshots`,
  through one row-to-envelope function, `envelope_of`, whose key comes from the three key columns
  (the seal binds all three byte for byte), never from the blob. Before any statement,
  `write_snapshot` refuses an empty `entity_id` (`''` and the kind are different keys), then an
  envelope sealed for another key than the row's (#3082): `SnapshotKeyMismatchError` names the
  field. It never seals or verifies; `Restorer` does (CV-C53).
- `JournalRowsAdapter` is the `persistence.JournalRowStore` under `RowStoreDrainJournal`: the
  append hands back the store's conflict report, and `present` names the `send_id`s with a row.
- `EventsAdapter` maps `MachineEventRow`. `occurred_at` must be the audit plugin's ISO-8601 UTC
  string, so that `row_digest` over a row read back equals the `row_hash` it was stored with; one
  that would come back different is refused before the store sees the batch.
- `FaultRows` (E50-T63) is `PersistAudit` and `RestoreAudit` over the `machine_events` sink: one
  `phase="fault"` row in the machine's own chain per refusal, drain error or quarantine (24 §17.6
  "Faults"). It never raises: a raising `drain_error` would lose the drained events and a raising
  `quarantine` would mask the refusal and skip its page, so a row it cannot write is logged
  CRITICAL and paged P1 by the writer itself.

The persistence bundle (E50-T63): `build_statechart_persistence` returns a `StatechartPersistence`
on the real backend when `HmacKeys` are injected, else `None`, so persist, restore and the
inspector's snapshots stay unwired and fail closed until a key provider exists (a plan gap,
#2701). It holds the `statechart` pool and its three stores, the WAL-backed sink (reached through
`admin.wiring`: M19 is not importable here, C-3.3), one process-wide `Persister` whose sealer
looks the chart up by `key.machine_kind`, one `Restorer` per lane (`prepare` = the sink's `seed`,
`plugins` = the `cv_plugins` triple with the sink's head and the audit redactor), the one
`ChainTripLatch` with `LatchAdmission` over it for the gateways, the `PagerAdapter` over
`LogPager`, the fault-row writers and `PersistOps`, the two persistence metric families. The
lifespan starts it before `Supervisor.start_all` and stops it last, after `stop_all`.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Final, Protocol

import structlog

from candleviewer.admin.inspector import SnapshotRow, SnapshotStore
from candleviewer.admin.wiring import (
    MachineEventSinkHandle,
    MachineEventSinkMetrics,
    build_machine_event_sink,
    system_event_redactor,
)
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.replay.sessions_service import SnapshotSource
from candleviewer.settings import Settings
from candleviewer.statechart.config import LANES, Lane
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import ADMITTED, REASON_DEGRADED, Decision
from candleviewer.statechart.persistence import (
    PAGE_TIMEOUT_S,
    SEAL_LAYOUT_V,
    ChainSeedError,
    ChainTripLatch,
    DegradedLatchError,
    DrainJournal,
    HmacKeys,
    JournalConflict,
    JournalEntry,
    JournalLane,
    JournalRowStore,
    MachineKey,
    OpsRecorder,
    Pager,
    PersistAudit,
    Persister,
    PluginsFactory,
    RestoreAudit,
    Restorer,
    RowStoreDrainJournal,
    Seal,
    SealedSnapshot,
    Sealer,
    SnapshotRepo,
    seal,
)
from candleviewer.statechart.plugins import (
    CvAuditPlugin,
    CvErrorHooks,
    CvMetricsPlugin,
    LogPager,
    cv_plugins,
)
from candleviewer.statechart.plugins._base import Pager as AlertPager
from candleviewer.statechart.plugins._base import Severity
from candleviewer.statechart.plugins.audit import GENESIS_HASH, MachineEventRow, Phase, row_digest
from candleviewer.statechart.registry import Registry
from candleviewer.statechart.schema import canonical_json
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import (
    EventRecord,
    JournalConflictRecord,
    JournalRecord,
    SnapshotRecord,
    SqlAlchemyEventStore,
    SqlAlchemyJournalStore,
    SqlAlchemySnapshotStore,
)

_KEY_FIELDS: Final = tuple(f.name for f in fields(MachineKey))
_LANES: Final[dict[str, JournalLane]] = {"priority": "priority", "inbox": "inbox"}
_PHASES: Final[dict[str, Phase]] = {"ahead": "ahead", "commit": "commit", "fault": "fault"}


class SnapshotKeyMismatchError(ValueError):
    """`write_snapshot` refused, before any statement, an envelope for another key (#3082)."""

    def __init__(self, field: str, problem: str) -> None:
        super().__init__(f"snapshot write refused: {problem} (field {field})")
        self.field = field


def envelope_of(record: SnapshotRecord) -> SealedSnapshot:
    """A row's envelope: the key from its three key columns, the tag as lowercase hex."""
    return SealedSnapshot(
        key=MachineKey(record.machine_kind, record.entity_id, record.env),
        version=record.lib_snapshot_ver,
        machine_hash=record.machine_hash,
        snapshot=record.snapshot,
        seal=Seal(key_id=record.hmac_key_id, tag=record.hmac_tag.hex()),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _seal_columns(seal: Any) -> tuple[str, bytes]:
    """`hmac_key_id` and the 32 raw bytes of `hmac_tag`, from the envelope's seal."""
    if not isinstance(seal, Seal):
        raise TypeError("snapshot write refused: the envelope carries no HMAC seal")
    try:
        tag = bytes.fromhex(seal.tag)
    except (TypeError, ValueError):
        raise ValueError("snapshot write refused: the HMAC tag is not hex") from None
    if len(tag) != 32:
        raise ValueError("snapshot write refused: the HMAC tag is not 32 bytes")
    return seal.key_id, tag


def _record(key: MachineKey, envelope: SealedSnapshot, now: datetime) -> SnapshotRecord:
    """The row `write_snapshot` writes for `key`, or a refusal before any statement."""
    if not key.entity_id:
        raise SnapshotKeyMismatchError("entity_id", "entity_id is empty")
    for name in _KEY_FIELDS:
        if getattr(envelope.key, name, None) != getattr(key, name):
            raise SnapshotKeyMismatchError(
                name, f"{name} is not the one the envelope is sealed for"
            )
    key_id, tag = _seal_columns(envelope.seal)
    blob = envelope.snapshot
    state_ids, trips = blob.get("state_ids", []), blob.get("chain_trips", 0)
    if not isinstance(state_ids, list) or not all(isinstance(s, str) for s in state_ids):
        raise ValueError("snapshot write refused: the blob's state_ids is not a list of ids")
    if type(trips) is not int or trips < 0:
        raise ValueError("snapshot write refused: the blob's chain_trips is not a count")
    return SnapshotRecord(
        machine_kind=key.machine_kind, entity_id=key.entity_id, env=key.env,
        cv_schema_version=SEAL_LAYOUT_V, lib_snapshot_ver=envelope.version,
        machine_hash=envelope.machine_hash, snapshot=blob, hmac_key_id=key_id, hmac_tag=tag,
        state_ids=tuple(state_ids), chain_trips=trips, updated_at=now,
    )  # fmt: skip


class SnapshotRows(Protocol):
    async def upsert(self, record: SnapshotRecord) -> None: ...

    async def get(self, machine_kind: str, entity_id: str, env: str) -> SnapshotRecord | None: ...

    async def list_all(self) -> Sequence[SnapshotRecord]: ...


class JournalRows(Protocol):
    async def append(
        self, machine_kind: str, entity_id: str, env: str, records: Sequence[JournalRecord]
    ) -> Sequence[JournalConflictRecord]: ...

    async def list_unreplayed(
        self, machine_kind: str, entity_id: str, env: str
    ) -> Sequence[JournalRecord]: ...

    async def present(
        self, machine_kind: str, entity_id: str, env: str, send_ids: Sequence[str]
    ) -> frozenset[str]: ...

    async def mark_replayed(
        self, machine_kind: str, entity_id: str, env: str, send_ids: Sequence[str]
    ) -> None: ...


class EventRows(Protocol):
    async def insert_batch(self, records: Sequence[EventRecord]) -> None: ...

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str: ...

    async def read_chain(
        self, machine_kind: str, entity_id: str, env: str, *, after_seq: int = 0
    ) -> Sequence[EventRecord]: ...

    async def read_whole_chain(
        self, machine_kind: str, entity_id: str, env: str
    ) -> Sequence[EventRecord]: ...


class SnapshotAdapter:
    """`SnapshotRepo`, `SnapshotSource` and `SnapshotStore` over the snapshot store."""

    def __init__(self, store: SnapshotRows, clock: Callable[[], datetime] = _utc_now) -> None:
        self._store, self._clock = store, clock

    async def write_snapshot(self, key: MachineKey, envelope: SealedSnapshot) -> None:
        await self._store.upsert(_record(key, envelope, self._clock()))

    async def load(self, key: MachineKey) -> SealedSnapshot | None:
        record = await self._store.get(key.machine_kind, key.entity_id, key.env)
        return None if record is None else envelope_of(record)

    async def snapshots(self) -> Sequence[SnapshotRow]:
        """Every row; a singleton (`entity_id` equal to its kind) has no `entity_id`, the shape
        `admin.inspector` reads (its scope stays the default until E42-T07 binds it)."""
        return [
            SnapshotRow(
                machine_kind=r.machine_kind,
                entity_id=None if r.entity_id == r.machine_kind else r.entity_id,
                environment=r.env,
                envelope=envelope_of(r),
                updated_at=r.updated_at,
            )
            for r in await self._store.list_all()
        ]


def _lane(lane: str) -> JournalLane:
    if lane not in _LANES:
        raise ValueError("a drain journal row is on neither the priority nor the inbox lane")
    return _LANES[lane]


class JournalRowsAdapter:
    """`persistence.JournalRowStore` over the journal store: `JournalEntry.record` is `payload`."""

    def __init__(self, store: JournalRows) -> None:
        self._store = store

    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> tuple[JournalConflict, ...]:
        if not entries:
            return ()
        records = [
            JournalRecord(e.send_id, e.lane, e.ordinal, e.event_type, e.record, e.receipt_error)
            for e in entries
        ]
        conflicts = await self._store.append(key.machine_kind, key.entity_id, key.env, records)
        return tuple(JournalConflict(c.send_id, c.stamped, c.same_payload) for c in conflicts)

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        records = await self._store.list_unreplayed(key.machine_kind, key.entity_id, key.env)
        return [
            JournalEntry(
                r.send_id, _lane(r.lane), r.ordinal, r.event_type, r.payload, r.receipt_error
            )
            for r in records
        ]

    async def present(self, key: MachineKey, send_ids: Sequence[str]) -> frozenset[str]:
        if not send_ids:
            return frozenset()
        return await self._store.present(key.machine_kind, key.entity_id, key.env, send_ids)

    async def mark_replayed(self, key: MachineKey, send_ids: Sequence[str]) -> None:
        if send_ids:
            await self._store.mark_replayed(key.machine_kind, key.entity_id, key.env, send_ids)


def _occurred_at(value: str) -> datetime:
    """The audit plugin's `occurred_at`, an ISO-8601 UTC string the store hands back unchanged."""
    try:
        at: datetime | None = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        at = None
    if at is None or at.tzinfo is None or at.astimezone(UTC).isoformat() != value:
        raise ValueError("occurred_at must be ISO-8601 in UTC, as the audit plugin writes it")
    return at


def _event_record(row: MachineEventRow) -> EventRecord:
    return EventRecord(
        machine_kind=row.machine_kind, entity_id=row.entity_id, env=row.env,
        event_type=row.event_type, payload=row.payload, from_states=tuple(row.from_states),
        to_states=tuple(row.to_states), actions_run=tuple(row.actions_run), fault=row.fault,
        occurred_at=_occurred_at(row.occurred_at), phase=row.phase, prev_hash=row.prev_hash,
        row_hash=row.row_hash,
    )  # fmt: skip


def _event_row(record: EventRecord) -> MachineEventRow:
    return MachineEventRow(
        machine_kind=record.machine_kind, entity_id=record.entity_id, env=record.env,
        event_type=record.event_type, payload=record.payload,
        from_states=list(record.from_states), to_states=list(record.to_states),
        actions_run=list(record.actions_run), fault=record.fault,
        occurred_at=record.occurred_at.astimezone(UTC).isoformat(),
        phase=_PHASES[record.phase], prev_hash=record.prev_hash, row_hash=record.row_hash,
    )  # fmt: skip


class EventsAdapter:
    """`MachineEventRow`s to and from the events store, unchanged for `row_digest`."""

    def __init__(self, store: EventRows) -> None:
        self._store = store

    async def insert_batch(self, rows: Sequence[MachineEventRow]) -> None:
        records = [_event_record(row) for row in rows]  # every row checked before the store
        if records:
            await self._store.insert_batch(records)

    async def head(self, key: MachineKey) -> str:
        return await self._store.head(key.machine_kind, key.entity_id, key.env)

    async def read_chain(
        self, key: MachineKey, *, after_seq: int = 0
    ) -> list[tuple[int, MachineEventRow]]:
        """A keyset page: `(seq, row)` pairs, so the caller pages with the last `seq`."""
        page = await self._store.read_chain(
            key.machine_kind, key.entity_id, key.env, after_seq=after_seq
        )
        return [(r.seq, _event_row(r)) for r in page]

    async def chain(self, key: MachineKey) -> list[MachineEventRow]:
        """The machine's whole chain, in `seq` order (`ChainTooLongError` past the cap)."""
        records = await self._store.read_whole_chain(key.machine_kind, key.entity_id, key.env)
        return [_event_row(r) for r in records]


def _logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.statechart_wiring")


class ChainSink(Protocol):
    """The `machine_events` sink as its writers use it (`audit.machine_events.MachineEventWalSink`,
    reached through `admin.wiring`): seed a key's chain head, read it, append a row."""

    async def seed(self, key: MachineKey) -> None: ...

    def head(self, key: MachineKey) -> str | None: ...

    def append(self, row: MachineEventRow) -> None: ...


#: A fault row's `reason` is cut to this many characters.
FAULT_REASON_MAX: Final = 256


def _snapshot_digest(snapshot: Any) -> str | None:
    """The sha256 of the canonical snapshot, never the snapshot; `None` for one that has no
    canonical form (a NaN, a value JSON cannot hold)."""
    try:
        return hashlib.sha256(canonical_json(snapshot)).hexdigest()
    except (TypeError, ValueError):
        return None


class FaultRows:
    """`PersistAudit` and `RestoreAudit` over the sink: each writer seeds the key, then appends one
    `phase="fault"` row chained to the held head, with `payload` `{}`, empty state lists and
    `occurred_at` from the UTC clock. A refused persist also pages P1. Never raises (see the
    module docstring); cancellation passes through. `ops` counts each quarantine row."""

    def __init__(
        self,
        sink: ChainSink,
        pager: Pager,
        *,
        clock: Callable[[], datetime] = _utc_now,
        ops: OpsRecorder | None = None,
    ) -> None:
        self._sink, self._pager, self._clock, self._ops = sink, pager, clock, ops

    async def persist_refused(self, key: MachineKey, reason: str) -> None:
        cut = reason[:FAULT_REASON_MAX]
        await self._write(key, "PERSIST_REFUSED", {"kind": "persist_refused", "reason": cut})
        await self._page(key, f"persist refused, no snapshot written: {cut}")

    async def drain_error(self, key: MachineKey, error: str) -> None:
        fault = {"kind": "drain_error", "error": error[:FAULT_REASON_MAX]}
        await self._write(key, "DRAIN_ERROR", fault)

    async def quarantine(self, key: MachineKey, envelope: SealedSnapshot, reason: str) -> None:
        seal = envelope.seal
        fault = {
            "kind": "restore_quarantined",
            "reason": reason[:FAULT_REASON_MAX],
            "machine_hash": envelope.machine_hash,
            "version": envelope.version,
            "hmac_key_id": seal.key_id if isinstance(seal, Seal) else None,
            "snapshot_sha256": _snapshot_digest(envelope.snapshot),
        }
        written = await self._write(key, "RESTORE_QUARANTINED", fault)
        if self._ops is not None:
            self._ops("quarantine", "ok" if written else "error")

    async def _write(self, key: MachineKey, event_type: str, fault: dict[str, Any]) -> bool:
        try:
            await self._sink.seed(key)
            row = MachineEventRow(
                machine_kind=key.machine_kind, entity_id=key.entity_id, env=key.env,
                event_type=event_type, payload={}, from_states=[], to_states=[], actions_run=[],
                fault=fault, occurred_at=self._clock().isoformat(), phase="fault",
                prev_hash=self._sink.head(key) or GENESIS_HASH,
            )  # fmt: skip
            self._sink.append(replace(row, row_hash=row_digest(row)))
        except Exception as exc:  # never raised: the caller's own path must go on
            error = type(exc).__name__
            _logger().critical(
                "statechart_fault_row_failed",
                machine_kind=key.machine_kind,
                entity_id=key.entity_id,
                env=key.env,
                event_type=event_type,
                error=error,
            )
            await self._page(key, f"machine_events fault row {event_type} not written ({error})")
            return False
        return True

    async def _page(self, key: MachineKey, message: str) -> None:
        """Best effort and bounded, as the `Restorer`'s pages."""
        try:
            async with asyncio.timeout(PAGE_TIMEOUT_S):
                await self._pager.page(key, "P1", message)
        except Exception as exc:
            _logger().critical(
                "statechart_page_failed",
                machine_kind=key.machine_kind,
                entity_id=key.entity_id,
                env=key.env,
                reason="fault row",
                error=type(exc).__name__,
            )


class EventFramesAdapter:
    """The sink's `MachineEventStore` over `EventsAdapter`: each WAL frame is rebuilt as the
    `MachineEventRow` it was (`MachineEventRow(**frame)`), which `EventsAdapter` checks."""

    def __init__(self, events: EventsAdapter) -> None:
        self._events = events

    async def insert_batch(self, frames: Sequence[Mapping[str, Any]]) -> None:
        await self._events.insert_batch([MachineEventRow(**frame) for frame in frames])

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str:
        return await self._events.head(MachineKey(machine_kind, entity_id, env))


#: The events a chain-trip latch refuses, by machine kind (C-2.21, CV-C63): those that start
#: work. A stop-type event (pause, cancel, destroy, the kill switch) always passes, so a latched
#: machine can still be stopped; a latched key of a kind not listed here refuses every event.
GATED_EVENTS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {"replay": frozenset({"PREPARE", "PLAY", "STEP", "SEEK", "SET_SPEED"})}
)


class LatchAdmission:
    """The latch-backed gateway `Admission` (E50-T63): a gated event of a machine the
    `ChainTripLatch` holds is refused (`DegradedLatchError` becomes a refused `Decision`); any
    other event, an unlatched machine and a machine registered without a key are admitted."""

    def __init__(
        self, latch: ChainTripLatch, gated: Mapping[str, frozenset[str]] = GATED_EVENTS
    ) -> None:
        self.latch, self._gated = latch, gated

    def admit(self, key: MachineKey | None, event_type: str) -> Decision:
        if key is None:
            return ADMITTED
        gated = self._gated.get(key.machine_kind)
        if gated is not None and event_type not in gated:
            return ADMITTED
        try:
            self.latch.admit_command(key)
        except DegradedLatchError:
            return Decision(False, REASON_DEGRADED)
        return ADMITTED


class PagerAdapter:
    """`persistence.Pager` over the plugins' `LogPager`: a P1 page is its CRITICAL `cv_page=true`
    line, which the log-based alert rules key on, anything else an ERROR line. No new channel."""

    def __init__(self, pager: AlertPager | None = None) -> None:
        self._pager: AlertPager = pager or LogPager()

    async def page(self, key: MachineKey, severity: str, message: str) -> None:
        level: Severity = "page" if severity == "P1" else "alert"
        summary = f"{key.machine_kind}/{key.entity_id} ({key.env}): {message}"
        self._pager.raise_alert(level, summary, machine_kind=key.machine_kind)


#: `cv_machine_persist_ops_total`'s closed label sets: 4 x 4, the catalogue's cap of 16.
PERSIST_OPERATIONS: Final = ("persist", "restore", "quarantine", "event_flush")
PERSIST_OUTCOMES: Final = ("ok", "refused", "degraded", "error")


class PersistOps:
    """The two persistence families (catalogued `planned`, E50), registered on the app's one
    facade: `record(operation, outcome)` counts `cv_machine_persist_ops_total`, where a value
    outside the closed sets makes no series; `pending(rows)` sets `cv_machine_event_wal_pending`."""

    def __init__(self, metrics: Metrics) -> None:
        specs = {spec.name: spec for spec in CATALOGUE}
        ops, wal = specs["cv_machine_persist_ops_total"], specs["cv_machine_event_wal_pending"]
        self._ops = metrics.counter(ops.name, ops.help, ops.labels, max_series=ops.max_series)
        gauge = metrics.gauge(wal.name, wal.help, wal.labels, max_series=wal.max_series)
        self._pending = gauge.child()

    def record(self, operation: str, outcome: str) -> None:
        if operation in PERSIST_OPERATIONS and outcome in PERSIST_OUTCOMES:
            self._ops.labels(operation, outcome).inc()

    def flushed(self, outcome: str) -> None:
        self.record("event_flush", outcome)

    def pending(self, rows: int) -> None:
        self._pending.set(rows)


def _registry_sealer(keys: HmacKeys, registry: Registry) -> Sealer:
    """`Persister.seal` for every chart: `hmac_sealer` binds one chart, and the process-wide
    `Persister` seals for the chart of the key it persists."""

    async def _seal(
        snapshot: dict[str, Any], machine_hash: str, version: int, key: MachineKey
    ) -> Seal:
        return seal(keys, registry.get(key.machine_kind), snapshot, machine_hash, version, key=key)

    return _seal


#: The bound on closing the `statechart` pool at stop; the sink's drain has its own.
DISPOSE_TIMEOUT_S: Final = 5.0


@dataclass(slots=True)
class StatechartPersistence:
    """The persistence bundle (see the module docstring); on `app.state.statechart_persistence`.
    Its repr leaves out the key provider and the pool's repository (defence in depth: a debug line
    or an exception group that formats the bundle shows neither, C-2.7, C-12.6)."""

    relational: SqlAlchemyRelationalRepository = field(repr=False)
    snapshots: SnapshotAdapter
    journal: RowStoreDrainJournal
    events: EventsAdapter
    sink: MachineEventSinkHandle
    persister: Persister
    restorers: Mapping[Lane, Restorer]
    latch: ChainTripLatch
    admission: LatchAdmission
    pager: PagerAdapter
    faults: FaultRows
    keys: HmacKeys = field(repr=False)
    registry: Registry
    ops: PersistOps
    metrics: Metrics

    def restorer(self, lane: Lane) -> Restorer:
        return self.restorers[lane]

    def plugins(
        self, key: MachineKey, lane: Lane
    ) -> tuple[CvErrorHooks, CvMetricsPlugin, CvAuditPlugin]:
        """The mandatory triple for `key`, once its chain is seeded (`plugins_for` seeds it; a
        restore's `prepare` does): the audit plugin chains from the sink's held head and redacts
        payloads with the shared audit serializer before hashing. An unseeded key raises
        `ChainSeedError`: its first row would chain from the genesis and fork a stored chain."""
        if self.sink.head(key) is None:
            raise ChainSeedError(key, "unseeded")
        return cv_plugins(
            machine_kind=key.machine_kind, lane=lane, entity_id=key.entity_id, env=key.env,
            metrics=self.metrics, sink=self.sink, head=lambda: self.sink.head(key),
            redactor=system_event_redactor(),
        )  # fmt: skip

    async def plugins_for(
        self, key: MachineKey, lane: Lane
    ) -> tuple[CvErrorHooks, CvMetricsPlugin, CvAuditPlugin]:
        """For an owner's fresh build (`factory.build(plugins=...)`), a start without a verified
        snapshot: seeds the key's chain, runs the orphan scan (`Restorer.page_unclaimed`, 24
        §17.6), then builds the triple. A failed seed raises `ChainSeedError`; a failed scan its
        own error, paged: the machine must not start."""
        try:
            await self.sink.seed(key)
        except Exception as exc:
            raise ChainSeedError(key, type(exc).__name__) from None
        await self.restorer(lane).page_unclaimed(key)
        return self.plugins(key, lane)

    async def start(self) -> None:
        """The sink: the WAL's lock and replay, and the flusher. Never waits on Postgres."""
        await self.sink.start()

    async def stop(self) -> None:
        """The lifespan's last step: the sink stops accepting and drains (bounded by its own
        grace; what it leaves is durable in the WAL), then the pool closes, within its bound."""
        try:
            await self.sink.stop()
        finally:
            try:
                async with asyncio.timeout(DISPOSE_TIMEOUT_S):
                    await self.relational.dispose()
            except Exception as exc:
                _logger().critical("statechart_pool_dispose_failed", error=type(exc).__name__)


def _restore_plugins(bundle: StatechartPersistence, lane: Lane) -> PluginsFactory:
    """`Restorer.plugins` for one lane, called after `prepare` seeded the key. The plugins are
    duck-typed (the runtime resolves their hooks by name), hence the untyped tuple."""

    def plugins(key: MachineKey) -> tuple[Any, ...]:
        return bundle.plugins(key, lane)

    return plugins


def build_statechart_persistence(
    settings: Settings,
    *,
    hmac_keys: HmacKeys | None,
    metrics: Metrics,
    registry: Registry | None = None,
) -> StatechartPersistence | None:
    """The bundle on the real backend when `hmac_keys` are injected, else `None` (fail closed). No
    I/O: the pool is lazy, and `start()` opens the WAL. `registry` is the charts' (tests inject
    their fixtures); the default loads the committed ones."""
    if hmac_keys is None or settings.storage_backend != "real":
        return None
    charts = registry or Registry()
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "statechart")
    snapshots = SnapshotAdapter(SqlAlchemySnapshotStore(relational))
    journal = RowStoreDrainJournal(JournalRowsAdapter(SqlAlchemyJournalStore(relational)))
    events = EventsAdapter(SqlAlchemyEventStore(relational))
    ops = PersistOps(metrics)
    sink = build_machine_event_sink(
        settings,
        EventFramesAdapter(events),
        metrics=MachineEventSinkMetrics(flushed=ops.flushed, pending=ops.pending),
    )
    pager, latch = PagerAdapter(), ChainTripLatch()
    faults = FaultRows(sink, pager, ops=ops.record)
    persister = Persister(
        repo=snapshots, journal=journal, audit=faults, seal=_registry_sealer(hmac_keys, charts),
        machine_hash_of=charts.hash, pager=pager, ops=ops.record,
    )  # fmt: skip
    restorers: dict[Lane, Restorer] = {}
    bundle = StatechartPersistence(
        relational=relational, snapshots=snapshots, journal=journal, events=events, sink=sink,
        persister=persister, restorers=restorers, latch=latch, admission=LatchAdmission(latch),
        pager=pager, faults=faults, keys=hmac_keys, registry=charts, ops=ops, metrics=metrics,
    )  # fmt: skip
    for lane in LANES:
        restorers[lane] = Restorer(
            registry=charts, keys=hmac_keys, journal=journal, audit=faults, pager=pager,
            latch=latch, plugins=_restore_plugins(bundle, lane),
            clock=default_clock(), lane=lane, prepare=sink.seed, ops=ops.record,
        )  # fmt: skip
    return bundle


#: Checked by mypy, which CI runs on `candleviewer`: the adapters serve the ports they implement.
_SNAPSHOT_REPO: Callable[[SnapshotRows], SnapshotRepo] = SnapshotAdapter
_SNAPSHOT_SOURCE: Callable[[SnapshotRows], SnapshotSource] = SnapshotAdapter
_SNAPSHOT_STORE: Callable[[SnapshotRows], SnapshotStore] = SnapshotAdapter
_JOURNAL_ROWS: Callable[[JournalRows], JournalRowStore] = JournalRowsAdapter
_DRAIN_JOURNAL: Callable[[JournalRowStore], DrainJournal] = RowStoreDrainJournal
_PERSIST_AUDIT: Callable[[ChainSink, Pager], PersistAudit] = FaultRows
_RESTORE_AUDIT: Callable[[ChainSink, Pager], RestoreAudit] = FaultRows
