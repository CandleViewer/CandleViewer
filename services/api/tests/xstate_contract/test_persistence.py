"""tests/xstate_contract/test_persistence.py — E50-T10 quiescent persist + drain journal.

Gherkin (ticket E50-T10):
  1. un-started interpreter is never persisted (AssertionError, no row);
  2. pending events on both lanes survive shutdown and replay exactly once,
     priority first (CV-C65');
  3. a context carrying `_fault` is refused and audited (MUST-01).
Plus: crash between journal append and snapshot write is idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from xstate_statemachine import Event, Interpreter, SimulatedClock, create_machine

from candleviewer.statechart import build
from candleviewer.statechart.bindings import load_binding_maps
from candleviewer.statechart.persistence import (
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    PersistRefusedError,
    SealedSnapshot,
    stable_send_id,
)
from candleviewer.statechart.registry import Registry
from tests.xstate_contract.persist_fixtures import binding_persist  # noqa: F401

_FIXTURES = Path(__file__).resolve().parent / "persist_fixtures"
_KIND = "persist_min"
KEY = MachineKey(_KIND, "00000000-0000-0000-0000-000000000001", "demo")


class FakeRepo:
    def __init__(self, fail: bool = False) -> None:
        self.rows: dict[MachineKey, SealedSnapshot] = {}
        self.fail = fail

    async def write_snapshot(self, key: MachineKey, envelope: SealedSnapshot) -> None:
        if self.fail:
            raise ConnectionError("simulated crash before snapshot write")
        self.rows[key] = envelope


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, MachineKey, str]] = []

    async def drain_error(self, key: MachineKey, error: str) -> None:
        self.events.append(("drain_error", key, error))

    async def persist_refused(self, key: MachineKey, reason: str) -> None:
        self.events.append(("persist_refused", key, reason))


async def _seal(blob: dict[str, Any], machine_hash: str, version: int, key: MachineKey) -> str:
    return f"stub-seal:{key.machine_kind}/{key.entity_id}/{key.env}:{machine_hash}:{version}"


@pytest.fixture()
def registry() -> Registry:
    return Registry(machines_dir=_FIXTURES)


def _persister(
    registry: Registry, repo: FakeRepo, journal: InMemoryDrainJournal, audit: FakeAudit
) -> Persister:
    return Persister(
        repo=repo, journal=journal, audit=audit, seal=_seal, machine_hash_of=registry.hash
    )


async def _started(registry: Registry) -> Interpreter[Any]:
    res = await build(_KIND, clock=SimulatedClock(), lane="platform", registry=registry)
    return res.interpreter


async def test_persist_unstarted_interpreter_raises_and_writes_nothing(registry: Registry) -> None:
    maps = load_binding_maps(_KIND)
    from xstate_statemachine import MachineLogic

    machine = create_machine(
        registry.get(_KIND),
        logic=MachineLogic(actions=maps.actions, guards=maps.guards, services=maps.services),
    )
    interp: Interpreter[Any] = Interpreter(machine)
    repo, journal, audit = FakeRepo(), InMemoryDrainJournal(), FakeAudit()
    with pytest.raises(AssertionError, match="CV-C40"):
        await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
    assert repo.rows == {}
    assert journal.rows(KEY) == []


async def test_persist_pending_both_lanes_replayed_once_priority_first(registry: Registry) -> None:
    interp = await _started(registry)
    # Queue synchronously (no await) so the run loop cannot consume them
    # before persist drains: 2 inbox, 1 priority.
    interp._enqueue_restored(Event("PING", {"n": "inbox-1"}))
    interp._enqueue_restored(Event("PING", {"n": "inbox-2"}))
    interp._enqueue_restored(Event("PING", {"n": "prio-1"}), priority=True)
    repo, journal, audit = FakeRepo(), InMemoryDrainJournal(), FakeAudit()
    await _persister(registry, repo, journal, audit).persist(interp, key=KEY)

    assert interp.status == "stopped"
    rows = journal.rows(KEY)
    assert [(r.lane, r.record["payload"]["n"]) for r in rows] == [
        ("priority", "prio-1"),
        ("inbox", "inbox-1"),
        ("inbox", "inbox-2"),
    ]
    env = repo.rows[KEY]
    assert env.machine_hash == registry.hash(_KIND)
    assert env.snapshot["pending_events"] == []  # drained into the journal, not the blob
    assert "children" not in env.snapshot or env.snapshot["children"] in ({}, [], None)

    # Restore (E50-T49 owns the production path; direct call is contract-suite only).
    maps = load_binding_maps(_KIND)
    from xstate_statemachine import MachineLogic

    machine = create_machine(
        registry.get(_KIND),
        logic=MachineLogic(actions=maps.actions, guards=maps.guards, services=maps.services),
    )
    restored: Interpreter[Any] = Interpreter.from_snapshot(
        json.dumps(env.snapshot), machine, minimum_version=3, plugins=[]
    )
    await restored.start()
    try:
        assert await journal.replay_once(KEY, restored) == 3
        assert await journal.replay_once(KEY, restored) == 0  # exactly once
        receipt = await restored.send("PING", wait=True, n="after")
        assert receipt is not None and receipt.error is None
        assert restored.context["seen"] == ["prio-1", "inbox-1", "inbox-2", "after"]
    finally:
        await restored.stop()


async def test_persist_hands_the_sealer_the_persisted_key(registry: Registry) -> None:
    interp = await _started(registry)
    repo, journal, audit = FakeRepo(), InMemoryDrainJournal(), FakeAudit()
    await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
    env = repo.rows[KEY]
    assert env.key == KEY
    want = f"stub-seal:{_KIND}/{KEY.entity_id}/{KEY.env}:{env.machine_hash}:{env.version}"
    assert env.seal == want


async def test_persist_faulted_context_refused_and_audited(registry: Registry) -> None:
    interp = await _started(registry)
    interp.context["_fault"] = {"kind": "ActionError"}
    repo, journal, audit = FakeRepo(), InMemoryDrainJournal(), FakeAudit()
    try:
        with pytest.raises(PersistRefusedError, match="MUST-01"):
            await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
        assert repo.rows == {}
        assert [e[0] for e in audit.events] == ["persist_refused"]
        assert interp.is_running  # refusal leaves the machine for the supervisor
    finally:
        await interp.stop()


async def test_crash_between_journal_and_snapshot_is_idempotent(registry: Registry) -> None:
    journal, audit = InMemoryDrainJournal(), FakeAudit()
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": "x"}))
    with pytest.raises(ConnectionError):
        await _persister(registry, FakeRepo(fail=True), journal, audit).persist(interp, key=KEY)
    first = journal.rows(KEY)
    assert len(first) == 1
    # Re-append of the same drained event (retry) dedupes on send_id.
    await journal.append(KEY, first)
    assert journal.rows(KEY) == first
    await interp.stop()


async def test_drained_waiter_receipt_is_audited(registry: Registry) -> None:
    interp = await _started(registry)
    ev = Event("PING", {"n": "w"})
    interp._enqueue_restored(ev)
    fut = interp._loop.create_future()  # type: ignore[union-attr]
    interp._receipts[id(ev)] = fut
    repo, journal, audit = FakeRepo(), InMemoryDrainJournal(), FakeAudit()
    await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
    assert audit.events == [("drain_error", KEY, "InterpreterStoppedError")]
    assert journal.rows(KEY)[0].receipt_error == "InterpreterStoppedError"
    assert fut.result().error is not None


def test_stable_send_id_is_deterministic() -> None:
    rec = {"kind": "event", "type": "PING", "payload": {"n": 1}}
    assert stable_send_id(KEY, 0, rec) == stable_send_id(KEY, 0, dict(rec))
    assert stable_send_id(KEY, 0, rec) != stable_send_id(KEY, 1, rec)
