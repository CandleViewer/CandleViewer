"""Statechart inspector read model (E42-T07, M21): `listStatecharts` and `exportStatechart`.

Never holds, builds or queries an `Interpreter` (MUSTNOT-03, C-2.20): a machine comes from its
snapshot once the HMAC envelope verifies (`persistence.open_sealed`, CV-C53), a chart from the
registry. E17-T08's grammar and check arrive as `KeyOf` and `Visible` (M21 may not import `ws`).
A row that does not verify, or whose metadata is off the contract, is left out and named; its
`system_events` row needs a migration, so it lands with the store.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import Any, Final, Protocol
from uuid import UUID

from candleviewer.admin.overview.fanout import Degraded, SliceFanOut, SliceResult, SourceUnavailable
from candleviewer.admin.overview.slices import AdminSlice
from candleviewer.settings import Environment
from candleviewer.statechart.errors import StatechartRegistryError
from candleviewer.statechart.persistence import HmacKeys, MachineKey, SealedSnapshot, open_sealed
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


@dataclass(frozen=True, slots=True)
class Machine:
    row: SnapshotRow
    key: str | None
    state: str
    machine_hash: str
    lock_matches: bool
    chain_trips: int
    deferred_depth: int | None

    @property
    def position(self) -> Position:
        return (self.row.machine_kind, self.key or "", self.row.environment)


@dataclass(frozen=True, slots=True)
class Listing:
    snapshots: SliceResult[tuple[Machine, ...]]
    metrics: SliceResult[None]
    items: tuple[Machine, ...]
    kinds: list[dict[str, Any]]
    has_more: bool


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


def _summaries(machines: Sequence[Machine]) -> list[dict[str, Any]]:
    """`StatechartKindSummary` rows; `dropped_receipts` is `null` until a metrics source exists."""
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
            "dropped_receipts": None,
        }
        for (kind, env), group in sorted(groups.items())
    ]


class StatechartInspector:
    """`lock` is the committed `machine_hashes.lock` (kind -> hash). `store` stays `None` until
    wired; a store without the HMAC keys that verify it is unwired too (CV-C53)."""

    def __init__(
        self,
        fan: SliceFanOut,
        key_of: KeyOf,
        lock: Mapping[str, str],
        *,
        store: SnapshotStore | None = None,
        keys: HmacKeys | None = None,
        registry: Registry | None = None,
    ) -> None:
        self._fan, self._key_of, self._lock = fan, key_of, lock
        self._store, self._keys, self._registry = store, keys, registry

    @cached_property
    def registry(self) -> Registry:
        """The given registry, else one loaded on first use (validating 20 charts takes ~0.1 s)."""
        return self._registry or Registry()

    def export(self, kind: str) -> dict[str, Any]:
        """`StatechartExport` of a registered chart; `MachineNotFoundError` for any other kind."""
        chart = self.registry.get(kind)
        return {
            "machine_kind": kind,
            "machine_hash": machine_hash(chart),
            "stately": export_stately(chart),
        }

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
        kinds = _summaries(machines)
        return Listing(snaps, metrics, tuple(rows[:limit]), kinds, len(rows) > limit)

    async def _read(self) -> tuple[Machine, ...] | Degraded[tuple[Machine, ...]]:
        if self._store is None or self._keys is None:
            raise SourceUnavailable("snapshots: no provider wired")
        rows, keys = await self._store.snapshots(), self._keys
        # An HMAC per row is CPU work, so it runs off the event loop.
        found = await asyncio.to_thread(lambda: [self._verified(row, keys) for row in rows])
        kept = tuple(m for m in found if m is not None)
        return Degraded(kept, "error", SEAL_FAILED, "seal") if len(kept) < len(rows) else kept

    def _verified(self, row: SnapshotRow, keys: HmacKeys) -> Machine | None:
        try:
            return self._project(row, keys)
        except (ValueError, TypeError, KeyError, StatechartRegistryError):
            return None  # fail closed: neither shown nor counted

    def _project(self, row: SnapshotRow, keys: HmacKeys) -> Machine:
        # The seal ties `environment` to the envelope, not the contract; `updated_at` is unsealed.
        if row.environment not in Environment or row.updated_at.utcoffset() is None:
            raise ValueError("row metadata is off the contract")
        chart = self.registry.get(row.machine_kind)
        expected = machine_hash(chart)  # MUST-12: the envelope must carry the registered hash
        # The key is the row's own columns, never the envelope's claim: the seal must bind the two.
        key = MachineKey(row.machine_kind, row.entity_id or row.machine_kind, row.environment)
        snap = open_sealed(keys, chart, row.envelope, key=key, expected_machine_hash=expected)
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
        )

    async def _dropped(self) -> None:
        """No `CvMetricsPlugin` reports to a registry the API reads yet: `unavailable`."""
        raise SourceUnavailable("metrics: no provider wired")
