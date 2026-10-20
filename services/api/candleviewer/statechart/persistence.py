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

The drain is sealed (24 §17.6, `SEAL_LAYOUT_V = 3`, E50-T62): before any journal row is written,
the persist fixes its life's `cv_epoch` (minted on the first persist of an interpreter that was
not restored, from the OS CSPRNG), its `cv_generation` (the restored or last one plus 1) and
`cv_drained` (the sorted `send_id`s it journals, each hashed over that epoch and generation too);
the blob it seals carries all three. An append conflict is a retry only on an unreplayed row with
the same payload text; any other is a persist fault, one P1 page per persist.

Restore (E50-T49, 29 §1.3) is `Restorer.restore`: `open_sealed` (HMAC-SHA256
over chart bytes + blob + machine key, CV-C53) -> the three `cv_` keys checked and removed ->
`from_snapshot(minimum_version=3, expected_machine_hash=, plugins=)` (CV-C52, MUST-12, R13-W1)
-> pre-start asserts (C45'', C60, C27', C54) -> `_cv_bring_up` -> bounded `start()` ->
`journal.replay_once` (only the rows the seal names, verified; one P1 page for the rest; a
failure stops the machine) -> `chain_trips` latch (C63). Any refusal writes a
quarantine row and fires a P1 alert; a tampered blob is never loaded. A machine that starts
without a verified snapshot calls `Restorer.page_unclaimed` instead: no sealed set can claim its
key's unreplayed rows. `from_snapshot(` appears only in this module (CV-LINT-RESTORE).

Storage and audit are injected Protocols: `statechart` may not import
`audit` or `storage` directly (import-linter, forbidden-M18). The Postgres
tables (`machine_snapshots`, `machine_drain_journal`, 24-internal-schemas.md
§17.6) are created by E50-T61; their row stores (E50-T62) are mapped onto
these Protocols by `candleviewer.statechart_wiring`, and `RowStoreDrainJournal`
replays the Postgres journal here, where the library may be imported. An
in-memory journal ships here for tests and for the contract suite.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import weakref
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

import structlog
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


@dataclass(frozen=True, slots=True)
class JournalConflict:
    """An appended entry whose `send_id` already had a row: is that row stamped, and is its
    stored `payload` text the entry's (24 §17.6)?"""

    send_id: str
    stamped: bool
    same_payload: bool

    @property
    def is_retry(self) -> bool:
        """The retry of one drain: the only conflict that is a no-op; any other is a fault."""
        return not self.stamped and self.same_payload


@dataclass(frozen=True, slots=True)
class DrainSeal:
    """What a layout-3 blob seals about its persist (24 §17.6): the life's `cv_epoch`, the
    persist's `cv_generation`, and `cv_drained`, the sorted `send_id`s it journaled."""

    epoch: str
    generation: int
    drained: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """One verified replay: how many rows were re-enqueued, the unreplayed rows skipped (their
    `send_id` and why), and the sealed `send_id`s with no row of the key."""

    replayed: int
    skipped: tuple[tuple[str, str], ...] = ()
    missing: tuple[str, ...] = ()


class DrainJournal(Protocol):
    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> Sequence[JournalConflict]: ...

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]: ...

    async def replay_once(
        self, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
    ) -> ReplayReport: ...


#: Seal callback: `(snapshot, machine_hash, version, key) -> seal` (E50-T49).
Sealer = Callable[[dict[str, Any], str, int, MachineKey], Awaitable[Any]]

_HEX32: Final = re.compile(r"[0-9a-f]{32}")
#: The most `send_id`s one page names; the rest are counted (`+N more`). One page per restore of
#: a key, per persist and per start without a snapshot, never one per row.
PAGE_SEND_IDS_MAX: Final = 20


def stable_send_id(
    key: MachineKey, epoch: str, generation: int, ordinal: int, record: dict[str, Any]
) -> str:
    """The drain journal's de-dup key (24 §17.6, R11-W-1, R14-02): the first 32 hex of sha256
    over `canonical_json([machine_kind, entity_id, env, cv_epoch, cv_generation, ordinal,
    record])`, which refuses a value JSON cannot hold, NaN and infinities included.

    The same persist re-appending the same record gets the same id, so a retried append is a
    no-op; a later persist (the generation) or another life (the epoch) never shares one.
    """
    inputs = [key.machine_kind, key.entity_id, key.env, epoch, generation, ordinal, record]
    return hashlib.sha256(canonical_json(inputs)).hexdigest()[:32]


def _send_ids_text(send_ids: Sequence[str]) -> str:
    shown = ", ".join(send_ids[:PAGE_SEND_IDS_MAX])
    more = len(send_ids) - PAGE_SEND_IDS_MAX
    return f"{shown} +{more} more" if more > 0 else shown


def _os_epoch() -> str:
    """A new life's `cv_epoch`: 128 bits from the OS CSPRNG, as 32 lowercase hex characters."""
    return secrets.token_hex(16)


@dataclass(frozen=True, slots=True)
class _Life:
    """A machine's life (24 §17.6): its epoch and the last generation it fixed: the restored one,
    or one a persist spent once it had drained, whether or not that persist then succeeded."""

    epoch: str
    generation: int


#: Each live interpreter's life: set by `Restorer.restore` from the verified blob, or minted by
#: the first persist of an interpreter that was not restored (a fresh build, a build after a
#: refused restore, a reset). Weak, so an interpreter's entry goes with it.
_LIVES: Final[weakref.WeakKeyDictionary[Interpreter[Any], _Life]] = weakref.WeakKeyDictionary()


def _is_settled(interp: Interpreter[Any]) -> bool:
    """CV-C40 / CV-C49': started, initial descent done, no macrostep open.

    Reads engine internals (`_descent_done`, `_step_in_flight`) because the
    pinned 0.9.1 exposes no public "settled after start" flag; this module
    is the one place allowed to couple to the runtime (CV-LINT-IMPORT).
    A restored interpreter has no initial descent: the library's resume path
    attaches the run loop without creating `_descent_done`, so running is its
    proof of start (F2; before E50-T62 no restored machine could persist again).
    """
    if not interp.is_running or interp._step_in_flight():
        return False
    descent = getattr(interp, "_descent_done", None)
    if descent is None:
        return bool(interp.restored_from_snapshot)
    return bool(descent.is_set())


def _record_lane(record: dict[str, Any]) -> JournalLane:
    """The lane a record names, as the library's own restore reads it (CV-C42)."""
    return "priority" if record.get("lane") == "priority" else "inbox"


def _refusal(
    key: MachineKey, drain: DrainSeal, sealed: frozenset[str], row: JournalEntry
) -> str | None:
    """Why an unreplayed row may not be replayed under the verified `drain`; `None` if it may."""
    if row.send_id not in sealed:
        return "not in the sealed drained set"
    if not isinstance(row.record, dict):
        return "record is not an object"
    try:
        recomputed = stable_send_id(key, drain.epoch, drain.generation, row.ordinal, row.record)
    except (TypeError, ValueError):  # e.g. `1e400` read back as Infinity: no JSON for it
        recomputed = ""
    if recomputed != row.send_id:
        return "send_id does not recompute"
    if (row.lane == "priority") != (row.record.get("lane") == "priority"):
        return "lane column disagrees with the record"
    if row.event_type != row.record.get("type"):
        return "event_type column disagrees with the record"
    return None


class JournalRowStore(Protocol):
    """One machine's `machine_drain_journal` rows (E50-T62): the composition root's
    `JournalRowsAdapter` over Postgres, or `InMemoryDrainJournal`. Replay needs the library, so
    it stays here, in `replay_sealed`."""

    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> Sequence[JournalConflict]: ...

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]: ...

    async def present(self, key: MachineKey, send_ids: Sequence[str]) -> frozenset[str]: ...

    async def mark_replayed(self, key: MachineKey, send_ids: Sequence[str]) -> None: ...


async def replay_sealed(
    rows: JournalRowStore, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
) -> ReplayReport:
    """Replay exactly the rows the verified blob seals (24 §17.6, CV-C65').

    An unreplayed row is re-enqueued only when its `send_id` is in `cv_drained`, recomputes from
    the row with the blob's epoch and generation, and its `lane` and `event_type` columns agree
    with its record; its lane is the record's, never the column's (CV-C42). Accepted rows go in
    `ordinal` order through the restore hook (lane and engine provenance kept, library #214), and
    only then are they stamped, in one call: a crash between the two re-delivers them, and an
    order retry reuses its client order id (C-2.10), where stamping first could lose an event.
    Every other unreplayed row is skipped (neither enqueued nor stamped) and reported, as is each
    sealed `send_id` that has no row of the key; the caller pages them.
    """
    sealed = frozenset(drain.drained)
    unreplayed = sorted(await rows.list_unreplayed(key), key=lambda e: (e.ordinal, e.send_id))
    accepted: list[JournalEntry] = []
    skipped: list[tuple[str, str]] = []
    for row in unreplayed:
        why = _refusal(key, drain, sealed, row)
        if why is None:
            accepted.append(row)
        else:
            skipped.append((row.send_id, why))
    listed = {row.send_id for row in unreplayed}
    unseen = [send_id for send_id in drain.drained if send_id not in listed]
    present = await rows.present(key, unseen) if unseen else frozenset[str]()
    missing = tuple(send_id for send_id in unseen if send_id not in present)
    for row in accepted:
        ev = restore_event(row.record)
        interp._enqueue_restored(ev, priority=_record_lane(row.record) == "priority")
    if accepted:
        await rows.mark_replayed(key, [row.send_id for row in accepted])
    return ReplayReport(len(accepted), tuple(skipped), missing)


class InMemoryDrainJournal:
    """Reference `DrainJournal` (tests, contract suite, dev).

    Semantics match `machine_drain_journal`: PK includes `send_id` (an append reports each id
    that already has a row: stamped or not, and whether its payload is the entry's, as canonical
    JSON), rows are replayed in `ordinal` order (priority first) through `replay_sealed`, and
    stamped `replayed`, so a second `replay_once` is a no-op (CV-C65').
    """

    def __init__(self) -> None:
        self._rows: dict[MachineKey, dict[str, JournalEntry]] = {}
        self._replayed: set[tuple[MachineKey, str]] = set()

    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> list[JournalConflict]:
        rows, conflicts = self._rows.setdefault(key, {}), []
        for entry in entries:
            held = rows.get(entry.send_id)
            if held is None:
                rows[entry.send_id] = entry
                continue
            stamped = (key, entry.send_id) in self._replayed
            same = canonical_json(held.record) == canonical_json(entry.record)
            conflicts.append(JournalConflict(entry.send_id, stamped, same))
        return conflicts

    def rows(self, key: MachineKey) -> list[JournalEntry]:
        return sorted(self._rows.get(key, {}).values(), key=lambda e: e.ordinal)

    async def list_unreplayed(self, key: MachineKey) -> list[JournalEntry]:
        return [e for e in self.rows(key) if (key, e.send_id) not in self._replayed]

    async def present(self, key: MachineKey, send_ids: Sequence[str]) -> frozenset[str]:
        held = self._rows.get(key, {})
        return frozenset(send_id for send_id in send_ids if send_id in held)

    async def mark_replayed(self, key: MachineKey, send_ids: Sequence[str]) -> None:
        self._replayed.update((key, send_id) for send_id in send_ids)

    async def replay_once(
        self, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
    ) -> ReplayReport:
        return await replay_sealed(self, key, interp, drain)


@dataclass(slots=True)
class RowStoreDrainJournal:
    """`DrainJournal` over a `JournalRowStore` (E50-T62): the Postgres journal, replayed by
    `replay_sealed`, as the reference is."""

    rows: JournalRowStore

    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> Sequence[JournalConflict]:
        return await self.rows.append(key, entries)

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        return await self.rows.list_unreplayed(key)

    async def replay_once(
        self, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
    ) -> ReplayReport:
        return await replay_sealed(self.rows, key, interp, drain)


@dataclass(slots=True)
class Persister:
    """Wires `persist()` to its injected collaborators.

    `epoch_source` is a test-only seam: production keeps `_os_epoch`, the OS CSPRNG, so a life's
    ids cannot be predicted before its first snapshot is readable (24 §17.6).
    """

    repo: SnapshotRepo
    journal: DrainJournal
    audit: PersistAudit
    seal: Sealer
    machine_hash_of: Callable[[str], str]
    pager: Pager
    version: int = field(default=SNAPSHOT_V)
    epoch_source: Callable[[], str] = field(default=_os_epoch)

    def _life(self, interp: Interpreter[Any]) -> _Life:
        """The interpreter's life; for one that was not restored, a new life with a new epoch,
        which the persist keeps once it has drained (nothing is journaled before that)."""
        life = _LIVES.get(interp)
        if life is None:
            epoch = self.epoch_source()
            if not isinstance(epoch, str) or _HEX32.fullmatch(epoch) is None:
                raise ValueError("cv_epoch must be 32 lowercase hex characters (24 §17.6)")
            life = _Life(epoch, 0)
        return life

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
        life = self._life(interp)

        n_priority = len(interp._priority_queue)
        receipts = interp._receipts
        pending = list(interp.pending_events)
        waited = {id(ev) for ev in pending if id(ev) in receipts}
        drained = await interp.drain_pending()  # CV-LINT-DRAIN: only call site
        # Fixed before any journal row is written, and spent even if this persist fails later:
        # a retry gets new ids, so the failed attempt's rows stay out of every sealed set.
        generation = life.generation + 1
        _LIVES[interp] = _Life(life.epoch, generation)

        entries: list[JournalEntry] = []
        for ordinal, ev in enumerate(drained):
            lane: JournalLane = "priority" if ordinal < n_priority else "inbox"
            record = persist_event(ev, lane="priority" if lane == "priority" else None)
            receipt_error = "InterpreterStoppedError" if id(ev) in waited else None
            if receipt_error is not None:
                await self.audit.drain_error(key, receipt_error)  # R14-02
            entries.append(
                JournalEntry(
                    send_id=stable_send_id(key, life.epoch, generation, ordinal, record),
                    lane=lane,
                    ordinal=ordinal,
                    event_type=str(ev.type),
                    record=record,
                    receipt_error=receipt_error,
                )
            )
        sealed_keys = {
            "cv_epoch": life.epoch,
            "cv_generation": generation,
            "cv_drained": sorted({entry.send_id for entry in entries}),
        }
        conflicts = await self.journal.append(key, entries)
        faults = [c for c in conflicts if not c.is_retry]
        if faults:  # MUST-01: never a silent no-op; the send_ids only, never a payload
            stamped = sum(c.stamped for c in faults)
            await self.pager.page(
                key,
                "P1",
                f"drain journal append: {len(faults)} conflicting row(s), a persist fault "
                f"(MUST-01): {stamped} stamped already, {len(faults) - stamped} with another "
                f"payload; send_ids {_send_ids_text([c.send_id for c in faults])}",
            )

        blob = {**interp.get_persisted_snapshot(), **sealed_keys}  # root only (CV-C41)
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
#: machine key; 3 (E50-T62) keeps those parts, through `canonical_json`, which refuses NaN and
#: infinities from E50-T62, and seals a blob that carries `cv_epoch`, `cv_generation` and
#: `cv_drained` (24 §17.6). No upcaster: an envelope of an earlier layout fails the MAC and is
#: quarantined.
SEAL_LAYOUT_V: Final[int] = 3


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
#: CvAuditPlugin — E50-T60), for the machine being restored: `cv_plugins` needs its
#: identity (E50-T62). Passed via `from_snapshot(plugins=)` (R13-W1).
PluginsFactory = Callable[[MachineKey], Sequence[PluginBase[Any]]]


_CV_KEYS: Final = ("cv_epoch", "cv_generation", "cv_drained")


def split_sealed_drain(blob: dict[str, Any]) -> tuple[DrainSeal, dict[str, Any]]:
    """A verified layout-3 blob's `DrainSeal`, and the blob without its three `cv_` keys, which
    `from_snapshot` never sees. `ValueError` names a missing or malformed key (24 §17.6)."""
    epoch, generation, drained = (blob.get(name) for name in _CV_KEYS)
    if not isinstance(epoch, str) or _HEX32.fullmatch(epoch) is None:
        raise ValueError("sealed cv_epoch is missing or not 32 lowercase hex (SEAL_LAYOUT_V 3)")
    if type(generation) is not int or generation < 1:
        raise ValueError("sealed cv_generation is missing or not an int of at least 1")
    if (
        not isinstance(drained, list)
        or not all(isinstance(s, str) and _HEX32.fullmatch(s) for s in drained)
        or drained != sorted(set(drained))
    ):
        raise ValueError(
            "sealed cv_drained is missing or not a sorted, duplicate-free send_id list"
        )
    rest = {name: value for name, value in blob.items() if name not in _CV_KEYS}
    return DrainSeal(epoch, generation, tuple(drained)), rest


def _skipped_page(report: ReplayReport) -> str:
    """One page for a restore of one key: the counts, why, and at most 20 `send_id`s, the missing
    sealed ones first: each may be a lost event, so a flood of skipped rows never crowds them
    out of the bounded list (CR-E50T62R2-05)."""
    why = Counter(reason for _, reason in report.skipped)
    tally = "; ".join(f"{n} {reason}" for reason, n in sorted(why.items()))
    send_ids = [*report.missing, *(send_id for send_id, _ in report.skipped)]
    return (
        f"drain journal: {len(report.missing)} sealed row(s) missing, "
        f"{len(report.skipped)} unreplayed row(s) skipped"
        + (f" ({tally})" if tally else "")
        + f"; nothing of them replayed or stamped; send_ids {_send_ids_text(send_ids)}"
    )


def _logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.statechart.persistence")


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

    async def _page(self, key: MachineKey, reason: str, message: str) -> None:
        """A best-effort P1 page (CR-E50T62R2-02): a pager that raises never escapes `restore()`,
        never masks the failure being paged and never orphans a started machine. It is logged
        CRITICAL with the key, the page's fixed `reason` and the pager error's type, never the
        pager's text or the message (which a refusal fills from library text). Cancellation
        passes through."""
        try:
            await self.pager.page(key, "P1", message)
        except Exception as exc:
            _logger().critical(
                "statechart_page_failed",
                machine_kind=key.machine_kind,
                entity_id=key.entity_id,
                env=key.env,
                reason=reason,
                error=type(exc).__name__,
            )

    async def _stop(self, key: MachineKey, interp: Interpreter[Any]) -> None:
        """Stop a machine this restore started; a `stop()` that raises is logged CRITICAL by its
        type only and never replaces the failure that led here."""
        try:
            await interp.stop()
        except Exception as exc:
            _logger().critical(
                "statechart_restore_stop_failed",
                machine_kind=key.machine_kind,
                entity_id=key.entity_id,
                env=key.env,
                error=type(exc).__name__,
            )

    async def _refuse(
        self, key: MachineKey, envelope: SealedSnapshot, reason: str
    ) -> RestoreRefusedError:
        await self.audit.quarantine(key, envelope, reason)
        await self._page(key, "snapshot refused", f"snapshot refused: {reason}")
        return RestoreRefusedError(key, reason)

    async def _replay(
        self, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
    ) -> ReplayReport:
        """The verified replay of a started machine. A replay that fails stops the machine, which
        would otherwise run with no owner, and leaves its rows unstamped for the next restore
        (F7, SR-E50T62-03): an error pages P1 by its type only and is raised again without its
        chain; a cancellation stops the machine and passes through. A `stop()` or a page that
        raises on the way is logged and never replaces the original failure (CR-E50T62R2-02)."""
        try:
            return await self.journal.replay_once(key, interp, drain)
        except asyncio.CancelledError:
            await self._stop(key, interp)
            raise
        except Exception as exc:
            failure = exc
        await self._stop(key, interp)
        await self._page(
            key,
            "drain journal replay failed",
            f"drain journal replay failed ({type(failure).__name__}): the restored machine is "
            "stopped and its rows stay unreplayed for the next restore",
        )
        raise failure from None

    async def page_unclaimed(self, key: MachineKey) -> int:
        """The start of a machine without a verified snapshot (fresh, after a refused restore,
        after a reset): no sealed set can claim its key's unreplayed rows, such as those of a
        crash between the first append and the first snapshot, so each is skipped, left
        unstamped, and named in one P1 page (24 §17.6). Returns how many."""
        rows = sorted(await self.journal.list_unreplayed(key), key=lambda e: (e.ordinal, e.send_id))
        # replay_sealed's skip-and-page branch under an empty sealed set: nothing is replayed.
        unclaimed = ReplayReport(
            0, tuple((r.send_id, "no verified snapshot claims it") for r in rows)
        )
        if unclaimed.skipped:
            await self._page(key, "drain journal rows unclaimed", _skipped_page(unclaimed))
        return len(rows)

    async def restore(self, key: MachineKey, envelope: SealedSnapshot) -> RestoreResult:
        chart = self.registry.get(key.machine_kind)
        expected = self.registry.hash(key.machine_kind)
        try:
            sealed = open_sealed(
                self.keys, chart, envelope, key=key, expected_machine_hash=expected
            )
            drain, blob = split_sealed_drain(sealed)
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
                plugins=list(self.plugins(key)),
            )
            factory.apply_lane_config(interp, self.lane)
            _pre_start_checks(blob, interp)
        except (XStateMachineError, ValueError) as exc:
            raise await self._refuse(key, envelope, f"{type(exc).__name__}: {exc}") from None
        _LIVES[interp] = _Life(drain.epoch, drain.generation)  # its next persist is the +1

        factory._cv_bring_up(interp)
        try:
            await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)
        except TimeoutError as exc:
            raise TimeoutError(
                f"restore({key.machine_kind}) start() did not settle within "
                f"{CV_START_TIMEOUT}s (CV-C56)"
            ) from exc
        report = await self._replay(key, interp, drain)
        if report.skipped or report.missing:
            await self._page(key, "drain journal rows skipped or missing", _skipped_page(report))

        degraded = interp.chain_trips > 0  # CV-C63: read the count, not last_error
        if degraded:
            reason = f"chain_trips={interp.chain_trips}: {interp.last_chain_error}"
            self.latch.latch(key, reason)
            await self._page(key, "restored degraded", f"restored degraded ({reason})")
        return RestoreResult(
            interpreter=interp, machine_hash=expected, replayed=report.replayed, degraded=degraded
        )


def hmac_sealer(keys: HmacKeys, chart: dict[str, Any]) -> Sealer:
    """Adapt `seal()` to `Persister.seal` for one chart, sealing for the key `persist` is given."""

    async def _seal(
        snapshot: dict[str, Any], machine_hash: str, version: int, key: MachineKey
    ) -> Seal:
        return seal(keys, chart, snapshot, machine_hash, version, key=key)

    return _seal
