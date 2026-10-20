"""`candleviewer.statechart_wiring` adapters and `persistence.RowStoreDrainJournal` (E50-T62 #3793):
the statechart DTOs to and from the store records, the #3082 key assertion and the blob and
`occurred_at` refusals (nothing reaches the database), the append's conflicts, and the replay
wrapper's order and stamping. Postgres: `tests/integration/storage/test_statechart_stores_pg.py`;
the journal contract cases run both journals in `tests/xstate_contract/test_persistence.py` and
`test_restore.py`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from candleviewer.statechart import persistence
from candleviewer.statechart.persistence import (
    SEAL_LAYOUT_V,
    DrainSeal,
    JournalConflict,
    JournalEntry,
    MachineKey,
    ReplayReport,
    RowStoreDrainJournal,
    Seal,
    SealedSnapshot,
    stable_send_id,
)
from candleviewer.statechart.plugins.audit import GENESIS_HASH, MachineEventRow, row_digest
from candleviewer.statechart_wiring import (
    EventsAdapter,
    JournalRowsAdapter,
    SnapshotAdapter,
    SnapshotKeyMismatchError,
    envelope_of,
)
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import (
    EventRecord,
    JournalConflictRecord,
    JournalRecord,
    SnapshotRecord,
    SqlAlchemySnapshotStore,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
KEY = MachineKey("order", "0a000000-0000-4000-8000-000000000001", "demo")
SEAL = Seal(key_id="k1", tag="ab" * 32)
BLOB: dict[str, Any] = {
    "version": 3, "state_ids": ["order.pending"], "chain_trips": 2,
    "context": {"i": 7, "f": 0.5, "u": "é✓", "nested": [[1, [2.5, None]]], "nul": None},
}  # fmt: skip
ENVELOPE = SealedSnapshot(key=KEY, version=3, machine_hash="d" * 64, snapshot=BLOB, seal=SEAL)


class FakeSnapshots:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], SnapshotRecord] = {}

    async def upsert(self, record: SnapshotRecord) -> None:
        self.rows[(record.machine_kind, record.entity_id, record.env)] = record

    async def get(self, machine_kind: str, entity_id: str, env: str) -> SnapshotRecord | None:
        return self.rows.get((machine_kind, entity_id, env))

    async def list_all(self) -> Sequence[SnapshotRecord]:
        return tuple(self.rows.values())


class _NoDatabase:
    """A relational repository whose unit of work must never open."""

    def __init__(self) -> None:
        self.opened = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        self.opened += 1
        raise AssertionError("a statement reached the database")
        yield


@pytest.mark.parametrize(
    ("envelope_key", "field"),
    [
        (replace(KEY, machine_kind="trade_group"), "machine_kind"),
        (replace(KEY, entity_id="0a000000-0000-4000-8000-000000000002"), "entity_id"),
        (replace(KEY, env="live"), "env"),
    ],
    ids=["machine_kind", "entity_id", "env"],
)
async def test_a_snapshot_sealed_for_another_key_is_refused_before_any_statement(
    envelope_key: MachineKey, field: str
) -> None:
    """#3082: the write refuses an envelope whose sealed key differs from the row's key, naming the
    field, before it opens a transaction (the real store over a database that must not open)."""
    database = _NoDatabase()
    store = SqlAlchemySnapshotStore(cast(SqlAlchemyRelationalRepository, database))
    with pytest.raises(SnapshotKeyMismatchError) as refused:
        await SnapshotAdapter(store).write_snapshot(KEY, replace(ENVELOPE, key=envelope_key))
    assert refused.value.field == field and field in str(refused.value)
    assert database.opened == 0


async def test_an_empty_entity_id_is_refused_first() -> None:
    """`''` and the kind are different keys: an empty entity is refused even when the envelope
    agrees with it."""
    empty = replace(KEY, entity_id="")
    database = _NoDatabase()
    store = SqlAlchemySnapshotStore(cast(SqlAlchemyRelationalRepository, database))
    with pytest.raises(SnapshotKeyMismatchError, match="entity_id is empty") as refused:
        await SnapshotAdapter(store).write_snapshot(empty, replace(ENVELOPE, key=empty))
    assert refused.value.field == "entity_id" and database.opened == 0


@pytest.mark.parametrize(
    "seal",
    ["stub", Seal(key_id="k1", tag="zz" * 32), Seal(key_id="k1", tag="ab" * 31)],
    ids=["no Seal", "not hex", "31 bytes"],
)
async def test_a_snapshot_without_a_32_byte_hmac_seal_is_refused_before_any_statement(
    seal: object,
) -> None:
    database = _NoDatabase()
    store = SqlAlchemySnapshotStore(cast(SqlAlchemyRelationalRepository, database))
    with pytest.raises((TypeError, ValueError)):
        await SnapshotAdapter(store).write_snapshot(KEY, replace(ENVELOPE, seal=seal))
    assert database.opened == 0


@pytest.mark.parametrize(
    "metadata",
    [
        {"state_ids": "order.pending"},
        {"state_ids": ["order.pending", 7]},
        {"chain_trips": -1},
        {"chain_trips": True},
        {"chain_trips": 1.0},
    ],
    ids=["state_ids not a list", "state_ids holds a non-str", "chain_trips -1",
         "chain_trips a bool", "chain_trips a float"],
)  # fmt: skip
async def test_blob_metadata_that_is_not_ids_or_a_count_is_refused_before_any_statement(
    metadata: dict[str, Any],
) -> None:
    """The unsealed `state_ids` and `chain_trips` columns are copied from the blob, so a blob whose
    values could not fill them is refused before a transaction opens (F4 / SR-E50T62-05)."""
    database = _NoDatabase()
    store = SqlAlchemySnapshotStore(cast(SqlAlchemyRelationalRepository, database))
    with pytest.raises(ValueError, match="snapshot write refused: the blob's"):
        await SnapshotAdapter(store).write_snapshot(
            KEY, replace(ENVELOPE, snapshot={**BLOB, **metadata})
        )
    assert database.opened == 0


async def test_the_write_maps_the_envelope_onto_the_row() -> None:
    """Key columns from the key; `state_ids` and `chain_trips` copied from the blob;
    `cv_schema_version` is `SEAL_LAYOUT_V`; the tag as its 32 raw bytes; `updated_at` from the
    injected clock."""
    store = FakeSnapshots()
    await SnapshotAdapter(store, clock=lambda: NOW).write_snapshot(KEY, ENVELOPE)
    assert store.rows == {
        (KEY.machine_kind, KEY.entity_id, KEY.env): SnapshotRecord(
            machine_kind="order", entity_id=KEY.entity_id, env="demo",
            cv_schema_version=SEAL_LAYOUT_V, lib_snapshot_ver=3, machine_hash="d" * 64,
            snapshot=BLOB, hmac_key_id="k1", hmac_tag=bytes.fromhex("ab" * 32),
            state_ids=("order.pending",), chain_trips=2, updated_at=NOW,
        )
    }  # fmt: skip


async def test_load_returns_the_envelope_rebuilt_from_the_three_key_columns() -> None:
    store = FakeSnapshots()
    adapter = SnapshotAdapter(store, clock=lambda: NOW)
    await adapter.write_snapshot(KEY, ENVELOPE)
    assert await adapter.load(KEY) == ENVELOPE
    assert await adapter.load(replace(KEY, env="live")) is None
    upper = replace(ENVELOPE, seal=Seal(key_id="k1", tag="AB" * 32))
    await adapter.write_snapshot(KEY, upper)
    loaded = await adapter.load(KEY)
    assert loaded is not None and loaded.seal == SEAL  # the tag comes back as lowercase hex


async def test_the_inspector_list_names_a_singleton_with_no_entity_id() -> None:
    """`SnapshotStore.snapshots()`: `entity_id` equal to the kind (a singleton) is `None`, as
    `_project` reads it; `environment` is `env`; `updated_at` is tz-aware."""
    store = FakeSnapshots()
    adapter = SnapshotAdapter(store, clock=lambda: NOW)
    single = MachineKey("kill_switch", "kill_switch", "live")
    await adapter.write_snapshot(KEY, ENVELOPE)
    await adapter.write_snapshot(single, replace(ENVELOPE, key=single))
    rows = {row.machine_kind: row for row in await adapter.snapshots()}
    assert rows["kill_switch"].entity_id is None and rows["order"].entity_id == KEY.entity_id
    assert rows["kill_switch"].environment == "live" and rows["order"].environment == "demo"
    assert rows["kill_switch"].envelope.key == single and rows["order"].envelope == ENVELOPE
    assert all(row.updated_at.utcoffset() is not None for row in rows.values())


def test_envelope_of_takes_the_key_from_the_columns_never_from_the_blob() -> None:
    record = SnapshotRecord(
        machine_kind="order", entity_id="e-1", env="testnet", cv_schema_version=2,
        lib_snapshot_ver=3, machine_hash="d" * 64, snapshot={"machine_id": "other"},
        hmac_key_id="k2", hmac_tag=bytes(32), state_ids=(), chain_trips=0, updated_at=NOW,
    )  # fmt: skip
    envelope = envelope_of(record)
    assert envelope.key == MachineKey("order", "e-1", "testnet")
    assert envelope.seal == Seal(key_id="k2", tag="00" * 32) and envelope.version == 3


class FakeJournal:
    def __init__(self, conflicts: Sequence[JournalConflictRecord] = ()) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.rows: list[JournalRecord] = []
        self.conflicts = tuple(conflicts)

    async def append(
        self, machine_kind: str, entity_id: str, env: str, records: Sequence[JournalRecord]
    ) -> tuple[JournalConflictRecord, ...]:
        self.calls.append(("append", machine_kind, entity_id, env))
        self.rows.extend(records)
        return self.conflicts

    async def list_unreplayed(
        self, machine_kind: str, entity_id: str, env: str
    ) -> Sequence[JournalRecord]:
        self.calls.append(("list", machine_kind, entity_id, env))
        return tuple(self.rows)

    async def present(
        self, machine_kind: str, entity_id: str, env: str, send_ids: Sequence[str]
    ) -> frozenset[str]:
        self.calls.append(("present", machine_kind, entity_id, env, tuple(send_ids)))
        return frozenset(send_ids) & {r.send_id for r in self.rows}

    async def mark_replayed(
        self, machine_kind: str, entity_id: str, env: str, send_ids: Sequence[str]
    ) -> None:
        self.calls.append(("mark", machine_kind, entity_id, env, tuple(send_ids)))


EPOCH = "e0" * 16
_RECORDS = [
    {"kind": "event", "type": "PING", "lane": "priority", "payload": {"n": "p0"}},
    {"kind": "event", "type": "PING", "payload": {"n": "i1"}},
]
ENTRIES = [
    JournalEntry(send_id=stable_send_id(KEY, EPOCH, 1, 0, _RECORDS[0]), lane="priority",
                 ordinal=0, event_type="PING", record=_RECORDS[0]),
    JournalEntry(send_id=stable_send_id(KEY, EPOCH, 1, 1, _RECORDS[1]), lane="inbox", ordinal=1,
                 event_type="PING", record=_RECORDS[1], receipt_error="InterpreterStoppedError"),
]  # fmt: skip
DRAIN = DrainSeal(EPOCH, 1, tuple(sorted(e.send_id for e in ENTRIES)))


async def test_the_journal_rows_round_trip_through_the_store_records() -> None:
    store = FakeJournal()
    adapter = JournalRowsAdapter(store)
    assert await adapter.append(KEY, ENTRIES) == ()
    assert store.rows == [
        JournalRecord(e.send_id, e.lane, e.ordinal, e.event_type, e.record, e.receipt_error)
        for e in ENTRIES
    ]
    assert store.rows[1].payload == _RECORDS[1] and store.rows[1].receipt_error is not None
    assert list(await adapter.list_unreplayed(KEY)) == ENTRIES
    assert await adapter.present(KEY, [ENTRIES[0].send_id, "f" * 32]) == {ENTRIES[0].send_id}
    asked = ("present", "order", KEY.entity_id, "demo", (ENTRIES[0].send_id, "f" * 32))
    assert store.calls[-1:] == [asked]
    await adapter.mark_replayed(KEY, ["a" * 32])
    assert store.calls[-1] == ("mark", "order", KEY.entity_id, "demo", ("a" * 32,))
    calls = len(store.calls)
    assert await adapter.append(KEY, []) == ()
    await adapter.mark_replayed(KEY, [])
    assert await adapter.present(KEY, []) == frozenset()
    assert len(store.calls) == calls  # nothing to write or ask, nothing asked of the store


async def test_the_append_hands_back_the_stores_conflicts_as_the_ports() -> None:
    """The store says, per send_id it skipped, whether the row is stamped and whether its payload
    text is the entry's; the adapter hands that back for `Persister` to classify (24 §17.6)."""
    store = FakeJournal(
        [JournalConflictRecord("a" * 32, True, True), JournalConflictRecord("b" * 32, False, False)]
    )
    conflicts = await JournalRowsAdapter(store).append(KEY, ENTRIES)
    assert conflicts == (
        JournalConflict("a" * 32, stamped=True, same_payload=True),
        JournalConflict("b" * 32, stamped=False, same_payload=False),
    )
    assert not any(c.is_retry for c in conflicts)


async def test_a_journal_row_off_the_two_lanes_is_refused() -> None:
    store = FakeJournal()
    store.rows.append(
        JournalRecord(send_id="c" * 32, lane="side", ordinal=0, event_type="X", payload={})
    )
    with pytest.raises(ValueError, match="lane"):
        await JournalRowsAdapter(store).list_unreplayed(KEY)


class FakeRows:
    """A `JournalRowStore` that logs into the shared `log` and lists rows out of order."""

    def __init__(self, log: list[Any], rows: list[JournalEntry]) -> None:
        self.log, self.rows, self.stamped = log, rows, set[str]()

    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> list[Any]:
        self.rows.extend(entries)
        return []

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        self.log.append("list")
        return [e for e in reversed(self.rows) if e.send_id not in self.stamped]

    async def present(self, key: MachineKey, send_ids: Sequence[str]) -> frozenset[str]:
        self.log.append(("present", list(send_ids)))
        return frozenset(send_ids) & {e.send_id for e in self.rows}

    async def mark_replayed(self, key: MachineKey, send_ids: Sequence[str]) -> None:
        self.log.append(("mark", list(send_ids)))
        self.stamped.update(send_ids)


class FakeInterp:
    def __init__(self, log: list[Any], fail_at: int | None = None) -> None:
        self.log, self.fail_at, self.count = log, fail_at, 0

    def _enqueue_restored(self, ev: Any, priority: bool = False) -> None:
        self.count += 1
        if self.count == self.fail_at:
            raise RuntimeError("crash while re-enqueueing")
        self.log.append(("enqueue", ev, priority))


def _restore(record: dict[str, Any]) -> str:
    return str(record["payload"]["n"])


async def test_replay_enqueues_in_ordinal_order_then_stamps_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CV-C65': rows in `ordinal` order, priority lane first, each re-enqueued once on the lane its
    verified record names; then one stamp of every send_id; a second replay finds nothing to
    replay, asks which sealed rows exist, and stamps nothing."""
    monkeypatch.setattr(persistence, "restore_event", _restore)
    log: list[Any] = []
    journal = RowStoreDrainJournal(FakeRows(log, list(ENTRIES)))
    interp = cast(Any, FakeInterp(log))
    assert await journal.replay_once(KEY, interp, DRAIN) == ReplayReport(2, (), ())
    assert log == [
        "list",
        ("enqueue", "p0", True),
        ("enqueue", "i1", False),
        ("mark", [ENTRIES[0].send_id, ENTRIES[1].send_id]),
    ]
    assert await journal.replay_once(KEY, interp, DRAIN) == ReplayReport(0, (), ())
    assert log[-2:] == ["list", ("present", list(DRAIN.drained))]


async def test_a_crash_before_the_stamp_redelivers_rather_than_loses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stamp after enqueue: a crash part-way leaves every row unstamped, so the next restore
    re-delivers, and an order retry reuses its client order id (C-2.10)."""
    monkeypatch.setattr(persistence, "restore_event", _restore)
    log: list[Any] = []
    rows = FakeRows(log, list(ENTRIES))
    with pytest.raises(RuntimeError, match="crash"):
        await RowStoreDrainJournal(rows).replay_once(
            KEY, cast(Any, FakeInterp(log, fail_at=2)), DRAIN
        )
    assert rows.stamped == set() and not any(isinstance(e, tuple) and e[0] == "mark" for e in log)


async def test_the_journal_lists_unreplayed_rows_through_its_store() -> None:
    log: list[Any] = []
    journal = RowStoreDrainJournal(FakeRows(log, list(ENTRIES)))
    assert [e.ordinal for e in await journal.list_unreplayed(KEY)] == [1, 0]  # the store's order
    assert await journal.append(KEY, []) == []


def _chain(n: int) -> list[MachineEventRow]:
    rows, prev = [], GENESIS_HASH
    for i in range(n):
        row = MachineEventRow(
            machine_kind="order", entity_id=KEY.entity_id, env="demo", event_type="PING",
            payload={"i": i, "f": 0.25 * i, "u": "é✓", "nested": [[i, [1.5, None]]], "nul": None},
            from_states=["order.idle"], to_states=["order.pending"], actions_run=["record"],
            fault=None, occurred_at=NOW.replace(microsecond=i).isoformat(), phase="commit",
            prev_hash=prev,
        )  # fmt: skip
        row = replace(row, row_hash=row_digest(row))
        rows.append(row)
        prev = row.row_hash
    return rows


class FakeEvents:
    def __init__(self) -> None:
        self.records: list[EventRecord] = []

    async def insert_batch(self, records: Sequence[EventRecord]) -> None:
        stored = len(self.records)  # seq is the database's: 1, 2, ... in insertion order
        self.records.extend(replace(r, seq=stored + i + 1) for i, r in enumerate(records))

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str:
        return self.records[-1].row_hash if self.records else GENESIS_HASH

    async def read_chain(
        self, machine_kind: str, entity_id: str, env: str, *, after_seq: int = 0
    ) -> Sequence[EventRecord]:
        return tuple(r for r in self.records if r.seq > after_seq)

    async def read_whole_chain(
        self, machine_kind: str, entity_id: str, env: str
    ) -> Sequence[EventRecord]:
        return tuple(self.records)


async def test_machine_event_rows_come_back_byte_for_byte() -> None:
    """`occurred_at` returns as the plugin's ISO-8601 UTC string and the dicts as dicts, so
    `row_digest` over a row read back equals the `row_hash` it was stored with."""
    store, rows = FakeEvents(), _chain(3)
    adapter = EventsAdapter(store)
    await adapter.insert_batch(rows)
    assert store.records[0].occurred_at == NOW and store.records[0].from_states == ("order.idle",)
    back = await adapter.chain(KEY)
    assert back == rows and all(row_digest(r) == r.row_hash for r in back)
    assert await adapter.head(KEY) == rows[-1].row_hash
    page = await adapter.read_chain(KEY, after_seq=1)
    assert [(seq, row.row_hash) for seq, row in page] == [
        (2, rows[1].row_hash),
        (3, rows[2].row_hash),
    ]


@pytest.mark.parametrize(
    "occurred_at",
    ["2026-10-19T14:00:00+02:00", "2026-10-19T12:00:00", "2026-10-19T12:00:00Z", "yesterday"],
    ids=["another offset", "naive", "Z suffix", "not ISO-8601"],
)
async def test_an_occurred_at_that_would_not_come_back_unchanged_is_refused(
    occurred_at: str,
) -> None:
    """The digest covers the string: one the store would hand back differently is refused before
    the store sees it, never stored to break its chain later."""
    store = FakeEvents()
    row = replace(_chain(1)[0], occurred_at=occurred_at)
    with pytest.raises(ValueError, match="occurred_at"):
        await EventsAdapter(store).insert_batch([row])
    assert store.records == []


async def test_a_bad_row_after_a_good_one_refuses_the_whole_batch_before_the_store() -> None:
    """Every row is checked before the store sees the batch, so nothing of it is stored."""
    store = FakeEvents()
    good, bad = _chain(2)
    with pytest.raises(ValueError, match="occurred_at"):
        await EventsAdapter(store).insert_batch([good, replace(bad, occurred_at="yesterday")])
    assert store.records == []


class CountingEvents(FakeEvents):
    def __init__(self) -> None:
        super().__init__()
        self.batches: list[int] = []

    async def insert_batch(self, records: Sequence[EventRecord]) -> None:
        self.batches.append(len(records))
        await super().insert_batch(records)


async def test_an_empty_event_batch_asks_nothing_of_the_store() -> None:
    store = CountingEvents()
    await EventsAdapter(store).insert_batch([])
    await EventsAdapter(store).insert_batch(_chain(1))
    assert store.batches == [1]  # the empty batch never reached the store
