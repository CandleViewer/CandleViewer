"""Statechart inspector read model (E42-T07, M21): `listStatecharts`, `getStatechart` and
`exportStatechart`.

Never holds, builds or queries an `Interpreter` (MUSTNOT-03, C-2.20): a machine comes from its
snapshot once the HMAC envelope verifies (`persistence.open_sealed`, CV-C53), a chart from the
registry. E17-T08's grammar and check arrive as `KeyOf` and `Visible` (M21 may not import `ws`);
a row's `scope` is the one the owning module bound in the topic's registry, set by the store the
composition root wires (`admin_wiring.RegistryScopedStore`), so a row without one is shown to no
role for a scoped kind (fail closed). A row that does not verify, or whose metadata is off the
contract, is left out and named in `_checked`, the one place both reads leave a row out, which
hands it to `SealFailures`: one `statechart` `system_events` row per snapshot version (migration
0057 admits the component), written off the read so it never costs the slice its budget.
`dropped_receipts` is the process's `cv_machine_dropped_receipts_total` per kind
(E50-T60), read through `DroppedReceipts`; `chain_trips` comes from the verified snapshot itself,
not from `machine_events`. The detail's `context_summary` holds only the keys the topic sends for
the kind (`state_feed.SUMMARY`, 23 §6.4), and its timeline is the latest `machine_events` rows
without their payloads.
"""

from __future__ import annotations

import asyncio
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.admin.audited import audit_exempt
from candleviewer.admin.overview.fanout import Degraded, SliceFanOut, SliceResult, SourceUnavailable
from candleviewer.admin.overview.slices import AdminSlice
from candleviewer.observability.context import spawn
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from candleviewer.settings import Environment
from candleviewer.statechart.errors import StatechartRegistryError
from candleviewer.statechart.persistence import HmacKeys, MachineKey, SealedSnapshot, open_sealed
from candleviewer.statechart.plugins.state_feed import SUMMARY
from candleviewer.statechart.registry import Registry, export_stately, machine_hash

#: `snapshots.detail` when a snapshot is left out (`listStatecharts`).
SEAL_FAILED: Final = "snapshot seal did not verify"
#: The list's sort key and page position: (`machine_kind`, `machine_key`, environment).
Position = tuple[str, str, str]
#: A machine's `machineKey`, or `None`: its kind has no public id, or the id is off the grammar.
KeyOf = Callable[[str, str | None], str | None]


@dataclass(frozen=True, slots=True)
class BoundScope:
    """The scope the owning module binds to a machine from its own record (23 §6.4)."""

    accounts: frozenset[UUID] = frozenset()
    user: UUID | None = None


@dataclass(frozen=True, slots=True)
class DroppedReceipts:
    """`cv_machine_dropped_receipts_total` per machine kind since process start, for the
    process's own `env` only; a kind with no series has dropped none. `read` is synchronous (an
    in-memory registry read), so it runs off the loop. A row of another environment gets `null`:
    this process cannot read that environment's counter."""

    env: str
    read: Callable[[], Mapping[str, int]]


#: The most `machine_events` rows the detail shows (`StatechartMachineDetail.recent_events`).
RECENT_EVENTS: Final = 50
#: The caller's per-entity check: may it see a machine of this kind and bound scope?
Visible = Callable[[str, BoundScope], bool]


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    """A `machine_snapshots` row, its §6.4 public id and the owning module's scope (not context)."""

    machine_kind: str
    entity_id: str | None
    environment: str
    envelope: SealedSnapshot
    updated_at: datetime
    scope: BoundScope = field(default_factory=BoundScope)


class SnapshotStore(Protocol):
    async def snapshots(self) -> Sequence[SnapshotRow]:
        """Every persisted snapshot of every environment."""

    async def snapshot(
        self, machine_kind: str, entity_id: str | None, environment: str
    ) -> SnapshotRow | None:
        """One machine's snapshot (`entity_id` `None` for a singleton), or `None`."""


@dataclass(frozen=True, slots=True)
class RecentEvent:
    """A `machine_events` row as the detail shows it: no payload, no fault content."""

    event_type: str
    phase: str
    from_states: tuple[str, ...]
    to_states: tuple[str, ...]
    faulted: bool
    occurred_at: datetime


class EventStore(Protocol):
    async def recent(self, key: MachineKey, limit: int) -> Sequence[RecentEvent]:
        """The machine's latest `limit` rows, newest first."""


@dataclass(frozen=True, slots=True)
class Machine:
    row: SnapshotRow
    key: str | None
    state: str
    machine_hash: str
    lock_matches: bool
    chain_trips: int
    deferred_depth: int | None
    #: Every active state id, ancestors included, sorted; and the topic's redacted summary.
    configuration: tuple[str, ...] = ()
    context_summary: Mapping[str, Any] = field(default_factory=dict)

    @property
    @audit_exempt("read")
    def position(self) -> Position:
        return (self.row.machine_kind, self.key or "", self.row.environment)


@dataclass(frozen=True, slots=True)
class Listing:
    snapshots: SliceResult[tuple[Machine, ...]]
    metrics: SliceResult[Mapping[str, int]]
    items: tuple[Machine, ...]
    kinds: list[dict[str, Any]]
    has_more: bool


@dataclass(frozen=True, slots=True)
class Detail:
    """`getStatechart`: `machine` is set only when `snapshots` is `ok`; `events` only then."""

    snapshots: SliceResult[Machine | None]
    events: SliceResult[tuple[RecentEvent, ...]] | None
    config: Mapping[str, Any] | None


#: The kinds whose public entity id is their symbol (23 §6.4); an `order` id is a UUID, never one.
_SYMBOL_ENTITIES: Final = frozenset({"book", "recording"})


def context_summary(kind: str, context: object, entity_id: str | None) -> dict[str, Any]:
    """The topic's `context_summary` (`CvStateFeedPlugin`'s rule): each key the kind may send,
    only when its value has its type; `book` and `recording` name their entity's symbol."""
    found = context if isinstance(context, Mapping) else {}
    summary: dict[str, Any] = {}
    for key, valid in SUMMARY.get(kind, {}).items():
        value = found.get(key)
        if value is None and key == "symbol" and kind in _SYMBOL_ENTITIES and valid(entity_id):
            value = entity_id
        if valid(value):
            summary[key] = value
    return summary


def published_state(chart: Mapping[str, Any], active: frozenset[str]) -> str:
    """The root's active child (the first region's, if parallel), as on the topic, or ValueError."""
    root, states = str(chart["id"]), chart.get("states") or {}
    if chart.get("type") == "parallel" and states:
        region = next(iter(states))
        root, states = f"{root}.{region}", states[region].get("states") or {}
    state = next((str(name) for name in states if f"{root}.{name}" in active), None)
    if state is None:
        raise ValueError("no active state under the chart root")
    return state


def _summaries(
    machines: Sequence[Machine], dropped: Mapping[str, int] | None, dropped_env: str | None
) -> list[dict[str, Any]]:
    """`StatechartKindSummary` rows; `dropped_receipts` is `null` when the metrics slice failed
    or the row's environment is not the one the process counts for."""
    groups: dict[tuple[str, str], list[Machine]] = {}
    for m in machines:
        groups.setdefault((m.row.machine_kind, m.row.environment), []).append(m)
    return [
        {
            "machine_kind": kind,
            "environment": env,
            "machines": len(group),
            "by_state": dict(sorted(Counter(m.state for m in group).items())),
            "chain_trips": sum(m.chain_trips for m in group),
            "degraded_machines": sum(m.chain_trips > 0 for m in group),
            "dropped_receipts": (
                dropped.get(kind, 0) if dropped is not None and env == dropped_env else None
            ),
        }
        for (kind, env), group in sorted(groups.items())
    ]


#: The `system_events` row of a left-out snapshot (22 `listStatecharts`): a fixed message, never
#: the snapshot's content, its key id or its tag.
SEAL_EVENT_KIND: Final = "snapshot_seal_failed"
SEAL_EVENT_MESSAGE: Final = "a statechart snapshot did not verify and is left out of the inspector"
#: A stalled sink must not hold a write task for long, nor may failures pile up tasks (C-2.18).
SEAL_EVENT_TIMEOUT_S: Final = 1.0
MAX_IN_FLIGHT: Final = 16
#: Snapshot versions already reported, oldest forgotten first.
MAX_REPORTED: Final = 4096
#: Why a row was left out, the closed word list of `details["reason"]` (never exception text):
#: its envelope did not verify (`open_sealed`, an unknown key id included), or its metadata, kind
#: or verified payload is off the contract.
SealReason = Literal["seal", "off_contract"]
#: (kind, entity id, environment, `updated_at`): one snapshot version.
_Version = tuple[str, str | None, str, datetime]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _SealRefused(ValueError):
    """`open_sealed` refused the envelope; any other failure of a row is off the contract."""


class SealFailures:
    """Writes one critical `statechart` `system_events` row per left-out snapshot version
    (machine, environment, `updated_at`), not one per read. `details` hold the kind, the public
    machine key (when the kind has one), the environment and `updated_at`: never the entity id of
    a kind without a public one, the context, the key id or the tag. `report` does no I/O and never
    raises; the write runs in a tracked task under a timeout, at most `max_in_flight` at once. A
    version is remembered once its write is started (bounded, oldest first); a failed or skipped
    write is forgotten, so a later read reports it again. A failure is logged by class only.
    The remembered versions are per process: after a restart a still-bad version writes one more
    row, which `listIncidents` folds into the same incident."""

    def __init__(
        self,
        events: SystemEventWriter,
        key_of: KeyOf,
        *,
        timeout_s: float = SEAL_EVENT_TIMEOUT_S,
        max_in_flight: int = MAX_IN_FLIGHT,
        max_reported: int = MAX_REPORTED,
    ) -> None:
        self._events, self._key_of = events, key_of
        self._timeout_s, self._max_in_flight = timeout_s, max_in_flight
        self._max_reported = max_reported
        self._reported: OrderedDict[_Version, None] = OrderedDict()
        self._tasks: set[asyncio.Task[None]] = set()

    @audit_exempt("read")  # called by the reads; its row is telemetry (22), not an admin action
    def report(self, row: SnapshotRow, reason: SealReason = "seal") -> None:
        version = (row.machine_kind, row.entity_id, row.environment, row.updated_at)
        if version in self._reported:
            return
        if len(self._tasks) >= self._max_in_flight:
            _log().warning("statechart.seal_event_skipped", reason="in_flight")
            return
        self._reported[version] = None
        while len(self._reported) > self._max_reported:
            self._reported.popitem(last=False)
        details = {
            "machine_kind": row.machine_kind,
            "environment": row.environment,
            "updated_at": row.updated_at.isoformat(),
            "reason": reason,
        }
        key = self._key_of(row.machine_kind, row.entity_id)
        if key is not None:  # `machine`: the redactor masks any `*_key` (24 Sec.15.4)
            details["machine"] = key
        event = SystemEvent(
            component="statechart",
            kind=SEAL_EVENT_KIND,
            severity="critical",
            message=SEAL_EVENT_MESSAGE,
            details=details,
        )
        task = spawn(self._write(version, event), name="statechart-seal-event")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _write(self, version: _Version, event: SystemEvent) -> None:
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._events.write(event)
        except Exception as exc:  # telemetry: never the read, never raised
            self._reported.pop(version, None)
            _log().error("statechart.seal_event_failed", error=type(exc).__name__)

    @audit_exempt("lifecycle")
    async def drain(self) -> None:
        """Await every write in flight; each ends by its own timeout (the lifespan teardown)."""
        while self._tasks:
            await asyncio.wait(set(self._tasks))


class StatechartInspector:
    """`lock` is the committed `machine_hashes.lock` (kind -> hash). `store` stays `None` until
    wired; a store without the HMAC keys that verify it is unwired too (CV-C53). `dropped` reads
    the metric registry the `CvMetricsPlugin`s count on; `None` leaves `metrics` unavailable.
    `system_events` receives the row of each left-out snapshot version; `None` writes none."""

    def __init__(
        self,
        fan: SliceFanOut,
        key_of: KeyOf,
        lock: Mapping[str, str],
        *,
        store: SnapshotStore | None = None,
        keys: HmacKeys | None = None,
        registry: Registry | None = None,
        dropped: DroppedReceipts | None = None,
        events: EventStore | None = None,
        system_events: SystemEventWriter | None = None,
        seal_timeout_s: float = SEAL_EVENT_TIMEOUT_S,
    ) -> None:
        self._fan, self._key_of, self._lock = fan, key_of, lock
        self.seal_failures = (
            None
            if system_events is None
            else SealFailures(system_events, key_of, timeout_s=seal_timeout_s)
        )
        self._store, self._keys, self._registry = store, keys, registry
        self._dropped_receipts, self._events = dropped, events

    @cached_property
    @audit_exempt("read")
    def registry(self) -> Registry:
        """The given registry, else one loaded on first use (validating 20 charts takes ~0.1 s)."""
        return self._registry or Registry()

    @audit_exempt("read")
    def export(self, kind: str) -> dict[str, Any]:
        """`StatechartExport` of a registered chart; `MachineNotFoundError` for any other kind."""
        chart = self.registry.get(kind)
        return {
            "machine_kind": kind,
            "machine_hash": machine_hash(chart),
            "stately": export_stately(chart),
        }

    @audit_exempt("read")
    async def listing(
        self,
        visible: Visible,
        *,
        kind: str | None = None,
        environment: str | None = None,
        degraded: bool | None = None,
        after: Position | None = None,
        limit: int = 100,
    ) -> Listing:
        """`kind`/`environment` narrow `items` and `kinds`; the rest narrow `items` only."""
        snaps, metrics = await asyncio.gather(
            self._fan.read(AdminSlice.STATECHART_SNAPSHOTS, self._read),
            self._fan.read(AdminSlice.STATECHART_METRICS, self._dropped),
        )
        machines = [
            m
            for m in snaps.value or ()
            if kind in (None, m.row.machine_kind) and environment in (None, m.row.environment)
        ]
        rows = sorted(
            (
                m
                for m in machines
                if m.key is not None
                and degraded in (None, m.chain_trips > 0)
                and (after is None or m.position > after)
                and visible(m.row.machine_kind, m.row.scope)
            ),
            key=lambda m: m.position,
        )
        dropped_env = None if self._dropped_receipts is None else self._dropped_receipts.env
        ok = metrics.value if metrics.status == "ok" else None
        kinds = _summaries(machines, ok, dropped_env)
        return Listing(snaps, metrics, tuple(rows[:limit]), kinds, len(rows) > limit)

    @audit_exempt("read")
    async def detail(
        self, visible: Visible, kinds: Sequence[str], entity_id: str | None, environment: str
    ) -> Detail | None:
        """One machine of one of `kinds` (the four algo charts share an entity) in `environment`,
        or `None` when there is none or the caller may not see it: the same answer, decided
        before the seal is checked. A read that cannot be made, or a seal that does not verify,
        is a `Detail` without the machine. Every read is live (the cache is the list's)."""
        hidden = False

        async def load() -> Machine | Degraded[Machine | None] | None:
            nonlocal hidden
            if self._store is None or self._keys is None:
                raise SourceUnavailable("snapshots: no provider wired")
            store, keys = self._store, self._keys
            row = None
            for kind in kinds:
                if (row := await store.snapshot(kind, entity_id, environment)) is not None:
                    break
            if row is None or not visible(row.machine_kind, row.scope):
                hidden = True
                return None
            (machine,) = await self._checked((row,), keys)
            return Degraded(None, "error", SEAL_FAILED, "seal") if machine is None else machine

        snaps = await self._fan.read(AdminSlice.STATECHART_SNAPSHOTS, load, cached=False)
        if hidden:
            return None
        found = snaps.value if snaps.status == "ok" else None
        if found is None:
            return Detail(snaps, None, None)
        key = MachineKey(found.row.machine_kind, entity_id or found.row.machine_kind, environment)
        events = await self._fan.read(
            AdminSlice.STATECHART_EVENTS, lambda: self._recent(key), cached=False
        )
        return Detail(snaps, events, self.registry.get(key.machine_kind))

    async def _recent(self, key: MachineKey) -> tuple[RecentEvent, ...]:
        if self._events is None:
            raise SourceUnavailable("events: no provider wired")
        return tuple(await self._events.recent(key, RECENT_EVENTS))

    async def _read(self) -> tuple[Machine, ...] | Degraded[tuple[Machine, ...]]:
        if self._store is None or self._keys is None:
            raise SourceUnavailable("snapshots: no provider wired")
        rows, keys = await self._store.snapshots(), self._keys
        found = await self._checked(rows, keys)
        kept = tuple(m for m in found if m is not None)
        return Degraded(kept, "error", SEAL_FAILED, "seal") if len(kept) < len(rows) else kept

    async def _checked(self, rows: Sequence[SnapshotRow], keys: HmacKeys) -> list[Machine | None]:
        """Each row's machine, or `None`: the one point a row is left out (list and detail), and
        the one that reports it. An HMAC per row is CPU work, so it runs off the event loop."""
        found = await asyncio.to_thread(lambda: [self._verified(row, keys) for row in rows])
        if self.seal_failures is not None:
            for row, machine in zip(rows, found, strict=True):
                if isinstance(machine, str):
                    self.seal_failures.report(row, machine)
        return [m if isinstance(m, Machine) else None for m in found]

    def _verified(self, row: SnapshotRow, keys: HmacKeys) -> Machine | SealReason:
        """The row's machine, or why it is left out: its seal or the contract."""
        try:
            return self._project(row, keys)
        except _SealRefused:
            return "seal"  # fail closed: neither shown nor counted
        except (ValueError, TypeError, KeyError, StatechartRegistryError):
            return "off_contract"

    def _project(self, row: SnapshotRow, keys: HmacKeys) -> Machine:
        # The seal ties `environment` to the envelope, not the contract; `updated_at` is unsealed.
        if row.environment not in Environment or row.updated_at.utcoffset() is None:
            raise ValueError("row metadata is off the contract")
        chart = self.registry.get(row.machine_kind)
        expected = machine_hash(chart)  # MUST-12: the envelope must carry the registered hash
        # The key is the row's own columns, never the envelope's claim: the seal must bind the two.
        key = MachineKey(row.machine_kind, row.entity_id or row.machine_kind, row.environment)
        try:
            snap = open_sealed(keys, chart, row.envelope, key=key, expected_machine_hash=expected)
        except (ValueError, TypeError, KeyError) as exc:
            raise _SealRefused from exc
        configuration, trips = snap.get("configuration"), snap.get("chain_trips", 0)
        if not isinstance(configuration, list) or not all(
            isinstance(s, str) for s in configuration
        ):
            raise ValueError("snapshot carries no configuration")
        if type(trips) is not int or trips < 0:
            raise ValueError("snapshot carries no chain_trips count")
        deferred = snap.get("deferred")
        return Machine(
            row,
            self._key_of(row.machine_kind, row.entity_id),
            published_state(chart, frozenset(configuration)),
            expected,
            self._lock.get(row.machine_kind) == expected,
            trips,
            len(deferred) if isinstance(deferred, list) else None,
            tuple(sorted(configuration)),
            context_summary(row.machine_kind, snap.get("context"), row.entity_id),
        )

    async def _dropped(self) -> Mapping[str, int]:
        """Per kind, from the registry; a negative or non-integral count fails the slice."""
        if self._dropped_receipts is None:
            raise SourceUnavailable("metrics: no provider wired")
        counts = await asyncio.to_thread(self._dropped_receipts.read)
        if not all(type(n) is int and n >= 0 for n in counts.values()):
            raise ValueError("dropped receipts are not counts")
        return dict(counts)
