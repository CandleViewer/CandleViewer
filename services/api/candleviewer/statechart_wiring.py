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
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from candleviewer.admin.inspector import SnapshotRow, SnapshotStore
from candleviewer.replay.sessions_service import SnapshotSource
from candleviewer.statechart.persistence import (
    SEAL_LAYOUT_V,
    DrainJournal,
    JournalConflict,
    JournalEntry,
    JournalLane,
    JournalRowStore,
    MachineKey,
    RowStoreDrainJournal,
    Seal,
    SealedSnapshot,
    SnapshotRepo,
)
from candleviewer.statechart.plugins.audit import MachineEventRow, Phase
from candleviewer.storage.repositories.statechart_sqlalchemy import (
    EventRecord,
    JournalConflictRecord,
    JournalRecord,
    SnapshotRecord,
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


#: Checked by mypy, which CI runs on `candleviewer`: the adapters serve the ports they implement.
_SNAPSHOT_REPO: Callable[[SnapshotRows], SnapshotRepo] = SnapshotAdapter
_SNAPSHOT_SOURCE: Callable[[SnapshotRows], SnapshotSource] = SnapshotAdapter
_SNAPSHOT_STORE: Callable[[SnapshotRows], SnapshotStore] = SnapshotAdapter
_JOURNAL_ROWS: Callable[[JournalRows], JournalRowStore] = JournalRowsAdapter
_DRAIN_JOURNAL: Callable[[JournalRowStore], DrainJournal] = RowStoreDrainJournal
