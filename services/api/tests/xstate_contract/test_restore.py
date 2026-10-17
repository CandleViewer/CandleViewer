"""tests/xstate_contract/test_restore.py — E50-T49 restore + HMAC envelope.

Gherkin (ticket E50-T49):
  1. bad HMAC / wrong machine_hash / version 2 -> refused, quarantined, P1 page;
  2. plugins are attached via from_snapshot(plugins=);
  3. a snapshot with chain_trips = 1 restores degraded: reads served, order
     commands refused.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from xstate_statemachine import Event, PluginBase, SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart import factory as cv_factory
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    DegradedLatchError,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    RestoreRefusedError,
    Seal,
    SealedSnapshot,
    hmac_sealer,
    open_sealed,
    reconcile_counts,
    seal,
)
from candleviewer.statechart.registry import Registry
from tests.xstate_contract.persist_fixtures import binding_persist  # noqa: F401

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
    def __init__(self) -> None:
        self.rows: dict[MachineKey, SealedSnapshot] = {}

    async def write_snapshot(self, key: MachineKey, envelope: SealedSnapshot) -> None:
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


def _restorer(
    registry: Registry,
    keys: FakeKeys,
    audit: FakeAudit,
    pager: FakePager,
    journal: InMemoryDrainJournal | None = None,
    latch: ChainTripLatch | None = None,
) -> Restorer:
    return Restorer(
        registry=registry,
        keys=keys,
        journal=journal or InMemoryDrainJournal(),
        audit=audit,
        pager=pager,
        latch=latch or ChainTripLatch(),
        plugins=lambda: [CvErrorHooks(), CvMetricsPlugin(), CvAuditPlugin()],
        clock=SimulatedClock(),
        lane="platform",
    )


async def _sealed(
    registry: Registry, keys: FakeKeys, journal: InMemoryDrainJournal, chain_trips: int = 0
) -> SealedSnapshot:
    res = await build(_KIND, clock=SimulatedClock(), lane="platform", registry=registry)
    interp = res.interpreter
    interp.chain_trips = chain_trips
    interp._enqueue_restored(Event("PING", {"n": "pending"}))
    repo = FakeRepo()
    await Persister(
        repo=repo,
        journal=journal,
        audit=FakeAudit(),
        seal=hmac_sealer(keys, registry.get(_KIND)),
        machine_hash_of=registry.hash,
    ).persist(interp, key=KEY)
    return repo.rows[KEY]


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


async def test_restore_after_key_rotation_uses_envelope_key_id(registry: Registry) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    journal = InMemoryDrainJournal()
    env = await _sealed(registry, keys, journal)
    keys.cur = "k2"  # rotated after sealing
    res = await _restorer(registry, keys, audit, pager, journal).restore(KEY, env)
    try:
        assert res.replayed == 1 and not res.degraded
        assert audit.quarantined == [] and pager.pages == []
    finally:
        await res.interpreter.stop()


async def test_restore_attaches_plugins_via_from_snapshot(registry: Registry) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    journal = InMemoryDrainJournal()
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


async def test_restore_chain_trip_latch_serves_reads_refuses_orders(registry: Registry) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    journal, latch = InMemoryDrainJournal(), ChainTripLatch()
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


async def test_factory_restore_delegates(registry: Registry) -> None:
    keys, audit, pager = FakeKeys(), FakeAudit(), FakePager()
    journal = InMemoryDrainJournal()
    env = await _sealed(registry, keys, journal)
    res = await cv_factory.restore(_restorer(registry, keys, audit, pager, journal), KEY, env)
    await res.interpreter.stop()
