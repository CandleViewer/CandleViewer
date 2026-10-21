"""tests/xstate_contract/test_restore.py — E50-T49 restore + HMAC envelope.

Gherkin (ticket E50-T49):
  1. bad HMAC / wrong machine_hash / version 2 -> refused, quarantined, P1 page;
  2. plugins are attached via from_snapshot(plugins=);
  3. a snapshot with chain_trips = 1 restores degraded: reads served, order
     commands refused.

E50-T62: `Restorer.plugins` is called with the key being restored, and the journal cases run on
both journals (the reference and `RowStoreDrainJournal` over an in-memory row store).

E50-T62 round 2 (24 §17.6, `SEAL_LAYOUT_V = 3`): a restore replays only the rows the verified
blob's `cv_drained` names and whose `send_id` recomputes from the row with the blob's `cv_epoch`
and `cv_generation`, with columns that agree with the record; it skips and pages the rest, and a
sealed `send_id` with no row, in one page per key. A layout-2 envelope, or a blob that lacks or
malforms a `cv_` key, is quarantined. A failed replay stops the machine (F7); a restored machine
persists again (F2) under the next generation of its life, and a later identical drain is never
dropped (F1).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import hmac
import json
from collections.abc import MutableMapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs
from xstate_statemachine import Event, Interpreter, PluginBase, SimulatedClock
from xstate_statemachine.events import persist_event

from candleviewer.statechart import build, persistence
from candleviewer.statechart import factory as cv_factory
from candleviewer.statechart.persistence import (
    ChainSeedError,
    ChainTripLatch,
    DegradedLatchError,
    DrainJournal,
    DrainSeal,
    InMemoryDrainJournal,
    JournalEntry,
    MachineKey,
    Persister,
    ReplayReport,
    Restorer,
    RestoreRefusedError,
    RowStoreDrainJournal,
    Seal,
    SealedSnapshot,
    hmac_sealer,
    open_sealed,
    reconcile_counts,
    seal,
    split_sealed_drain,
    stable_send_id,
)
from candleviewer.statechart.registry import Registry
from candleviewer.statechart.schema import canonical_json
from candleviewer.storage.errors import (
    JournalListTooLargeError,
    StorageQueryFailed,
    StorageTierUnavailable,
)
from tests.unit.audit.audit_waits import virtual
from tests.xstate_contract.persist_fixtures import binding_persist  # noqa: F401
from tests.xstate_contract.persist_fixtures.journals import (
    JOURNALS,
    FakeJournalRows,
    JournalSubject,
)

_FIXTURES = Path(__file__).resolve().parent / "persist_fixtures"
_KIND = "persist_min"
KEY = MachineKey(_KIND, "00000000-0000-0000-0000-000000000002", "demo")


class FakeKeys:
    def __init__(self) -> None:
        self._keys = {"k1": b"\x01" * 32, "k2": b"\x02" * 32}
        self.cur = "k1"

    def current(self) -> str:
        return self.cur

    def key(self, key_id: str) -> bytes:
        return self._keys[key_id]


class FakeRepo:
    def __init__(self, fail: bool = False) -> None:
        self.rows: dict[MachineKey, SealedSnapshot] = {}
        self.fail = fail

    async def write_snapshot(self, key: MachineKey, envelope: SealedSnapshot) -> None:
        if self.fail:
            raise ConnectionError("simulated crash before the snapshot write")
        self.rows[key] = envelope


class FakeAudit:
    def __init__(self) -> None:
        self.quarantined: list[tuple[MachineKey, str]] = []

    async def drain_error(self, key: MachineKey, error: str) -> None: ...

    async def persist_refused(self, key: MachineKey, reason: str) -> None: ...

    async def quarantine(self, key: MachineKey, envelope: SealedSnapshot, reason: str) -> None:
        self.quarantined.append((key, reason))


class FakePager:
    def __init__(self) -> None:
        self.pages: list[tuple[str, str]] = []

    async def page(self, key: MachineKey, severity: str, message: str) -> None:
        self.pages.append((severity, message))


class CvErrorHooks(PluginBase[Any]):
    pass


class CvMetricsPlugin(PluginBase[Any]):
    pass


class CvAuditPlugin(PluginBase[Any]):
    def __init__(self) -> None:
        self.events: list[str] = []

    def on_event_received(self, interpreter: Any, event: Any) -> None:
        self.events.append(str(event.type))


@pytest.fixture()
def registry() -> Registry:
    return Registry(machines_dir=_FIXTURES)


@pytest.fixture(params=list(JOURNALS))
def journal(request: pytest.FixtureRequest) -> JournalSubject:
    return JOURNALS[request.param]()


def _restorer(
    registry: Registry,
    keys: FakeKeys,
    audit: FakeAudit,
    pager: FakePager,
    journal: DrainJournal | None = None,
    latch: ChainTripLatch | None = None,
) -> Restorer:
    return Restorer(
        registry=registry,
        keys=keys,
        journal=journal or InMemoryDrainJournal(),
        audit=audit,
        pager=pager,
        latch=latch or ChainTripLatch(),
        plugins=lambda key: [CvErrorHooks(), CvMetricsPlugin(), CvAuditPlugin()],
        clock=SimulatedClock(),
        lane="platform",
    )


async def _built(registry: Registry) -> Interpreter[Any]:
    res = await build(_KIND, clock=SimulatedClock(), lane="platform", registry=registry)
    return res.interpreter


async def _persist(
    registry: Registry,
    keys: FakeKeys,
    journal: DrainJournal,
    interp: Interpreter[Any],
    *,
    repo: FakeRepo | None = None,
    pager: FakePager | None = None,
) -> SealedSnapshot:
    """Persist through the production `Persister` (the OS CSPRNG mints a fresh life's epoch)."""
    repo = repo or FakeRepo()
    await Persister(
        repo=repo,
        journal=journal,
        audit=FakeAudit(),
        seal=hmac_sealer(keys, registry.get(_KIND)),
        machine_hash_of=registry.hash,
        pager=pager or FakePager(),
    ).persist(interp, key=KEY)
    return repo.rows[KEY]


async def _sealed(
    registry: Registry, keys: FakeKeys, journal: DrainJournal, chain_trips: int = 0
) -> SealedSnapshot:
    interp = await _built(registry)
    interp.chain_trips = chain_trips
    interp._enqueue_restored(Event("PING", {"n": "pending"}))
    return await _persist(registry, keys, journal, interp)


def _bad_hmac(env: SealedSnapshot, keys: FakeKeys, chart: dict[str, Any]) -> SealedSnapshot:
    blob = {**env.snapshot, "context": {**env.snapshot["context"], "seen": ["forged"]}}
    return dataclasses.replace(env, snapshot=blob)


def _wrong_hash(env: SealedSnapshot, keys: FakeKeys, chart: dict[str, Any]) -> SealedSnapshot:
    return dataclasses.replace(env, machine_hash="0" * 64)


def _version_2(env: SealedSnapshot, keys: FakeKeys, chart: dict[str, Any]) -> SealedSnapshot:
    return dataclasses.replace(env, version=2)


def _blob_version_2_resealed(
    env: SealedSnapshot, keys: FakeKeys, chart: dict[str, Any]
) -> SealedSnapshot:
    # Even a correctly-MACed blob that declares v2 is refused by from_snapshot.
    blob = {**env.snapshot, "version": 2}
    return dataclasses.replace(
        env, snapshot=blob, seal=seal(keys, chart, blob, env.machine_hash, 3, key=KEY)
    )


@pytest.mark.parametrize(
    "defect",
    [_bad_hmac, _wrong_hash, _version_2, _blob_version_2_resealed],
    ids=["bad HMAC", "wrong machine_hash", "version 2", "blob version 2 (resealed)"],
)
async def test_restore_bad_envelope_refused_quarantined_paged(
    registry: Registry, defect: Any
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = defect(await _sealed(registry, keys, InMemoryDrainJournal()), keys, registry.get(_KIND))
    with pytest.raises(RestoreRefusedError):
        await _restorer(registry, keys, audit, pager).restore(KEY, env)
    assert [k for k, _ in audit.quarantined] == [KEY]
    assert [s for s, _ in pager.pages] == ["P1"]


@pytest.mark.parametrize(
    "other",
    [
        dataclasses.replace(KEY, env="live"),
        dataclasses.replace(KEY, entity_id="00000000-0000-0000-0000-0000000000ff"),
    ],
    ids=["env", "entity_id"],
)
async def test_restore_envelope_persisted_for_another_machine_refused_quarantined_paged(
    registry: Registry, other: MachineKey
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    with pytest.raises(RestoreRefusedError, match="another machine key"):
        await _restorer(registry, keys, audit, pager).restore(other, env)
    assert [k for k, _ in audit.quarantined] == [other]
    assert [s for s, _ in pager.pages] == ["P1"]


async def test_restore_unsealed_envelope_refused(registry: Registry) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = dataclasses.replace(await _sealed(registry, keys, InMemoryDrainJournal()), seal="stub")
    with pytest.raises(RestoreRefusedError, match="no HMAC seal"):
        await _restorer(registry, keys, audit, pager).restore(KEY, env)


async def test_restore_unknown_key_id_refused(registry: Registry) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    env = dataclasses.replace(env, seal=Seal(key_id="gone", tag=env.seal.tag))
    with pytest.raises(RestoreRefusedError, match="key_id"):
        await _restorer(registry, keys, audit, pager).restore(KEY, env)


async def test_restore_after_key_rotation_uses_envelope_key_id(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    keys.cur = "k2"  # rotated after sealing
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.replayed == 1 and not res.degraded
        assert audit.quarantined == [] and pager.pages == []
    finally:
        await res.interpreter.stop()


async def test_restore_attaches_plugins_via_from_snapshot(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    interp = res.interpreter
    try:
        names = [type(getattr(p, "_plugin", p)).__name__ for p in interp._plugins]
        assert names == ["CvErrorHooks", "CvMetricsPlugin", "CvAuditPlugin"]
        assert interp._max_queue_size is not None and interp.strict is True
        await interp.send("PING", wait=True, n="after")
        assert interp.context["seen"] == ["pending", "after"]
    finally:
        await interp.stop()


async def test_restore_chain_trip_latch_serves_reads_refuses_orders(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    latch = ChainTripLatch()
    env = await _sealed(registry, keys, journal, chain_trips=1)
    res = await _restorer(registry, keys, audit, pager, journal, latch).restore(KEY, env)
    try:
        assert res.degraded and res.interpreter.chain_trips == 1
        assert latch.is_latched(KEY)
        assert res.interpreter.current_state_ids  # reads served
        with pytest.raises(DegradedLatchError, match="CV-C63"):
            latch.admit_command(KEY)
        assert [s for s, _ in pager.pages] == ["P1"]
        latch.acknowledge(KEY)
        latch.admit_command(KEY)
    finally:
        await res.interpreter.stop()


def test_open_sealed_round_trip_and_low_version_seal_refused(registry: Registry) -> None:
    keys, chart = FakeKeys(), registry.get(_KIND)
    blob = {"a": 1}
    s = seal(keys, chart, blob, "h", 3, key=KEY)
    env = SealedSnapshot(key=KEY, version=3, machine_hash="h", snapshot=blob, seal=s)
    assert open_sealed(keys, chart, env, key=KEY, expected_machine_hash="h") == blob
    with pytest.raises(ValueError, match="CV-C53"):
        seal(keys, chart, blob, "h", 2, key=KEY)
    # Chart bytes are bound: a different chart fails verification.
    with pytest.raises(ValueError, match="bad HMAC"):
        open_sealed(keys, {**chart, "id": "other"}, env, key=KEY, expected_machine_hash="h")


class _Stub:
    def __init__(self, pending: int, deferred: int, sched: int) -> None:
        self.pending_events = tuple(range(pending))
        self._deferred_events = list(range(deferred))
        self._restored_self_sends = list(range(sched))


@pytest.mark.parametrize("field", ["pending_events", "deferred", "scheduled_sends"])
def test_reconcile_counts_mismatch_raises(field: str) -> None:
    blob = {"pending_events": [1], "deferred": [1], "scheduled_sends": [1]}
    reconcile_counts(blob, _Stub(1, 1, 1))  # type: ignore[arg-type]  # duck-typed stub
    blob[field] = [1, 2]
    with pytest.raises(ValueError, match="CV-C54"):
        reconcile_counts(blob, _Stub(1, 1, 1))  # type: ignore[arg-type]  # duck-typed stub


async def test_factory_restore_delegates(registry: Registry, journal: JournalSubject) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    res = await cv_factory.restore(_restorer(registry, keys, audit, pager, journal), KEY, env)
    await res.interpreter.stop()


async def test_restore_calls_the_plugins_factory_with_the_key_it_restores(
    registry: Registry,
) -> None:
    """E50-T62: the mandatory plugin triple needs the identity of the machine being restored
    (`cv_plugins(machine_kind=, entity_id=, env=, ...)`), so the factory receives the key."""
    keys, audit, pager, journal = FakeKeys(), FakeAudit(), FakePager(), InMemoryDrainJournal()
    env = await _sealed(registry, keys, journal)
    seen: list[MachineKey] = []

    def plugins(key: MachineKey) -> list[PluginBase[Any]]:
        seen.append(key)
        return [CvErrorHooks(), CvMetricsPlugin(), CvAuditPlugin()]

    restorer = dataclasses.replace(
        _restorer(registry, keys, audit, pager, journal), plugins=plugins
    )
    res = await restorer.restore(KEY, env)
    try:
        assert seen == [KEY]
    finally:
        await res.interpreter.stop()


# --- E50-T62 round 2: the sealed drained set, the restore checks and the pages (24 §17.6) ---


def _ping(n: object, lane: str | None = None) -> dict[str, Any]:
    return persist_event(Event("PING", {"n": n}), lane=lane)


async def test_an_identical_event_at_the_same_ordinal_in_a_later_drain_is_replayed(
    registry: Registry, journal: JournalSubject
) -> None:
    """F1: the generation keeps a later drain's id apart from the stamped row of an earlier drain
    that held the same event at the same ordinal, so the later one is replayed, not dropped."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    restorer = _restorer(registry, keys, audit, pager, journal)
    interp = await _built(registry)
    interp._enqueue_restored(Event("PING", {"n": "same"}))
    first = await restorer.restore(KEY, await _persist(registry, keys, journal, interp))
    assert first.replayed == 1
    await first.interpreter.send("PING", wait=True, n="flush")  # the replayed one is processed
    first.interpreter._enqueue_restored(Event("PING", {"n": "same"}))
    later = await _persist(registry, keys, journal, first.interpreter, pager=pager)
    again = await restorer.restore(KEY, later)
    try:
        assert again.replayed == 1 and pager.pages == []
        await again.interpreter.send("PING", wait=True, n="end")
        assert again.interpreter.context["seen"] == ["same", "flush", "same", "end"]
    finally:
        await again.interpreter.stop()


async def test_a_restored_interpreter_is_persisted_again_under_the_next_generation(
    registry: Registry, journal: JournalSubject
) -> None:
    """F2 (E50-T10/T49): the library's resume path leaves `_descent_done` unset, which made every
    restored machine unpersistable; it persists again, and its life keeps one epoch."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    restorer = _restorer(registry, keys, audit, pager, journal)
    env = await _persist(registry, keys, journal, await _built(registry))
    seen = [(env.snapshot["cv_epoch"], env.snapshot["cv_generation"])]
    for _ in range(2):
        res = await restorer.restore(KEY, env)
        env = await _persist(registry, keys, journal, res.interpreter)
        assert res.interpreter.status == "stopped"
        seen.append((env.snapshot["cv_epoch"], env.snapshot["cv_generation"]))
    assert [g for _, g in seen] == [1, 2, 3] and len({e for e, _ in seen}) == 1
    assert pager.pages == []


async def test_a_new_life_never_collides_with_the_rows_of_a_crash_before_the_first_snapshot(
    registry: Registry, journal: JournalSubject
) -> None:
    """A crash between the first append and the first snapshot leaves rows no sealed set can
    claim: the next start (no verified snapshot) pages them, and its new life, under a new epoch,
    writes other ids for the identical event; each later restore skips and pages them again."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    restorer = _restorer(registry, keys, audit, pager, journal)
    crashed = await _built(registry)
    crashed._enqueue_restored(Event("PING", {"n": "same"}))
    with pytest.raises(ConnectionError):
        await _persist(registry, keys, journal, crashed, repo=FakeRepo(fail=True))
    await crashed.stop()
    [orphan] = journal.rows(KEY)
    assert await restorer.page_unclaimed(KEY) == 1
    [(severity, text)] = pager.pages
    assert severity == "P1" and orphan.send_id in text and "no verified snapshot" in text
    fresh = await _built(registry)
    fresh._enqueue_restored(Event("PING", {"n": "same"}))
    env = await _persist(registry, keys, journal, fresh, pager=pager)
    assert len(pager.pages) == 1  # no conflict: the new life's id is another
    assert orphan.send_id not in env.snapshot["cv_drained"] and len(env.snapshot["cv_drained"]) == 1
    res = await restorer.restore(KEY, env)
    try:
        assert res.replayed == 1 and journal.stamped(KEY) == set(env.snapshot["cv_drained"])
        assert len(pager.pages) == 2 and orphan.send_id in pager.pages[1][1]
    finally:
        await res.interpreter.stop()


async def test_a_new_life_after_a_refused_restore_never_collides_with_the_old_rows(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    restorer = _restorer(registry, keys, audit, pager, journal)
    old = await _built(registry)
    old._enqueue_restored(Event("PING", {"n": "same"}))
    old_env = await _persist(registry, keys, journal, old)
    with pytest.raises(RestoreRefusedError):
        await restorer.restore(KEY, _bad_hmac(old_env, keys, registry.get(_KIND)))
    assert await restorer.page_unclaimed(KEY) == 1  # nothing verified claims the old row
    new = await _built(registry)
    new._enqueue_restored(Event("PING", {"n": "same"}))
    persist_pager = FakePager()
    env = await _persist(registry, keys, journal, new, pager=persist_pager)
    assert persist_pager.pages == []
    assert set(env.snapshot["cv_drained"]).isdisjoint(old_env.snapshot["cv_drained"])
    res = await restorer.restore(KEY, env)
    try:
        assert res.replayed == 1
    finally:
        await res.interpreter.stop()


async def test_rows_of_a_persist_whose_snapshot_write_failed_are_skipped_and_paged(
    registry: Registry, journal: JournalSubject
) -> None:
    """The accepted trade-off (24 §17.6): rows journaled by a persist whose snapshot write failed
    belong to no sealed set; the next restore skips and pages them instead of replaying them onto
    the state that was written instead (C-2.10: the OMS reconciles from the exchange)."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    interp = await _built(registry)
    interp._enqueue_restored(Event("PING", {"n": "lost"}))
    with pytest.raises(ConnectionError):
        await _persist(registry, keys, journal, interp, repo=FakeRepo(fail=True))
    [stale] = journal.rows(KEY)
    interp._enqueue_restored(Event("PING", {"n": "kept"}))
    env = await _persist(registry, keys, journal, interp)
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.replayed == 1 and stale.send_id not in journal.stamped(KEY)
        await res.interpreter.send("PING", wait=True, n="end")
        assert res.interpreter.context["seen"] == ["kept", "end"]
        [(severity, text)] = pager.pages
        assert severity == "P1" and stale.send_id in text
        assert "1 not in the sealed drained set" in text
    finally:
        await res.interpreter.stop()


async def test_a_planted_row_is_skipped_left_unstamped_and_paged(
    registry: Registry, journal: JournalSubject
) -> None:
    """A row cv_app inserted with a self-consistent send_id (the epoch and generation are readable
    in the blob) recomputes, but the seal never named it: it is not replayed."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    drain, _ = split_sealed_drain(env.snapshot)
    record = _ping("planted", lane="priority")
    sid = stable_send_id(KEY, drain.epoch, drain.generation, 1, record)
    journal.plant(KEY, JournalEntry(sid, "priority", 1, "PING", record))
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.replayed == 1 and sid not in journal.stamped(KEY)
        await res.interpreter.send("PING", wait=True, n="end")
        assert res.interpreter.context["seen"] == ["pending", "end"]
        [(severity, text)] = pager.pages
        assert severity == "P1" and sid in text and "planted" not in text
    finally:
        await res.interpreter.stop()


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"lane": "priority"}, "1 lane column disagrees with the record"),
        ({"event_type": "PONG"}, "1 event_type column disagrees with the record"),
        ({"ordinal": 7}, "1 send_id does not recompute"),
        ({"record": _ping("forged")}, "1 send_id does not recompute"),
        ({"record": ["not", "an", "object"]}, "1 record is not an object"),
        ({"record": {"type": "PING", "payload": {"x": float("inf")}}}, "1 send_id does not"),
    ],
    ids=["lane", "event_type", "ordinal", "payload", "not an object", "1e400 read back"],
)
async def test_a_sealed_row_whose_columns_or_payload_were_rewritten_is_skipped_and_paged(
    registry: Registry, journal: JournalSubject, changes: dict[str, Any], why: str
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    [row] = journal.rows(KEY)
    journal.tamper(KEY, row.send_id, **changes)
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.replayed == 0 and journal.stamped(KEY) == set()
        [(severity, text)] = pager.pages
        assert severity == "P1" and row.send_id in text and why in text
        assert "forged" not in text
    finally:
        await res.interpreter.stop()


async def test_a_sealed_send_id_with_no_row_is_paged(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    [row] = journal.rows(KEY)
    journal.drop(KEY, row.send_id)
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.replayed == 0
        [(severity, text)] = pager.pages
        assert severity == "P1" and "1 sealed row(s) missing" in text and row.send_id in text
    finally:
        await res.interpreter.stop()


async def test_a_second_restore_of_the_same_snapshot_replays_and_pages_nothing(
    registry: Registry, journal: JournalSubject
) -> None:
    """A crash after the replay: the sealed rows are stamped, present, and not missing."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    restorer = _restorer(registry, keys, audit, pager, journal)
    env = await _sealed(registry, keys, journal)
    await (await restorer.restore(KEY, env)).interpreter.stop()
    again = await restorer.restore(KEY, env)
    try:
        assert again.replayed == 0 and pager.pages == []
    finally:
        await again.interpreter.stop()


async def test_a_restore_pages_once_per_key_naming_at_most_20_send_ids(
    registry: Registry, journal: JournalSubject
) -> None:
    assert persistence.PAGE_SEND_IDS_MAX == 20
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    planted = [f"{i:032x}" for i in range(25)]
    for i, sid in enumerate(planted):
        journal.plant(KEY, JournalEntry(sid, "inbox", 10 + i, "PING", _ping(i)))
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.replayed == 1
        [(severity, text)] = pager.pages
        assert severity == "P1" and "25 unreplayed row(s) skipped" in text
        assert (
            text.endswith("+5 more") and [s in text for s in planted] == [True] * 20 + [False] * 5
        )
    finally:
        await res.interpreter.stop()


def _layout_2_seal(keys: FakeKeys, chart: dict[str, Any], env: SealedSnapshot) -> Seal:
    """The tag of the layout before E50-T62 round 2: the v2 label over the same parts."""
    parts = [
        b"cv-snapshot-seal-v2",
        canonical_json(chart),
        canonical_json(env.snapshot),
        env.machine_hash.encode("utf-8"),
        str(env.version).encode("ascii"),
        *(part.encode("utf-8") for part in (KEY.machine_kind, KEY.entity_id, KEY.env)),
    ]
    mac = b"".join(len(p).to_bytes(8, "big") + p for p in parts)
    return Seal(key_id="k1", tag=hmac.new(keys.key("k1"), mac, hashlib.sha256).hexdigest())


async def test_a_layout_2_envelope_is_refused_and_quarantined(registry: Registry) -> None:
    """No upcaster: no deployment holds a snapshot, so a layout-2 envelope never verifies."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    _, blob = split_sealed_drain(env.snapshot)  # a layout-2 blob carries no cv_ key
    old = dataclasses.replace(env, snapshot=blob)
    old = dataclasses.replace(old, seal=_layout_2_seal(keys, registry.get(_KIND), old))
    with pytest.raises(RestoreRefusedError, match="bad HMAC"):
        await _restorer(registry, keys, audit, pager).restore(KEY, old)
    assert [k for k, _ in audit.quarantined] == [KEY] and [s for s, _ in pager.pages] == ["P1"]


_MISSING = object()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("cv_epoch", _MISSING), ("cv_epoch", "E0" * 16), ("cv_epoch", "e0" * 15),
        ("cv_epoch", "e0" * 16 + "\n"), ("cv_epoch", 7),
        ("cv_generation", _MISSING), ("cv_generation", 0), ("cv_generation", True),
        ("cv_generation", "1"), ("cv_generation", 1.0),
        ("cv_drained", _MISSING), ("cv_drained", "a" * 32), ("cv_drained", ["b" * 32, "a" * 32]),
        ("cv_drained", ["a" * 32, "a" * 32]), ("cv_drained", ["A" * 32]), ("cv_drained", [7]),
    ],
)  # fmt: skip
async def test_a_blob_missing_or_malforming_a_cv_key_is_refused_and_quarantined(
    registry: Registry, name: str, value: object
) -> None:
    """Sealed with a valid tag, so only the layout-3 format check refuses it."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    blob = {k: v for k, v in env.snapshot.items() if k != name}
    if value is not _MISSING:
        blob[name] = value
    tag = seal(keys, registry.get(_KIND), blob, env.machine_hash, env.version, key=KEY)
    with pytest.raises(RestoreRefusedError, match=name):
        await _restorer(registry, keys, audit, pager).restore(
            KEY, dataclasses.replace(env, snapshot=blob, seal=tag)
        )
    assert [k for k, _ in audit.quarantined] == [KEY] and [s for s, _ in pager.pages] == ["P1"]


async def test_the_library_never_sees_the_sealed_cv_keys(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    seen: list[set[str]] = []
    real = Interpreter.from_snapshot

    def spy(snapshot_str: str, *args: Any, **kwargs: Any) -> Any:
        seen.append(set(json.loads(snapshot_str)))
        return real(snapshot_str, *args, **kwargs)

    monkeypatch.setattr(Interpreter, "from_snapshot", spy)  # the class persistence restores with
    res = await _restorer(registry, keys, audit, pager).restore(KEY, env)
    await res.interpreter.stop()
    assert seen and not {"cv_epoch", "cv_generation", "cv_drained"} & seen[0]


class _StampFails(FakeJournalRows):
    """A row store whose stamp (after the re-enqueue) or whose list (before it) raises."""

    def __init__(self, error: Exception, at: str = "stamp") -> None:
        super().__init__()
        self.error, self.at = error, at

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        if self.at == "list":
            raise self.error
        return await super().list_unreplayed(key)

    async def mark_replayed(self, key: MachineKey, send_ids: Sequence[str]) -> None:
        if self.at == "stamp":
            raise self.error
        await super().mark_replayed(key, send_ids)


class _DownPager(FakePager):
    """A pager whose transport is down: it records the attempt, then raises with a text that
    must never reach a log."""

    async def page(self, key: MachineKey, severity: str, message: str) -> None:
        await super().page(key, severity, message)
        raise ConnectionError("pager transport down, token=hunter2")


class _Capturing:
    """A `DrainJournal` that keeps the interpreter its replay was handed. `stop_raises` gives it
    a `stop()` that raises `stop_error` (a `RuntimeError` unless set), `stop_hangs` one that
    never returns (E50-T63)."""

    def __init__(
        self,
        inner: DrainJournal,
        hang: bool = False,
        stop_raises: bool = False,
        stop_error: BaseException | None = None,
        stop_hangs: bool = False,
    ) -> None:
        self.inner, self.hang, self.stop_raises = inner, hang, stop_raises
        self.stop_error, self.stop_hangs = stop_error, stop_hangs
        self.interp: Interpreter[Any] | None = None
        self.entered = asyncio.Event()

    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> Any:
        return await self.inner.append(key, entries)

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        return await self.inner.list_unreplayed(key)

    async def replay_once(
        self, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
    ) -> ReplayReport:
        self.interp = interp
        self.entered.set()
        if self.stop_raises or self.stop_hangs:  # an instance attribute shadows the method
            error = self.stop_error or RuntimeError("stop() failed")
            hangs = self.stop_hangs

            async def stop(**_: object) -> None:
                if hangs:
                    await asyncio.Event().wait()
                raise error

            interp.stop = stop  # type: ignore[method-assign]  # a raising stop, for this test
        if self.hang:
            await asyncio.Event().wait()
        return await self.inner.replay_once(key, interp, drain)


_REPLAY_FAILURES = [
    ("stamp", ConnectionError("the stamp's connection was lost")),
    ("stamp", StorageTierUnavailable("statechart journal.mark_replayed failed (sqlstate 08006)")),
    ("stamp", StorageQueryFailed("40001")),
    ("stamp", ValueError("a poison row")),
    ("list", JournalListTooLargeError("refused, not truncated")),
]


@pytest.mark.parametrize(
    ("at", "error"),
    _REPLAY_FAILURES,
    ids=["stamp-ConnectionError", "stamp-StorageTierUnavailable", "stamp-StorageQueryFailed",
         "stamp-ValueError", "list-JournalListTooLargeError"],
)  # fmt: skip
async def test_a_replay_that_fails_stops_the_machine_pages_and_leaves_the_rows(
    registry: Registry, at: str, error: Exception
) -> None:
    """F7 / SR-E50T62-03 for every error the real journal raises (CR-E50T62R2-01): the rows were
    re-enqueued and then the stamp failed, or the list failed before any re-enqueue. The started
    machine is stopped (never left without an owner), one P1 page names the error type only, the
    same error is raised again without its chain, and the rows stay unstamped."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    rows = _StampFails(error, at)
    journal = _Capturing(RowStoreDrainJournal(rows))
    env = await _sealed(registry, keys, journal)
    with pytest.raises(type(error)) as failed:
        await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    assert failed.value is error
    assert failed.value.__cause__ is None and failed.value.__suppress_context__
    assert journal.interp is not None and journal.interp.status == "stopped"
    [(severity, text)] = pager.pages
    assert severity == "P1" and type(error).__name__ in text and str(error) not in text
    rows.at = "nowhere"
    unreplayed = [e.send_id for e in await rows.list_unreplayed(KEY)]
    assert unreplayed == env.snapshot["cv_drained"]


async def test_a_cancelled_replay_stops_the_machine_without_a_page(registry: Registry) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    journal = _Capturing(InMemoryDrainJournal(), hang=True)
    env = await _sealed(registry, keys, journal)
    task = asyncio.ensure_future(_restorer(registry, keys, audit, pager, journal).restore(KEY, env))
    await journal.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert journal.interp is not None and journal.interp.status == "stopped"
    assert pager.pages == []


async def test_a_start_without_a_snapshot_and_no_rows_pages_nothing(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    assert await _restorer(registry, keys, audit, pager, journal).page_unclaimed(KEY) == 0
    assert pager.pages == []


# --- CR-E50T62R2-02: the Restorer's pages are best-effort; CR-E50T62R2-05: missing ids first ---


def _page_failures(logs: Sequence[MutableMapping[str, Any]]) -> list[MutableMapping[str, Any]]:
    return [e for e in logs if e["event"] == "statechart_page_failed"]


def _failure_log(reason: str) -> dict[str, Any]:
    return {
        "event": "statechart_page_failed", "log_level": "critical",
        "machine_kind": KEY.machine_kind, "entity_id": KEY.entity_id, "env": KEY.env,
        "reason": reason, "error": "ConnectionError",
    }  # fmt: skip


async def test_a_raising_pager_after_a_clean_replay_leaves_the_machine_running_and_owned(
    registry: Registry, journal: JournalSubject
) -> None:
    """The replay succeeded and a planted row is to be paged, but the pager raises: the restore
    still returns the running machine to its caller, never an orphan, and logs CRITICAL with the
    key and the page's reason, never the pager's text or a payload."""
    keys, audit, pager = FakeKeys(), FakeAudit(), _DownPager()
    env = await _sealed(registry, keys, journal)
    journal.plant(KEY, JournalEntry("f" * 32, "inbox", 9, "PING", _ping("planted")))
    with capture_logs() as logs:
        res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.interpreter.is_running and res.replayed == 1
        assert [s for s, _ in pager.pages] == ["P1"]  # attempted once
        assert _page_failures(logs) == [_failure_log("drain journal rows skipped or missing")]
        assert "hunter2" not in repr(logs) and "planted" not in repr(logs)
    finally:
        await res.interpreter.stop()


async def test_a_raising_pager_on_a_degraded_restore_still_returns_the_latched_machine(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager, latch = FakeKeys(), FakeAudit(), _DownPager(), ChainTripLatch()
    env = await _sealed(registry, keys, journal, chain_trips=1)
    with capture_logs() as logs:
        res = await _restorer(registry, keys, audit, pager, journal, latch).restore(KEY, env)
    try:
        assert res.degraded and res.interpreter.is_running and latch.is_latched(KEY)
        assert _page_failures(logs) == [_failure_log("restored degraded")]
    finally:
        await res.interpreter.stop()


async def test_a_raising_pager_on_a_refused_restore_still_raises_the_refusal(
    registry: Registry,
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), _DownPager()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    with capture_logs() as logs, pytest.raises(RestoreRefusedError, match="bad HMAC"):
        await _restorer(registry, keys, audit, pager).restore(
            KEY, _bad_hmac(env, keys, registry.get(_KIND))
        )
    assert [k for k, _ in audit.quarantined] == [KEY]
    assert _page_failures(logs) == [_failure_log("snapshot refused")]


async def test_a_raising_pager_during_a_failed_replay_still_raises_the_original_failure(
    registry: Registry,
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), _DownPager()
    failure = StorageTierUnavailable("statechart journal.mark_replayed failed (sqlstate 08006)")
    journal = _Capturing(RowStoreDrainJournal(_StampFails(failure)))
    env = await _sealed(registry, keys, journal)
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable) as raised:
        await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    assert raised.value is failure
    assert journal.interp is not None and journal.interp.status == "stopped"
    assert _page_failures(logs) == [_failure_log("drain journal replay failed")]


async def test_a_raising_stop_during_a_failed_replay_still_raises_the_original_failure(
    registry: Registry,
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    failure = StorageQueryFailed("40001")
    journal = _Capturing(RowStoreDrainJournal(_StampFails(failure)), stop_raises=True)
    env = await _sealed(registry, keys, journal)
    try:
        with capture_logs() as logs, pytest.raises(StorageQueryFailed) as raised:
            await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
        assert raised.value is failure
        stops = [e for e in logs if e["event"] == "statechart_restore_stop_failed"]
        assert stops == [
            {"event": "statechart_restore_stop_failed", "log_level": "critical",
             "machine_kind": KEY.machine_kind, "entity_id": KEY.entity_id, "env": KEY.env,
             "error": "RuntimeError", "cv_page": True}
        ]  # fmt: skip
        [(severity, text)] = pager.pages  # the page still goes out, and says it did not stop
        assert severity == "P1" and "StorageQueryFailed" in text
        assert "could not be stopped, see the log" in text and "is stopped" not in text
    finally:
        assert journal.interp is not None
        del journal.interp.stop  # the instance override; the real stop() ends the test cleanly
        await journal.interp.stop()


async def test_a_raising_pager_at_a_start_without_a_snapshot_still_counts_the_rows(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), _DownPager()
    journal.plant(KEY, JournalEntry("f" * 32, "inbox", 0, "PING", _ping("orphan")))
    with capture_logs() as logs:
        assert await _restorer(registry, keys, audit, pager, journal).page_unclaimed(KEY) == 1
    assert _page_failures(logs) == [_failure_log("drain journal rows unclaimed")]


async def test_a_restore_page_names_the_missing_sealed_ids_before_the_skipped_ones(
    registry: Registry, journal: JournalSubject
) -> None:
    """CR-E50T62R2-05: a sealed `send_id` with no row may be a lost event, so the bounded list
    keeps it ahead of a flood of skipped rows."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    [sealed] = journal.rows(KEY)
    journal.drop(KEY, sealed.send_id)
    planted = [f"{i:032x}" for i in range(25)]
    for i, sid in enumerate(planted):
        journal.plant(KEY, JournalEntry(sid, "inbox", 10 + i, "PING", _ping(i)))
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        [(_, text)] = pager.pages
        ids = text.split("send_ids ", 1)[1]
        assert ids.startswith(sealed.send_id) and text.endswith("+6 more")
        assert [s in text for s in planted] == [True] * 19 + [False] * 6
    finally:
        await res.interpreter.stop()


# --- E50-T63: chain seeding (`prepare`), outcomes, the start-timeout stop, deadlines, mutants ---


class _Steps:
    """The order of the restore steps the chain depends on (scenario 1's first clause)."""

    def __init__(self) -> None:
        self.steps: list[str] = []
        self.outcomes: list[tuple[str, str]] = []

    async def prepare(self, key: MachineKey) -> None:
        self.steps.append(f"prepare:{key.entity_id}")

    def plugins(self, key: MachineKey) -> list[PluginBase[Any]]:
        self.steps.append("plugins")
        return [CvErrorHooks(), CvMetricsPlugin(), CvAuditPlugin()]

    def ops(self, operation: str, outcome: str) -> None:
        self.outcomes.append((operation, outcome))


class _StepAudit(FakeAudit):
    def __init__(self, steps: _Steps) -> None:
        super().__init__()
        self.order = steps

    async def quarantine(self, key: MachineKey, envelope: SealedSnapshot, reason: str) -> None:
        self.order.steps.append("quarantine")
        await super().quarantine(key, envelope, reason)


def _seeded(restorer: Restorer, steps: _Steps) -> Restorer:
    return dataclasses.replace(
        restorer, prepare=steps.prepare, plugins=steps.plugins, ops=steps.ops
    )


async def test_restore_awaits_prepare_before_the_plugins_factory(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager, steps = FakeKeys(), FakeAudit(), FakePager(), _Steps()
    env = await _sealed(registry, keys, journal)
    res = await _seeded(_restorer(registry, keys, audit, pager, journal), steps).restore(KEY, env)
    try:
        assert steps.steps == [f"prepare:{KEY.entity_id}", "plugins"]
        assert steps.outcomes == [("restore", "ok")]
    finally:
        await res.interpreter.stop()


async def test_restore_awaits_prepare_before_a_refusals_quarantine_row(registry: Registry) -> None:
    keys, pager, steps = FakeKeys(), FakePager(), _Steps()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    restorer = _seeded(_restorer(registry, keys, _StepAudit(steps), pager), steps)
    with pytest.raises(RestoreRefusedError):
        await restorer.restore(KEY, _bad_hmac(env, keys, registry.get(_KIND)))
    assert steps.steps == [f"prepare:{KEY.entity_id}", "quarantine"]
    assert steps.outcomes == [("restore", "refused")]


async def test_a_prepare_that_fails_is_a_chain_seed_error_and_nothing_is_restored(
    registry: Registry,
) -> None:
    """No machine starts a chain that could fork: no plugins, no quarantine row, no page."""
    keys, audit, pager, steps = FakeKeys(), FakeAudit(), FakePager(), _Steps()
    env = await _sealed(registry, keys, InMemoryDrainJournal())

    async def prepare(key: MachineKey) -> None:
        raise ConnectionError("the chain head could not be read")

    restorer = _seeded(_restorer(registry, keys, audit, pager), steps)
    restorer.prepare = prepare
    with pytest.raises(ChainSeedError, match="ConnectionError") as raised:
        await restorer.restore(KEY, env)
    assert raised.value.__cause__ is None and raised.value.key == KEY
    assert steps.steps == [] and audit.quarantined == [] and pager.pages == []
    assert steps.outcomes == [("restore", "error")]


async def test_a_degraded_restore_is_counted_degraded(
    registry: Registry, journal: JournalSubject
) -> None:
    keys, audit, pager, steps = FakeKeys(), FakeAudit(), FakePager(), _Steps()
    env = await _sealed(registry, keys, journal, chain_trips=1)
    restorer = _seeded(_restorer(registry, keys, audit, pager, journal), steps)
    res = await restorer.restore(KEY, env)
    await res.interpreter.stop()
    assert steps.outcomes == [("restore", "degraded")]


async def test_a_failed_replay_is_counted_as_an_error(registry: Registry) -> None:
    keys, audit, pager, steps = FakeKeys(), FakeAudit(), FakePager(), _Steps()
    journal = _Capturing(RowStoreDrainJournal(_StampFails(StorageQueryFailed("40001"))))
    env = await _sealed(registry, keys, journal)
    with pytest.raises(StorageQueryFailed):
        await _seeded(_restorer(registry, keys, audit, pager, journal), steps).restore(KEY, env)
    assert steps.outcomes == [("restore", "error")]


@virtual
async def test_a_start_that_does_not_settle_is_stopped_paged_and_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3898: the start timeout stops the interpreter it started, as a failed replay does; the
    bound runs on the virtual loop's fake seconds."""
    registry = Registry(machines_dir=_FIXTURES)
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    started: list[Interpreter[Any]] = []
    real_start = Interpreter.start

    async def start_that_never_settles(self: Interpreter[Any]) -> Any:
        await real_start(self)
        started.append(self)
        await asyncio.Event().wait()

    monkeypatch.setattr(Interpreter, "start", start_that_never_settles)
    with pytest.raises(TimeoutError, match="CV-C56"):
        await _restorer(registry, keys, audit, pager).restore(KEY, env)
    [interp] = started
    assert interp.status == "stopped"
    [(severity, text)] = pager.pages
    assert severity == "P1" and "did not settle" in text and "is stopped" in text


class _BringUp(PluginBase[Any]):
    """An owner's extra plugin with a bring-up, in the machines feed's slot (#3978)."""

    def __init__(self, steps: _Steps) -> None:
        self.order = steps

    def cv_bring_up(self, interpreter: Any) -> None:
        self.order.steps.append("bring_up")


def _record_start(monkeypatch: pytest.MonkeyPatch, steps: _Steps, *, settles: bool) -> None:
    real_start = Interpreter.start

    async def start(self: Interpreter[Any]) -> Any:
        result = await real_start(self)
        steps.steps.append("start")
        if not settles:
            await asyncio.Event().wait()
        return result

    monkeypatch.setattr(Interpreter, "start", start)


async def test_a_seeded_restore_brings_up_extra_plugins_after_start_before_the_replay(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The merged order (#3801 on #3978): the seed, then the triple with the owner's extra plugins
    after it, then `start()`, then each `cv_bring_up`, then the replay."""
    keys, audit, pager, steps = FakeKeys(), FakeAudit(), FakePager(), _Steps()
    journal = InMemoryDrainJournal()
    env = await _sealed(registry, keys, journal)
    replay = journal.replay_once

    async def spy(*args: Any) -> ReplayReport:
        steps.steps.append("replay")
        return await replay(*args)

    monkeypatch.setattr(journal, "replay_once", spy)
    _record_start(monkeypatch, steps, settles=True)
    restorer = _seeded(_restorer(registry, keys, audit, pager, journal), steps)
    res = await restorer.restore(KEY, env, extra_plugins=[_BringUp(steps)])
    try:
        assert steps.steps == [f"prepare:{KEY.entity_id}", "plugins", "start", "bring_up", "replay"]
        names = [type(getattr(p, "_plugin", p)).__name__ for p in res.interpreter._plugins]
        assert names == ["CvErrorHooks", "CvMetricsPlugin", "CvAuditPlugin", "_BringUp"]
    finally:
        await res.interpreter.stop()


@virtual
async def test_a_start_that_does_not_settle_never_brings_up_the_extra_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A machine that did not start is stopped and paged (#3898) and never brought up (#3978)."""
    registry = Registry(machines_dir=_FIXTURES)
    keys, audit, pager, steps = FakeKeys(), FakeAudit(), FakePager(), _Steps()
    env = await _sealed(registry, keys, InMemoryDrainJournal())
    _record_start(monkeypatch, steps, settles=False)
    restorer = _seeded(_restorer(registry, keys, audit, pager), steps)
    with pytest.raises(TimeoutError, match="CV-C56"):
        await restorer.restore(KEY, env, extra_plugins=[_BringUp(steps)])
    assert steps.steps == [f"prepare:{KEY.entity_id}", "plugins", "start"]
    assert [s for s, _ in pager.pages] == ["P1"] and steps.outcomes == [("restore", "error")]


async def test_a_hanging_pager_is_cut_by_its_deadline(
    registry: Registry, journal: JournalSubject, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3898 (SR-E50T62-04): a page that never returns is cut; the restore still returns."""
    monkeypatch.setattr(persistence, "PAGE_TIMEOUT_S", 0.0)

    class _Hangs(FakePager):
        async def page(self, key: MachineKey, severity: str, message: str) -> None:
            await super().page(key, severity, message)
            await asyncio.Event().wait()

    keys, audit, pager, latch = FakeKeys(), FakeAudit(), _Hangs(), ChainTripLatch()
    env = await _sealed(registry, keys, journal, chain_trips=1)
    with capture_logs() as logs:
        res = await _restorer(registry, keys, audit, pager, journal, latch).restore(KEY, env)
    try:
        assert res.degraded and [s for s, _ in pager.pages] == ["P1"]
        assert [e["error"] for e in _page_failures(logs)] == ["TimeoutError"]
    finally:
        await res.interpreter.stop()


async def test_a_hanging_stop_is_cut_and_the_page_says_it_could_not_be_stopped(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(persistence, "STOP_TIMEOUT_S", 0.0)
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    failure = StorageQueryFailed("40001")
    journal = _Capturing(RowStoreDrainJournal(_StampFails(failure)), stop_hangs=True)
    env = await _sealed(registry, keys, journal)
    try:
        with capture_logs() as logs, pytest.raises(StorageQueryFailed) as raised:
            await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
        assert raised.value is failure
        stops = [e for e in logs if e["event"] == "statechart_restore_stop_failed"]
        assert [(e["error"], e["cv_page"]) for e in stops] == [("TimeoutError", True)]
        [(_, text)] = pager.pages
        assert "could not be stopped, see the log" in text
    finally:
        assert journal.interp is not None
        del journal.interp.stop
        await journal.interp.stop()


async def test_a_cancelled_replay_whose_stop_raises_still_passes_the_cancellation(
    registry: Registry,
) -> None:
    """Mutant (#3898): the cancel branch's `_stop` with a raising `stop()`."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    journal = _Capturing(InMemoryDrainJournal(), hang=True, stop_raises=True)
    env = await _sealed(registry, keys, journal)
    task = asyncio.ensure_future(_restorer(registry, keys, audit, pager, journal).restore(KEY, env))
    await journal.entered.wait()
    try:
        with capture_logs() as logs:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        stops = [e["error"] for e in logs if e["event"] == "statechart_restore_stop_failed"]
        assert stops == ["RuntimeError"] and pager.pages == []
    finally:
        assert journal.interp is not None
        del journal.interp.stop
        await journal.interp.stop()


async def test_a_cancellation_inside_the_pager_passes_through_page(registry: Registry) -> None:
    """Mutant (#3898): `_page` contains an `Exception`, never a cancellation."""

    class _Cancelled(FakePager):
        async def page(self, key: MachineKey, severity: str, message: str) -> None:
            raise asyncio.CancelledError

    keys, audit, latch = FakeKeys(), FakeAudit(), ChainTripLatch()
    journal = _Capturing(InMemoryDrainJournal())
    env = await _sealed(registry, keys, journal, chain_trips=1)
    with pytest.raises(asyncio.CancelledError):
        await _restorer(registry, keys, audit, _Cancelled(), journal, latch).restore(KEY, env)
    assert journal.interp is not None
    await journal.interp.stop()


async def test_a_cancellation_inside_stop_passes_through_stop(registry: Registry) -> None:
    """Mutant (#3898): `_stop` contains an `Exception`, never a cancellation; the page that
    would follow the stop is not sent."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    failure = StorageQueryFailed("40001")
    journal = _Capturing(
        RowStoreDrainJournal(_StampFails(failure)),
        stop_raises=True,
        stop_error=asyncio.CancelledError(),
    )
    env = await _sealed(registry, keys, journal)
    try:
        with pytest.raises(asyncio.CancelledError):
            await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
        assert pager.pages == []
    finally:
        assert journal.interp is not None
        del journal.interp.stop
        await journal.interp.stop()


async def test_a_restore_page_states_the_missing_count_before_the_skipped_count(
    registry: Registry, journal: JournalSubject
) -> None:
    """Mutant (#3898): the clause order of the restore page, missing first."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    env = await _sealed(registry, keys, journal)
    [sealed] = journal.rows(KEY)
    journal.drop(KEY, sealed.send_id)
    for i in range(2):
        journal.plant(KEY, JournalEntry(f"{i:032x}", "inbox", 10 + i, "PING", _ping(i)))
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        [(_, text)] = pager.pages
        assert text.startswith(
            "drain journal: 1 sealed row(s) missing, 2 unreplayed row(s) skipped "
            "(2 not in the sealed drained set); nothing of them replayed or stamped; "
        )
    finally:
        await res.interpreter.stop()


async def test_a_failing_orphan_scan_pages_p1_by_its_type_and_raises(registry: Registry) -> None:
    """#3898: a start without a verified snapshot whose scan fails must not start the machine."""
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    failure = JournalListTooLargeError("refused, not truncated")
    rows = _StampFails(failure, at="list")
    restorer = _restorer(registry, keys, audit, pager, RowStoreDrainJournal(rows))
    with pytest.raises(JournalListTooLargeError):
        await restorer.page_unclaimed(KEY)
    [(severity, text)] = pager.pages
    assert severity == "P1" and "JournalListTooLargeError" in text and "not truncated" not in text
    assert "not started" in text
