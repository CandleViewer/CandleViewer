"""Backup deletion test fakes (E42-T05 #966 BK-12): BK-4's store with a delete's reads and its mark,
each op failing or stalling on demand; an artefact remover; an audit trail; and `BackupDeletion`
over them, with BK-5's freshness on a gauge of its own. Every step lands in one log, in order, with
whether the admission lock was held."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from candleviewer.admin.backups.deletion import BackupDeletion, DeleteRecord, WriteAhead
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.metrics import BackupFreshness
from candleviewer.audit.access import AuditPrincipal
from candleviewer.observability.metrics import Gauge
from candleviewer.storage.repositories.backups import SUCCESS_STATUSES, BackupRow, counts_as_usable
from tests.unit.admin._backup_fakes import NOW, Store

HANG = "hang"  # a fault: the call never ends
Log = list[tuple[str, bool]]  # each step, and whether the admission lock was held


async def _fail(fault: Any) -> None:
    if fault == HANG:
        await asyncio.Event().wait()
    if isinstance(fault, Exception):
        raise fault


class Catalogue(Store):
    """`faults[op]`: an exception it raises, `HANG`, or a list of either, one per call (then the
    op succeeds). `marked_by` is who each mark names."""

    def __init__(self, rows: Sequence[BackupRow], gate: BackupJobGate, log: Log, **faults: Any):
        super().__init__(rows)
        self.gate, self.log, self.faults = gate, log, faults
        self.marked_by: dict[UUID, UUID] = {}

    async def _called(self, *call: Any) -> None:
        self.calls.append(call)
        self.log.append((call[0], self.gate._lock.locked()))
        fault = self.faults.get(call[0])
        await _fail((fault.pop(0) if fault else None) if isinstance(fault, list) else fault)

    async def usable_count(self, kind: str) -> int:
        await self._called("usable_count", kind)
        return sum(1 for r in self.rows if r.kind == kind and counts_as_usable(r))

    async def mark_deleted(self, backup_id: UUID, *, by: UUID, at: datetime) -> BackupRow | None:
        await self._called("mark_deleted", backup_id)
        for n, r in enumerate(self.rows):  # BK-3's guard: once, never on a running backup
            if r.id == backup_id and r.status != "running" and r.deleted_at is None:
                self.rows[n], self.marked_by[backup_id] = replace(r, deleted_at=at), by
                return self.rows[n]
        return None

    async def last_success_by_kind(self) -> dict[Any, datetime]:
        await self._called("last_success_by_kind")
        last: dict[Any, datetime] = {}
        for r in self.rows:
            if r.status in SUCCESS_STATUSES and r.finished_at and r.deleted_at is None:
                last[r.kind] = max(r.finished_at, last.get(r.kind, r.finished_at))
        return last


class Remover:
    """`ArtefactRemover`: each `(backup_id, location)` asked to go. It yields to the loop first,
    as a filesystem call would, so a delete that did not hold the lock would interleave."""

    def __init__(self, gate: BackupJobGate, log: Log, fault: Any = None) -> None:
        self.gate, self.log, self.fault = gate, log, fault
        self.removed: list[tuple[UUID, str]] = []

    async def remove(self, backup_id: UUID, location: str) -> None:
        self.removed.append((backup_id, location))
        self.log.append(("remove", self.gate._lock.locked()))
        await asyncio.sleep(0)
        await _fail(self.fault)


class Trail:
    """`AuditWriter.emit`: every record as passed; one whose `reason` is in `fail_on` raises (the
    write-ahead record's is `None`), as an unwritable WAL does."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.fail_on: frozenset[str | None] = frozenset()

    async def emit(self, action: str, **record: Any) -> None:
        if record["reason"] in self.fail_on:
            raise RuntimeError("WAL unwritable")
        self.records.append({"action": action, **record})


@dataclass
class World:
    deletion: BackupDeletion
    store: Catalogue
    remover: Remover
    gate: BackupJobGate
    trail: Trail
    freshness: BackupFreshness
    gauge: Gauge
    log: Log

    def write_ahead(self, who: AuditPrincipal) -> WriteAhead:
        """What the route passes: each record through `audit_delete`."""

        async def record(entry: DeleteRecord) -> None:
            self.log.append(("record", self.gate._lock.locked()))
            await self.deletion.audit_delete(who, entry)

        return record


def world(
    rows: Sequence[BackupRow] = (),
    *,
    remove: Any = None,
    gate: BackupJobGate | None = None,
    faults: dict[str, Any] | None = None,
    **budgets: float,
) -> World:
    gate, log, trail = BackupJobGate() if gate is None else gate, Log(), Trail()
    store, remover = Catalogue(rows, gate, log, **(faults or {})), Remover(gate, log, remove)
    gauge = Gauge("cv_backup_last_success_age_seconds", "age", ["kind"], registry=None)
    freshness = BackupFreshness(store, now=lambda: NOW, gauge=gauge)
    deletion = BackupDeletion(store, remover, gate=gate, audit=trail, freshness=freshness,
                              now=lambda: NOW, **budgets)  # fmt: skip
    return World(deletion, store, remover, gate, trail, freshness, gauge, log)
