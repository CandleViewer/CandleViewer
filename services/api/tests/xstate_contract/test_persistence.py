"""tests/xstate_contract/test_persistence.py — E50-T10 quiescent persist + drain journal.

Gherkin (ticket E50-T10):
  1. un-started interpreter is never persisted (AssertionError, no row);
  2. pending events on both lanes survive shutdown and replay exactly once,
     priority first (CV-C65');
  3. a context carrying `_fault` is refused and audited (MUST-01).
Plus: crash between journal append and snapshot write is idempotent.

Every journal case runs twice (E50-T62): on the reference `InMemoryDrainJournal` and on the
Postgres journal's replay, `RowStoreDrainJournal`, over an in-memory row store.

E50-T62 round 2 (24 §17.6, `SEAL_LAYOUT_V = 3`): the `send_id` hashes the life's `cv_epoch` and
the persist's `cv_generation`; the blob seals both and `cv_drained`; an append conflict is a retry
only on an unreplayed row with the same payload text, and any other is paged P1 once per persist.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import re
import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from structlog.testing import capture_logs
from xstate_statemachine import Event, Interpreter, SimulatedClock, create_machine
from xstate_statemachine.events import persist_event

from candleviewer.statechart import build, persistence
from candleviewer.statechart.bindings import load_binding_maps
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.persistence import (
    JournalConflict,
    JournalEntry,
    MachineKey,
    Persister,
    PersistRefusedError,
    SealedSnapshot,
    split_sealed_drain,
    stable_send_id,
)
from candleviewer.statechart.registry import Registry
from tests.xstate_contract.persist_fixtures import binding_persist
from tests.xstate_contract.persist_fixtures.journals import JOURNALS, JournalSubject

_FIXTURES = Path(__file__).resolve().parent / "persist_fixtures"
_KIND = "persist_min"
KEY = MachineKey(_KIND, "00000000-0000-0000-0000-000000000001", "demo")
EPOCH = "e0" * 16
_HEX32 = re.compile(r"[0-9a-f]{32}")


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


class FakePager:
    def __init__(self) -> None:
        self.pages: list[tuple[str, str]] = []

    async def page(self, key: MachineKey, severity: str, message: str) -> None:
        self.pages.append((severity, message))


async def _seal(blob: dict[str, Any], machine_hash: str, version: int, key: MachineKey) -> str:
    return f"stub-seal:{key.machine_kind}/{key.entity_id}/{key.env}:{machine_hash}:{version}"


@pytest.fixture()
def registry() -> Registry:
    return Registry(machines_dir=_FIXTURES)


@pytest.fixture(params=list(JOURNALS))
def journal(request: pytest.FixtureRequest) -> JournalSubject:
    return JOURNALS[request.param]()


def _persister(
    registry: Registry,
    repo: FakeRepo,
    journal: JournalSubject,
    audit: FakeAudit,
    pager: FakePager | None = None,
    epoch: str | None = EPOCH,
) -> Persister:
    persister = Persister(
        repo=repo,
        journal=journal,
        audit=audit,
        seal=_seal,
        machine_hash_of=registry.hash,
        pager=pager or FakePager(),
    )
    if epoch is None:
        return persister
    # `epoch_source` is the test-only seam (production keeps the OS CSPRNG): seeded here, so a
    # test can predict the send_id the next persist writes.
    return dataclasses.replace(persister, epoch_source=lambda: epoch)


async def _started(registry: Registry) -> Interpreter[Any]:
    res = await build(_KIND, clock=SimulatedClock(), lane="platform", registry=registry)
    return res.interpreter


async def test_persist_unstarted_interpreter_raises_and_writes_nothing(
    registry: Registry, journal: JournalSubject
) -> None:
    maps = load_binding_maps(_KIND)
    from xstate_statemachine import MachineLogic

    machine = create_machine(
        registry.get(_KIND),
        logic=MachineLogic(actions=maps.actions, guards=maps.guards, services=maps.services),
    )
    interp: Interpreter[Any] = Interpreter(machine)
    repo, audit = FakeRepo(), FakeAudit()
    with pytest.raises(AssertionError, match="CV-C40"):
        await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
    assert repo.rows == {}
    assert journal.rows(KEY) == []


async def test_persist_pending_both_lanes_replayed_once_priority_first(
    registry: Registry, journal: JournalSubject
) -> None:
    interp = await _started(registry)
    # Queue synchronously (no await) so the run loop cannot consume them
    # before persist drains: 2 inbox, 1 priority.
    interp._enqueue_restored(Event("PING", {"n": "inbox-1"}))
    interp._enqueue_restored(Event("PING", {"n": "inbox-2"}))
    interp._enqueue_restored(Event("PING", {"n": "prio-1"}), priority=True)
    repo, audit = FakeRepo(), FakeAudit()
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
    drain, blob = split_sealed_drain(env.snapshot)
    restored: Interpreter[Any] = Interpreter.from_snapshot(
        json.dumps(blob), machine, minimum_version=3, plugins=[]
    )
    await restored.start()
    try:
        assert (await journal.replay_once(KEY, restored, drain)).replayed == 3
        assert (await journal.replay_once(KEY, restored, drain)).replayed == 0  # exactly once
        receipt = await restored.send("PING", wait=True, n="after")
        assert receipt is not None and receipt.error is None
        assert restored.context["seen"] == ["prio-1", "inbox-1", "inbox-2", "after"]
    finally:
        await restored.stop()


async def test_persist_hands_the_sealer_the_persisted_key(
    registry: Registry, journal: JournalSubject
) -> None:
    interp = await _started(registry)
    repo, audit = FakeRepo(), FakeAudit()
    await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
    env = repo.rows[KEY]
    assert env.key == KEY
    want = f"stub-seal:{_KIND}/{KEY.entity_id}/{KEY.env}:{env.machine_hash}:{env.version}"
    assert env.seal == want


async def test_persist_faulted_context_refused_and_audited(
    registry: Registry, journal: JournalSubject
) -> None:
    interp = await _started(registry)
    interp.context["_fault"] = {"kind": "ActionError"}
    repo, audit = FakeRepo(), FakeAudit()
    try:
        with pytest.raises(PersistRefusedError, match="MUST-01"):
            await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
        assert repo.rows == {}
        assert [e[0] for e in audit.events] == ["persist_refused"]
        assert interp.is_running  # refusal leaves the machine for the supervisor
    finally:
        await interp.stop()


async def test_crash_between_journal_and_snapshot_is_idempotent(
    registry: Registry, journal: JournalSubject
) -> None:
    audit = FakeAudit()
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": "x"}))
    with pytest.raises(ConnectionError):
        await _persister(registry, FakeRepo(fail=True), journal, audit).persist(interp, key=KEY)
    first = journal.rows(KEY)
    assert len(first) == 1
    # Re-append of the same drained event (retry) dedupes on send_id: an unreplayed row with the
    # same payload text is the one conflict that is not a fault.
    conflicts = await journal.append(KEY, first)
    assert conflicts == [JournalConflict(first[0].send_id, stamped=False, same_payload=True)]
    assert conflicts[0].is_retry
    assert journal.rows(KEY) == first
    await interp.stop()


async def test_drained_waiter_receipt_is_audited(
    registry: Registry, journal: JournalSubject
) -> None:
    interp = await _started(registry)
    ev = Event("PING", {"n": "w"})
    interp._enqueue_restored(ev)
    fut = interp._loop.create_future()  # type: ignore[union-attr]
    interp._receipts[id(ev)] = fut
    repo, audit = FakeRepo(), FakeAudit()
    await _persister(registry, repo, journal, audit).persist(interp, key=KEY)
    assert audit.events == [("drain_error", KEY, "InterpreterStoppedError")]
    assert journal.rows(KEY)[0].receipt_error == "InterpreterStoppedError"
    assert fut.result().error is not None


def test_stable_send_id_is_deterministic() -> None:
    rec = {"kind": "event", "type": "PING", "payload": {"n": 1}}
    assert stable_send_id(KEY, EPOCH, 1, 0, rec) == stable_send_id(KEY, EPOCH, 1, 0, dict(rec))
    assert stable_send_id(KEY, EPOCH, 1, 0, rec) != stable_send_id(KEY, EPOCH, 1, 1, rec)


# --- E50-T62 round 2: the life, the generation and the append conflict rule (24 §17.6) ---


def _record(n: str) -> dict[str, Any]:
    """The record the persister journals for an inbox `PING` (the library's `persist_event`)."""
    return persist_event(Event("PING", {"n": n}))


def _predicted(n: str, generation: int = 1, ordinal: int = 0) -> str:
    """The send_id a persist of the seeded life writes for an inbox `PING` at `ordinal`."""
    return stable_send_id(KEY, EPOCH, generation, ordinal, _record(n))


def test_the_send_id_is_the_contract_hash_of_its_seven_inputs() -> None:
    """24 §17.6: the first 32 hex of sha256 over `[machine_kind, entity_id, env, cv_epoch,
    cv_generation, ordinal, record]` in canonical JSON (sorted keys, no spaces, ASCII), no NaN."""
    rec = {"kind": "event", "type": "PING", "payload": {"n": "é✓", "f": 0.5, "big": 1e16}}
    canon = json.dumps(
        [KEY.machine_kind, KEY.entity_id, KEY.env, EPOCH, 3, 2, rec],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    want = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]
    assert stable_send_id(KEY, EPOCH, 3, 2, rec) == want


@pytest.mark.parametrize(
    "field", ["machine_kind", "entity_id", "env", "epoch", "generation", "ordinal", "record"]
)
def test_every_send_id_input_changes_the_id(field: str) -> None:
    base: dict[str, Any] = {
        "key": KEY, "epoch": EPOCH, "generation": 1, "ordinal": 0, "record": _record("x")
    }  # fmt: skip
    other: dict[str, Any] = {
        "epoch": "e1" * 16, "generation": 2, "ordinal": 1, "record": _record("y")
    }  # fmt: skip
    changed = dict(base)
    if field in other:
        changed[field] = other[field]
    else:
        changed["key"] = dataclasses.replace(KEY, **{field: "other"})
    assert stable_send_id(**changed) != stable_send_id(**base)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_send_id_over_nan_or_infinity_is_an_error_never_a_string(value: float) -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        stable_send_id(KEY, EPOCH, 1, 0, {"payload": {"x": value}})


def test_a_send_id_over_a_value_json_cannot_hold_is_an_error_never_a_string() -> None:
    with pytest.raises(TypeError, match="not JSON serializable"):
        stable_send_id(KEY, EPOCH, 1, 0, {"payload": {"at": object()}})


async def test_a_persist_seals_its_epoch_generation_and_drained_set(
    registry: Registry, journal: JournalSubject
) -> None:
    """`cv_drained` is sorted by `send_id`, not in drain order (8 rows: 1 in 40 320 by chance)."""
    interp = await _started(registry)
    for i in range(7):
        interp._enqueue_restored(Event("PING", {"n": f"inbox-{i}"}))
    interp._enqueue_restored(Event("PING", {"n": "a"}), priority=True)
    repo = FakeRepo()
    await _persister(registry, repo, journal, FakeAudit()).persist(interp, key=KEY)
    blob, rows = repo.rows[KEY].snapshot, journal.rows(KEY)
    assert (blob["cv_epoch"], blob["cv_generation"]) == (EPOCH, 1) and len(rows) == 8
    assert blob["cv_drained"] == sorted(r.send_id for r in rows)
    assert blob["cv_drained"] != [r.send_id for r in rows]  # the drain order is another
    assert all(r.send_id == stable_send_id(KEY, EPOCH, 1, r.ordinal, r.record) for r in rows)


async def test_an_empty_drain_seals_an_empty_drained_set(
    registry: Registry, journal: JournalSubject
) -> None:
    repo = FakeRepo()
    await _persister(registry, repo, journal, FakeAudit()).persist(
        await _started(registry), key=KEY
    )
    assert repo.rows[KEY].snapshot["cv_drained"] == [] and journal.rows(KEY) == []


async def test_a_genuine_retry_conflict_is_a_no_op_and_pages_nothing(
    registry: Registry, journal: JournalSubject
) -> None:
    """An unreplayed row with this entry's payload text is this drain's own row (an append whose
    outcome was unknown): the append keeps it and pages nothing."""
    earlier = JournalEntry(_predicted("x"), "inbox", 0, "PING", _record("x"))
    journal.plant(KEY, earlier)
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": "x"}))
    repo, pager = FakeRepo(), FakePager()
    await _persister(registry, repo, journal, FakeAudit(), pager).persist(interp, key=KEY)
    assert pager.pages == [] and journal.rows(KEY) == [earlier]
    assert journal.stamped(KEY) == set() and repo.rows[KEY].snapshot["cv_drained"] == [
        earlier.send_id
    ]


async def test_a_conflict_with_a_stamped_row_is_a_persist_fault_paged_once(
    registry: Registry, journal: JournalSubject
) -> None:
    """A row cv_app planted already stamped under the send_id the persist writes would swallow
    the event: the persist pages P1 with the send_id (MUST-01) and still writes its snapshot."""
    sid = _predicted("x")
    journal.plant(KEY, JournalEntry(sid, "inbox", 0, "PING", _record("x")), stamped=True)
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": "x"}))
    repo, pager = FakeRepo(), FakePager()
    await _persister(registry, repo, journal, FakeAudit(), pager).persist(interp, key=KEY)
    [(severity, text)] = pager.pages
    assert severity == "P1" and sid in text and "MUST-01" in text and "1 stamped" in text
    assert repo.rows[KEY].snapshot["cv_drained"] == [sid] and interp.status == "stopped"


async def test_a_conflict_with_another_payload_is_a_persist_fault_paged_once(
    registry: Registry, journal: JournalSubject
) -> None:
    sid = _predicted("x")
    journal.plant(KEY, JournalEntry(sid, "inbox", 0, "PING", _record("forged")))
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": "x"}))
    repo, pager = FakeRepo(), FakePager()
    await _persister(registry, repo, journal, FakeAudit(), pager).persist(interp, key=KEY)
    [(severity, text)] = pager.pages
    assert severity == "P1" and sid in text and "1 with another payload" in text
    assert "forged" not in text  # the send_id only, never a payload
    assert journal.rows(KEY)[0].record == _record("forged")  # never overwritten


async def test_the_same_value_in_another_spelling_is_another_payload_text(
    registry: Registry, journal: JournalSubject
) -> None:
    """The retry test compares the stored text, not the value: a planted `1.0` where the drain
    has `1` is equal as a value and still a persist fault."""
    record = _record("x") | {"payload": {"n": 1}}
    planted = record | {"payload": {"n": 1.0}}
    assert planted == record  # equal as values
    sid = stable_send_id(KEY, EPOCH, 1, 0, record)
    journal.plant(KEY, JournalEntry(sid, "inbox", 0, "PING", planted))
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": 1}))
    pager = FakePager()
    await _persister(registry, FakeRepo(), journal, FakeAudit(), pager).persist(interp, key=KEY)
    [(severity, text)] = pager.pages
    assert severity == "P1" and sid in text and "1 with another payload" in text


async def test_the_conflicts_of_one_persist_are_one_page_naming_at_most_20_send_ids(
    registry: Registry, journal: JournalSubject
) -> None:
    assert persistence.PAGE_SEND_IDS_MAX == 20
    interp = await _started(registry)
    sids = [_predicted(f"x{i}", ordinal=i) for i in range(25)]
    for i, sid in enumerate(sids):
        interp._enqueue_restored(Event("PING", {"n": f"x{i}"}))
        journal.plant(KEY, JournalEntry(sid, "inbox", i, "PING", _record(f"x{i}")), stamped=True)
    pager = FakePager()
    await _persister(registry, FakeRepo(), journal, FakeAudit(), pager).persist(interp, key=KEY)
    [(_, text)] = pager.pages
    assert "25 conflicting" in text and text.endswith("+5 more")
    assert [sid in text for sid in sids] == [True] * 20 + [False] * 5


async def test_a_persist_that_fails_after_its_append_spends_its_generation(
    registry: Registry, journal: JournalSubject
) -> None:
    """The generation is fixed before the append: a retry of a failed persist never reuses the
    failed attempt's ids, so its rows stay unsealed (and are paged at the next start)."""
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": "same"}))
    with pytest.raises(ConnectionError):
        await _persister(registry, FakeRepo(fail=True), journal, FakeAudit()).persist(
            interp, key=KEY
        )
    interp._enqueue_restored(Event("PING", {"n": "same"}))  # identical, at the same ordinal
    repo, pager = FakeRepo(), FakePager()
    await _persister(registry, repo, journal, FakeAudit(), pager).persist(interp, key=KEY)
    blob = repo.rows[KEY].snapshot
    assert (blob["cv_epoch"], blob["cv_generation"]) == (EPOCH, 2) and pager.pages == []
    assert {r.send_id for r in journal.rows(KEY)} == {_predicted("same"), _predicted("same", 2)}
    assert blob["cv_drained"] == [_predicted("same", 2)]


@pytest.mark.parametrize("epoch", ["E0" * 16, "e0" * 15, "e0" * 16 + "0", "g" * 32])
async def test_a_malformed_epoch_from_the_source_is_refused_before_the_drain(
    registry: Registry, journal: JournalSubject, epoch: str
) -> None:
    interp = await _started(registry)
    interp._enqueue_restored(Event("PING", {"n": "kept"}))
    try:
        with pytest.raises(ValueError, match="cv_epoch"):
            await _persister(registry, FakeRepo(), journal, FakeAudit(), epoch=epoch).persist(
                interp, key=KEY
            )
        assert journal.rows(KEY) == [] and len(interp.pending_events) == 1  # nothing drained
    finally:
        await interp.stop()


async def test_the_epoch_comes_from_the_os_csprng_unless_a_test_seeds_it(
    registry: Registry, journal: JournalSubject, monkeypatch: pytest.MonkeyPatch
) -> None:
    drawn = [persistence._os_epoch(), persistence._os_epoch()]
    assert all(_HEX32.fullmatch(e) for e in drawn) and drawn[0] != drawn[1]
    calls: list[int] = []

    def token_hex(nbytes: int) -> str:
        calls.append(nbytes)
        return "ab" * nbytes

    monkeypatch.setattr(secrets, "token_hex", token_hex)
    repo = FakeRepo()
    await _persister(registry, repo, journal, FakeAudit(), epoch=None).persist(
        await _started(registry), key=KEY
    )
    assert calls == [16] and repo.rows[KEY].snapshot["cv_epoch"] == "ab" * 16


class _Descent:
    def __init__(self, done: bool) -> None:
        self.done = done

    def is_set(self) -> bool:
        return self.done


@pytest.mark.parametrize(
    ("running", "descent", "restored", "in_step", "settled"),
    [
        (True, None, True, False, True),
        (True, None, False, False, False),
        (True, None, True, True, False),
        (False, None, True, False, False),
        (True, _Descent(True), False, False, True),
        (True, _Descent(False), False, False, False),
        (True, _Descent(True), False, True, False),
    ],
    ids=[
        "restored: no descent to wait for", "built: no descent means not started",
        "restored, mid-step", "restored, not running", "built, descent done",
        "built, descent running", "built, mid-step",
    ],
)  # fmt: skip
def test_settled_means_running_no_step_open_and_a_finished_descent_or_a_restore(
    running: bool, descent: object, restored: bool, in_step: bool, settled: bool
) -> None:
    """F2 (E50-T10/T49): the library's resume path never creates `_descent_done`, so a restored
    interpreter is settled once running with no step in flight; a built one must show its
    descent."""
    interp = SimpleNamespace(
        is_running=running,
        _descent_done=descent,
        restored_from_snapshot=restored,
        _step_in_flight=lambda: in_step,
    )
    assert persistence._is_settled(cast(Any, interp)) is settled


@pytest.mark.parametrize(
    ("in_step", "waiting", "quiescent"),
    [(False, 0, True), (True, 0, False), (False, 1, False)],
    ids=["at rest", "mid-step", "an event not yet taken"],
)
def test_quiescent_means_settled_with_no_event_waiting_in_either_lane(
    in_step: bool, waiting: int, quiescent: bool
) -> None:
    """#4711: quiescent is settled (`_is_settled`) with no event accepted and not yet taken in
    either lane (`queue_depth`), what the OMS facade waits for before it judges an exit."""
    interp = SimpleNamespace(
        is_running=True,
        _descent_done=_Descent(True),
        restored_from_snapshot=False,
        _step_in_flight=lambda: in_step,
        queue_depth=waiting,
    )
    assert persistence.quiescent(cast(Any, interp)) is quiescent


async def test_quiescent_on_the_pinned_runtime_at_rest_only(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#4711 on the runtime itself, built through the factory: quiescent at rest, and not with an
    event accepted and not yet taken, nor with a step open, nor once stopped. A move of the pin
    re-runs this and `tests/unit/oms/test_exit_settled_state.py`."""
    began, go = asyncio.Event(), asyncio.Event()

    async def held(_interp: Any, _context: dict[str, Any], _event: Any, _action: Any) -> None:
        began.set()
        await go.wait()  # the step stays open until `go`

    monkeypatch.setitem(binding_persist.ACTIONS, "record", held)
    built = await build(_KIND, clock=default_clock(), lane="platform", registry=registry)
    interp = built.interpreter
    seen = [persistence.quiescent(interp)]
    taken = interp.send("PING", wait=True)  # its receipt answers once the step has run
    seen.append(persistence.quiescent(interp))
    await asyncio.wait_for(began.wait(), 5)  # a bound on the test, never a time
    seen.append(persistence.quiescent(interp))
    go.set()
    await asyncio.wait_for(taken, 5)
    seen.append(persistence.quiescent(interp))
    await interp.stop()
    seen.append(persistence.quiescent(interp))
    assert seen == [True, False, False, True, False]


# --- E50-T63 (#3898 carry): every persist() exception is a P1 page, best effort ---------------


class _Ops:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def __call__(self, operation: str, outcome: str) -> None:
        self.seen.append((operation, outcome))


async def test_a_persist_that_raises_pages_p1_once_and_raises_the_same_error(
    registry: Registry, journal: JournalSubject
) -> None:
    """MUST-01: never retried silently. The page names the error type only, never its text."""
    interp = await _started(registry)
    pager, ops = FakePager(), _Ops()
    persister = _persister(registry, FakeRepo(fail=True), journal, FakeAudit(), pager)
    persister.ops = ops
    with pytest.raises(ConnectionError, match="simulated"):
        await persister.persist(interp, key=KEY)
    [(severity, text)] = pager.pages
    assert severity == "P1" and "ConnectionError" in text and "simulated" not in text
    assert ops.seen == [("persist", "error")]
    await interp.stop()


async def test_an_unsettled_persist_is_paged_too(
    registry: Registry, journal: JournalSubject
) -> None:
    interp = await _started(registry)
    await interp.stop()
    pager = FakePager()
    with pytest.raises(AssertionError, match="CV-C40"):
        await _persister(registry, FakeRepo(), journal, FakeAudit(), pager).persist(interp, key=KEY)
    assert [s for s, _ in pager.pages] == ["P1"]


async def test_a_refused_persist_is_paged_by_its_fault_writer_never_twice(
    registry: Registry, journal: JournalSubject
) -> None:
    interp = await _started(registry)
    interp.context["_fault"] = {"kind": "ActionError"}
    pager, ops = FakePager(), _Ops()
    persister = _persister(registry, FakeRepo(), journal, FakeAudit(), pager)
    persister.ops = ops
    try:
        with pytest.raises(PersistRefusedError):
            await persister.persist(interp, key=KEY)
        assert pager.pages == [] and ops.seen == [("persist", "refused")]
    finally:
        await interp.stop()


async def test_a_clean_persist_is_counted_ok(registry: Registry, journal: JournalSubject) -> None:
    interp = await _started(registry)
    pager, ops = FakePager(), _Ops()
    persister = _persister(registry, FakeRepo(), journal, FakeAudit(), pager)
    persister.ops = ops
    await persister.persist(interp, key=KEY)
    assert ops.seen == [("persist", "ok")] and pager.pages == []


async def test_a_raising_pager_never_masks_the_persist_failure(
    registry: Registry, journal: JournalSubject
) -> None:
    class _Down(FakePager):
        async def page(self, key: MachineKey, severity: str, message: str) -> None:
            await super().page(key, severity, message)
            raise OSError("pager transport down")

    interp = await _started(registry)
    pager = _Down()
    with capture_logs() as logs, pytest.raises(ConnectionError):
        await _persister(registry, FakeRepo(fail=True), journal, FakeAudit(), pager).persist(
            interp, key=KEY
        )
    failed = [e for e in logs if e["event"] == "statechart_page_failed"]
    assert [(e["reason"], e["error"]) for e in failed] == [("persist failed", "OSError")]
    assert "transport" not in repr(logs)
    await interp.stop()


async def test_a_hanging_pager_on_a_failed_persist_is_cut_by_its_deadline(
    registry: Registry, journal: JournalSubject, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(persistence, "PAGE_TIMEOUT_S", 0.0)

    class _Hangs(FakePager):
        async def page(self, key: MachineKey, severity: str, message: str) -> None:
            await super().page(key, severity, message)
            await asyncio.Event().wait()

    interp = await _started(registry)
    with capture_logs() as logs, pytest.raises(ConnectionError):
        await _persister(registry, FakeRepo(fail=True), journal, FakeAudit(), _Hangs()).persist(
            interp, key=KEY
        )
    assert [e["error"] for e in logs if e["event"] == "statechart_page_failed"] == ["TimeoutError"]
    await interp.stop()
