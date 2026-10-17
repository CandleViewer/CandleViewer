"""candleviewer.statechart.persistence — quiescent persist + drain journal (E50-T10).

Owns the shutdown path of every catalogue machine
(29-statechart-adoption-plan.md §1.3, CV-C23/C40/C41/C49'/C58/C65'):

    assert started + settled          (CV-C40, CV-C49'/C58)
    refuse + audit if context._fault  (MUST-01)
    drain_pending()  -> journal       (CV-C65', both lanes, priority first)
    get_persisted_snapshot()          (root only, CV-C41)
    seal(...)                         (HMAC envelope — E50-T49, injected)
    repo.write_snapshot(...)
    stop()

`drain_pending()` is called only here (CV-LINT-DRAIN).

Restore (E50-T49, 29 §1.3) is `Restorer.restore`: `open_sealed` (HMAC-SHA256
over chart bytes + blob + machine key, CV-C53) -> `from_snapshot(minimum_version=3,
expected_machine_hash=, plugins=)` (CV-C52, MUST-12, R13-W1) -> pre-start
asserts (C45'', C60, C27', C54) -> `_cv_bring_up` -> bounded `start()` ->
`journal.replay_once` -> `chain_trips` latch (C63). Any refusal writes a
quarantine row and fires a P1 alert; a tampered blob is never loaded.
`from_snapshot(` appears only in this module (CV-LINT-RESTORE).

Storage and audit are injected Protocols: `statechart` may not import
`audit` or `storage` directly (import-linter, forbidden-M18), and the
Postgres tables (`machine_snapshots`, `machine_drain_journal`,
24-internal-schemas.md §17.6) land with migration E29-T12. An in-memory
journal ships here for tests and for the contract suite.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

from xstate_statemachine import Interpreter, PluginBase, XStateMachineError
from xstate_statemachine.clock import Clock
from xstate_statemachine.events import persist_event, restore_event

from candleviewer.statechart import factory
from candleviewer.statechart.config import CV_START_TIMEOUT, SNAPSHOT_V, Lane
from candleviewer.statechart.registry import Registry
from candleviewer.statechart.schema import canonical_json

JournalLane = Literal["priority", "inbox"]


class PersistRefusedError(RuntimeError):
    """Raised when `persist()` refuses to write a snapshot (MUST-01)."""


@dataclass(frozen=True, slots=True)
class MachineKey:
    """Primary key of `machine_snapshots` / `machine_drain_journal`."""

    machine_kind: str
    entity_id: str
    env: str


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One drained event — mirrors a `machine_drain_journal` row."""

    send_id: str
    lane: JournalLane
    ordinal: int
    event_type: str
    record: dict[str, Any]
    receipt_error: str | None = None


@dataclass(frozen=True, slots=True)
class SealedSnapshot:
    """What `repo.write_snapshot` receives (the envelope E50-T49 seals)."""

    key: MachineKey
    version: int
    machine_hash: str
    snapshot: dict[str, Any]
    seal: Any


class SnapshotRepo(Protocol):
    async def write_snapshot(self, key: MachineKey, envelope: SealedSnapshot) -> None: ...


class PersistAudit(Protocol):
    async def drain_error(self, key: MachineKey, error: str) -> None: ...

    async def persist_refused(self, key: MachineKey, reason: str) -> None: ...


class DrainJournal(Protocol):
    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> None: ...

    async def replay_once(self, key: MachineKey, interp: Interpreter[Any]) -> int: ...


#: Seal callback: `(snapshot, machine_hash, version, key) -> seal` (E50-T49).
Sealer = Callable[[dict[str, Any], str, int, MachineKey], Awaitable[Any]]


def stable_send_id(key: MachineKey, ordinal: int, record: dict[str, Any]) -> str:
    """Deterministic de-dup key for a drained event (R11-W-1, R14-02).

    Same machine key + drain position + persisted record => same id, so a
    re-submitted journal append after a crash is idempotent.
    """
    canon = json.dumps(
        [key.machine_kind, key.entity_id, key.env, ordinal, record],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]


def _is_settled(interp: Interpreter[Any]) -> bool:
    """CV-C40 / CV-C49': started, initial descent done, no macrostep open.

    Reads engine internals (`_descent_done`, `_step_in_flight`) because the
    pinned 0.9.1 exposes no public "settled after start" flag; this module
    is the one place allowed to couple to the runtime (CV-LINT-IMPORT).
    """
    descent = getattr(interp, "_descent_done", None)
    return (
        bool(interp.is_running)
        and descent is not None
        and bool(descent.is_set())
        and not interp._step_in_flight()
    )


class InMemoryDrainJournal:
    """Reference `DrainJournal` (tests, contract suite, dev).

    Semantics match `machine_drain_journal`: PK includes `send_id` (append is
    idempotent), rows are replayed in `ordinal` order (priority first) and
    stamped `replayed` so a second `replay_once` is a no-op (CV-C65').
    """

    def __init__(self) -> None:
        self._rows: dict[MachineKey, dict[str, JournalEntry]] = {}
        self._replayed: set[tuple[MachineKey, str]] = set()

    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> None:
        rows = self._rows.setdefault(key, {})
        for entry in entries:
            rows.setdefault(entry.send_id, entry)

    def rows(self, key: MachineKey) -> list[JournalEntry]:
        return sorted(self._rows.get(key, {}).values(), key=lambda e: e.ordinal)

    async def replay_once(self, key: MachineKey, interp: Interpreter[Any]) -> int:
        count = 0
        for entry in self.rows(key):
            marker = (key, entry.send_id)
            if marker in self._replayed:
                continue
            self._replayed.add(marker)
            ev = restore_event(entry.record)
            # Restore hook, not `send()`: keeps lane + engine provenance of
            # fired timers / completions (library #214), priority ahead of inbox.
            interp._enqueue_restored(ev, priority=entry.lane == "priority")
            count += 1
        return count


@dataclass(slots=True)
class Persister:
    """Wires `persist()` to its injected collaborators."""

    repo: SnapshotRepo
    journal: DrainJournal
    audit: PersistAudit
    seal: Sealer
    machine_hash_of: Callable[[str], str]
    version: int = field(default=SNAPSHOT_V)

    async def persist(self, interp: Interpreter[Any], *, key: MachineKey) -> None:
        """Quiescent persist (29 §1.3). See module docstring for the order."""
        if not _is_settled(interp):
            raise AssertionError(
                f"persist({key.machine_kind}/{key.entity_id}): interpreter is not "
                "started and settled (CV-C40, CV-C49'/C58); never persist an "
                "un-started or mid-step interpreter"
            )
        context = interp.context
        if isinstance(context, dict) and context.get("_fault") is not None:
            reason = "context carries _fault (MUST-01)"
            await self.audit.persist_refused(key, reason)
            raise PersistRefusedError(f"persist({key.machine_kind}/{key.entity_id}): {reason}")

        n_priority = len(interp._priority_queue)
        receipts = interp._receipts
        pending = list(interp.pending_events)
        waited = {id(ev) for ev in pending if id(ev) in receipts}
        drained = await interp.drain_pending()  # CV-LINT-DRAIN: only call site

        entries: list[JournalEntry] = []
        for ordinal, ev in enumerate(drained):
            lane: JournalLane = "priority" if ordinal < n_priority else "inbox"
            record = persist_event(ev, lane="priority" if lane == "priority" else None)
            receipt_error = "InterpreterStoppedError" if id(ev) in waited else None
            if receipt_error is not None:
                await self.audit.drain_error(key, receipt_error)  # R14-02
            entries.append(
                JournalEntry(
                    send_id=stable_send_id(key, ordinal, record),
                    lane=lane,
                    ordinal=ordinal,
                    event_type=str(ev.type),
                    record=record,
                    receipt_error=receipt_error,
                )
            )
        await self.journal.append(key, entries)

        blob = interp.get_persisted_snapshot()  # root only (CV-C41)
        machine_hash = self.machine_hash_of(key.machine_kind)
        seal = await self.seal(blob, machine_hash, self.version, key)
        await self.repo.write_snapshot(
            key,
            SealedSnapshot(
                key=key,
                version=self.version,
                machine_hash=machine_hash,
                snapshot=blob,
                seal=seal,
            ),
        )
        await interp.stop()


# ---------------------------------------------------------------------------
# Restore + HMAC envelope (E50-T49, 29 §1.3, CV-C52/C53/C54/C60/C27'/C45''/C63)
# ---------------------------------------------------------------------------


class RestoreRefusedError(RuntimeError):
    """A sealed snapshot was refused; it is quarantined, never loaded."""

    def __init__(self, key: MachineKey, reason: str) -> None:
        super().__init__(f"restore({key.machine_kind}/{key.entity_id}): {reason}")
        self.key = key
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Seal:
    """HMAC-SHA256 tag over `_mac_input` plus the KMS key id."""

    key_id: str
    tag: str


class HmacKeys(Protocol):
    """KMS facade (ADR-0009): HMAC keys rotated by `key_id`. Key bytes never
    leave this callable's result and are never logged."""

    def current(self) -> str: ...

    def key(self, key_id: str) -> bytes: ...


class RestoreAudit(Protocol):
    async def quarantine(self, key: MachineKey, envelope: SealedSnapshot, reason: str) -> None: ...


class Pager(Protocol):
    async def page(self, key: MachineKey, severity: str, message: str) -> None: ...


#: Layout of the HMAC input (CV-C53). A label carrying it leads every tag as a domain-separation
#: part, so a tag sealed under another layout, or for another purpose, never verifies. It is not
#: `SNAPSHOT_V`: that is the library's snapshot floor (`from_snapshot(minimum_version=)`, CV-C52)
#: and must not move with this. 1 = chart, blob, machine_hash, version; 2 adds the label and the
#: machine key.
SEAL_LAYOUT_V: Final[int] = 2


def _mac_input(
    key: MachineKey,
    chart: dict[str, Any],
    snapshot: dict[str, Any],
    machine_hash: str,
    version: int,
) -> bytes:
    # Length-prefixed parts so no byte shift can move data between fields. The machine key
    # closes the list: a tag verifies only for the (kind, entity, env) it was sealed for (C-2.11).
    parts = [
        f"cv-snapshot-seal-v{SEAL_LAYOUT_V}".encode("ascii"),
        canonical_json(chart),
        canonical_json(snapshot),
        machine_hash.encode("utf-8"),
        str(version).encode("ascii"),
        key.machine_kind.encode("utf-8"),
        key.entity_id.encode("utf-8"),
        key.env.encode("utf-8"),
    ]
    return b"".join(len(p).to_bytes(8, "big") + p for p in parts)


def seal(
    keys: HmacKeys,
    chart: dict[str, Any],
    snapshot: dict[str, Any],
    machine_hash: str,
    version: int,
    *,
    key: MachineKey,
) -> Seal:
    """CV-C53: HMAC-SHA256 over the chart, blob and machine `key`, `key_id=KMS.current()`."""
    if version < SNAPSHOT_V:
        raise ValueError(f"seal version {version} < {SNAPSHOT_V} (CV-C53)")
    key_id = keys.current()
    tag = hmac.new(
        keys.key(key_id), _mac_input(key, chart, snapshot, machine_hash, version), hashlib.sha256
    )
    return Seal(key_id=key_id, tag=tag.hexdigest())


def open_sealed(
    keys: HmacKeys,
    chart: dict[str, Any],
    envelope: SealedSnapshot,
    *,
    key: MachineKey,
    expected_machine_hash: str,
) -> dict[str, Any]:
    """Verify an envelope for `key`; returns the blob or raises `ValueError(reason)`.

    `key` is the machine the caller means to open, taken from where it looked the envelope up.
    The envelope only has to agree with it: the tag is checked against `key`, never `envelope.key`.
    """
    if envelope.key != key:
        raise ValueError("envelope seal is bound to another machine key (CV-C53, C-2.11)")
    if envelope.version < SNAPSHOT_V:
        raise ValueError(f"envelope version {envelope.version} < {SNAPSHOT_V} (CV-C52)")
    if envelope.machine_hash != expected_machine_hash:
        raise ValueError("envelope machine_hash does not match registry (MUST-12)")
    s = envelope.seal
    if not isinstance(s, Seal):
        raise ValueError("envelope carries no HMAC seal (CV-C53)")
    try:
        secret = keys.key(s.key_id)
    except KeyError:
        raise ValueError("unknown HMAC key_id (CV-C53)") from None
    want = hmac.new(
        secret,
        _mac_input(key, chart, envelope.snapshot, envelope.machine_hash, envelope.version),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(want, s.tag):
        raise ValueError("bad HMAC (CV-C53)")
    return envelope.snapshot


class DegradedLatchError(RuntimeError):
    """An order-path command was refused: the machine is chain-trip latched
    (CV-C63) until an operator acknowledges it (E42)."""


class ChainTripLatch:
    """Degraded-admission latch for restored machines with `chain_trips > 0`.

    Reads stay served; `admit_command` refuses order-path commands. The
    gateway (E50-T15) consults this synchronously before any send (C-2.21).
    Acknowledgement UI is E42; `acknowledge` is its backend hook.
    """

    def __init__(self) -> None:
        self._latched: dict[MachineKey, str] = {}

    def latch(self, key: MachineKey, reason: str) -> None:
        self._latched[key] = reason

    def is_latched(self, key: MachineKey) -> bool:
        return key in self._latched

    def admit_command(self, key: MachineKey) -> None:
        reason = self._latched.get(key)
        if reason is not None:
            raise DegradedLatchError(
                f"{key.machine_kind}/{key.entity_id} is degraded (chain_trips latch, "
                f"CV-C63): {reason}; order-path commands refused until acknowledged"
            )

    def acknowledge(self, key: MachineKey) -> None:
        self._latched.pop(key, None)


@dataclass(frozen=True, slots=True)
class RestoreResult:
    interpreter: Interpreter[Any]
    machine_hash: str
    replayed: int
    degraded: bool


def reconcile_counts(blob: dict[str, Any], interp: Interpreter[Any]) -> None:
    """CV-C54: persisted vs admitted record counts must agree before start().

    A record refused at restore (e.g. an event a chart upgrade undeclared)
    must never vanish silently.
    """
    persisted = len(blob.get("pending_events") or [])
    admitted = len(interp.pending_events)
    if persisted != admitted:
        raise ValueError(f"pending_events persisted={persisted} admitted={admitted} (CV-C54)")
    p_def = len(blob.get("deferred") or [])
    a_def = len(interp._deferred_events)
    if p_def != a_def:
        raise ValueError(f"deferred persisted={p_def} admitted={a_def} (CV-C54)")
    p_sched = len(blob.get("scheduled_sends") or [])
    a_sched = len(interp._restored_self_sends)
    if p_sched != a_sched:
        raise ValueError(f"scheduled_sends persisted={p_sched} admitted={a_sched} (CV-C54)")


def _pre_start_checks(blob: dict[str, Any], interp: Interpreter[Any]) -> None:
    if interp.last_transition_ok is None or interp.last_error is not None:
        raise ValueError(
            f"restore recorded an error before start(): {interp.last_error!r} (CV-C45'', CV-C60)"
        )
    state_ids = set(blob.get("state_ids") or [])
    configuration = {n.id for n in interp._active_state_nodes}
    if not state_ids <= configuration:
        raise ValueError(
            f"state_ids {sorted(state_ids - configuration)} not in configuration (CV-C27')"
        )
    reconcile_counts(blob, interp)


#: Plugin factory: fresh instances per restore (CvErrorHooks, CvMetricsPlugin,
#: CvAuditPlugin — E50-T60). Passed via `from_snapshot(plugins=)` (R13-W1).
PluginsFactory = Callable[[], Sequence[PluginBase[Any]]]


@dataclass(slots=True)
class Restorer:
    """The only path from sealed bytes to a live machine (29 §1.3)."""

    registry: Registry
    keys: HmacKeys
    journal: DrainJournal
    audit: RestoreAudit
    pager: Pager
    latch: ChainTripLatch
    plugins: PluginsFactory
    clock: Clock
    lane: Lane

    async def _refuse(
        self, key: MachineKey, envelope: SealedSnapshot, reason: str
    ) -> RestoreRefusedError:
        await self.audit.quarantine(key, envelope, reason)
        await self.pager.page(key, "P1", f"snapshot refused: {reason}")
        return RestoreRefusedError(key, reason)

    async def restore(self, key: MachineKey, envelope: SealedSnapshot) -> RestoreResult:
        chart = self.registry.get(key.machine_kind)
        expected = self.registry.hash(key.machine_kind)
        try:
            blob = open_sealed(self.keys, chart, envelope, key=key, expected_machine_hash=expected)
        except ValueError as exc:
            raise await self._refuse(key, envelope, str(exc)) from None

        machine = factory.make_machine(key.machine_kind, chart)
        try:
            interp: Interpreter[Any] = Interpreter.from_snapshot(
                json.dumps(blob),
                machine,
                clock=self.clock,
                minimum_version=SNAPSHOT_V,
                expected_machine_hash=machine.structure_hash,
                plugins=list(self.plugins()),
            )
            factory.apply_lane_config(interp, self.lane)
            _pre_start_checks(blob, interp)
        except (XStateMachineError, ValueError) as exc:
            raise await self._refuse(key, envelope, f"{type(exc).__name__}: {exc}") from None

        factory._cv_bring_up(interp)
        try:
            await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)
        except TimeoutError as exc:
            raise TimeoutError(
                f"restore({key.machine_kind}) start() did not settle within "
                f"{CV_START_TIMEOUT}s (CV-C56)"
            ) from exc
        replayed = await self.journal.replay_once(key, interp)

        degraded = interp.chain_trips > 0  # CV-C63: read the count, not last_error
        if degraded:
            reason = f"chain_trips={interp.chain_trips}: {interp.last_chain_error}"
            self.latch.latch(key, reason)
            await self.pager.page(key, "P1", f"restored degraded ({reason})")
        return RestoreResult(
            interpreter=interp, machine_hash=expected, replayed=replayed, degraded=degraded
        )


def hmac_sealer(keys: HmacKeys, chart: dict[str, Any]) -> Sealer:
    """Adapt `seal()` to `Persister.seal` for one chart, sealing for the key `persist` is given."""

    async def _seal(
        snapshot: dict[str, Any], machine_hash: str, version: int, key: MachineKey
    ) -> Seal:
        return seal(keys, chart, snapshot, machine_hash, version, key=key)

    return _seal
