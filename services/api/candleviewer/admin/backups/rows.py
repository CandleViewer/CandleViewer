"""A backup run's catalogue row and its `backup.run` records (E42-T05 #966 BK-8). The engine
executes and this records (#966 Q1): no catalogue write or `backup.run` record goes through a
port. Each await has its own bound (`limits`; SR-BK7-01, SR-BK7A-02): a record
`RECORD_BUDGET_S`, a catalogue write `WRITE_BUDGET_S`.

`RunRows.insert` adds a run's `running` row once its `requested` record is written. When the row
cannot be written the request still ends before the caller's `OpsUnavailable` (503): its
`finished` record, `store_unavailable` for an outage and `internal_error` for any other refusal
(SR-BK8A-02), then the row, in case its commit landed.

`RunRows.end` writes `backup.run` `stage: finished` (outcome, `size_bytes`, `checksum_sha256`)
before the row changes, so a row is `ok` only once the trail binds its digest. With that record
unwritten the row ends `failed`, `audit_unavailable`, no digest, and a job `result` it is given
gains `audit: "unavailable"` first, since that job may already read `succeeded`: the row is the
truth (#3674). The row's write is tried `WRITE_TRIES` times, so an end holds its job's lane for at
most one record and that many writes; a success then moves the freshness. A record past its
budget may still land (the writer never interrupts an append it began): the trail may hold a
record no row followed, never a row it does not explain.

A row no end could write stays `running`, as does a job a shutdown cancels (it has no end). At the
next boot, before anything serves, `close_lost` ends each `running` row the same way, as
`internal_error` with reason `lost_on_restart` and the system as actor (SR-BK7-05), and adds it to
`cv_admin_jobs_lost_on_restart_total`, so a row an audit outage ended with no record is still
seen. It assumes this one process ran every `running` row (ADR-0004: one API process, the engine
behind an in-process port). A second boot finds none; a row whose write failed after its record is
ended again later, so the trail may repeat a lost run."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Final, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.metrics import BackupFreshness
from candleviewer.admin.errors import OpsUnavailable
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.storage.errors import StorageError, StorageTierUnavailable
from candleviewer.storage.repositories import backups as port

Actor = Mapping[str, object]  # a record's actor fields
SYSTEM: Final[Actor] = {
    "actor_label": "system:backups", "actor_user_id": None, "actor_ip": None,
    "session_id": None, "request_id": None,
}  # fmt: skip


def _log() -> structlog.stdlib.BoundLogger:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class RunStore(Protocol):
    """What a run reads and writes of BK-3's `BackupStore`."""

    async def page(
        self,
        kind: port.BackupKind | None,
        status: port.BackupStatus | None,
        after: port.Position | None,
        limit: int,
    ) -> list[port.BackupRow]: ...

    async def insert_running(self, new: port.NewBackup) -> port.BackupRow: ...

    async def record_run_finished(
        self, backup_id: UUID, run: port.RunFinished
    ) -> port.BackupRow | None: ...


class RunAudit(Protocol):
    async def emit(self, action: str, **record: object) -> None: ...  # `AuditWriter.emit`


class LostCount(Protocol):
    def inc(self, amount: float = 1) -> None: ...  # `cv_admin_jobs_lost_on_restart_total`


def run_record(
    actor: Actor, backup_id: UUID, state: dict[str, object], reason: str | None
) -> dict[str, object]:
    """A `backup.run` record's `emit` keywords; a stage that failed is a warning."""
    failed = state.get("error") is not None
    return {
        **actor, "object_kind": "backup", "object_id": str(backup_id),
        "outcome": AuditOutcome.FAILURE if failed else AuditOutcome.SUCCESS,
        "severity": Severity.WARNING if failed else Severity.INFO, "reason": reason,
        "after_state": state,
    }  # fmt: skip


async def recorded(record: Awaitable[None], stage: str) -> bool:
    """One `backup.run` record within its budget; `False`, its class logged, when unwritten."""
    try:
        async with asyncio.timeout(limits.RECORD_BUDGET_S):
            await record
    except Exception as exc:  # not made durable in time (C-2.9)
        _log().error("backups.run_unrecorded", stage=stage, error=type(exc).__name__)
        return False
    return True


class RunRows:
    def __init__(
        self,
        store: RunStore,
        audit: RunAudit,
        *,
        lost: LostCount,
        freshness: BackupFreshness | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store, self._audit, self._lost = store, audit, lost
        self._freshness, self._now = freshness, now

    async def insert(self, actor: Actor, new: port.NewBackup) -> port.BackupRow:
        """`new`'s `running` row; one that cannot be written ends its request first."""
        try:
            async with asyncio.timeout(limits.WRITE_BUDGET_S):
                return await self._store.insert_running(new)
        except Exception as exc:  # an outage, or a refused statement or value
            outage = isinstance(exc, (TimeoutError, StorageTierUnavailable))
            failure = type(exc).__name__
        _log().error("backups.run_not_inserted", backup_id=str(new.id), error=failure)
        code: port.BackupErrorCode = "store_unavailable" if outage else "internal_error"
        await self.end(actor, new.id, port.RunFinished(self._now(), code))  # a lost commit too
        raise OpsUnavailable("backups: store unavailable")

    async def end(
        self,
        actor: Actor,
        backup_id: UUID,
        run: port.RunFinished,
        why: str = "",
        result: dict[str, object] | None = None,
    ) -> bool:
        """The `finished` record, then the row; `False` when the row could not be written."""
        state: dict[str, object] = {"stage": "finished", "size_bytes": run.size_bytes}
        state |= {"checksum_sha256": run.checksum_sha256, "error": run.error}
        reason = why or run.error
        record = self._audit.emit("backup.run", **run_record(actor, backup_id, state, reason))
        if not await recorded(record, "finished"):
            run = port.RunFinished(run.finished_at, "audit_unavailable")  # never `ok`, no digest
            if result is not None:
                result["audit"] = "unavailable"  # ahead of the row
        for attempt in range(1, limits.WRITE_TRIES + 1):
            try:
                async with asyncio.timeout(limits.WRITE_BUDGET_S):
                    row = await self._store.record_run_finished(backup_id, run)
            except Exception as exc:
                where = {"backup_id": str(backup_id), "attempt": attempt}
                _log().error("backups.run_not_ended", **where, error=type(exc).__name__)
                continue
            if row is not None and self._freshness is not None:
                self._freshness.record_success(row)
            return True
        return False  # left `running`: a later boot ends it (`close_lost`)

    async def close_lost(self) -> int:
        """At boot, before this process runs anything, end every `running` row: the process that
        ran it is gone (SR-BK7-05). One page of `LOST_RUNS_LIMIT` rows; a store outage ends the
        pass, logged, and never fails boot. Returns how many rows it ended, each counted lost."""
        try:
            async with asyncio.timeout(limits.LOST_READ_BUDGET_S):
                rows = await self._store.page(None, "running", None, limits.LOST_RUNS_LIMIT)
        except (TimeoutError, StorageError) as exc:
            _log().error("backups.lost_runs_unread", error=type(exc).__name__)
            return 0
        ended = 0
        for row in rows:
            lost = port.RunFinished(self._now(), "internal_error")
            if not await self.end(SYSTEM, row.id, lost, "lost_on_restart"):
                break
            ended += 1
        if ended:  # a boot with none logs nothing
            self._lost.inc(ended)
            _log().info("backups.lost_runs_ended", count=ended)
        return ended


class LostRuns:
    """The lifespan's boot step (SR-BK7-05): `close_lost`, once, before the app serves."""

    def __init__(self, rows: RunRows) -> None:
        self._rows = rows

    async def start(self) -> None:
        await self._rows.close_lost()
