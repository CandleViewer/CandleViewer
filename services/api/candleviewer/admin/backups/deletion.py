"""`deleteBackup` once its grant is spent (E42-T05 #966 BK-12): the artefact goes; the catalogue row
stays (21 Sec.7), `mark_deleted` setting `deleted_at` and `deleted_by`, its status unchanged.

Under the admission lock (`admit_delete`), one delete at a time and never beside a run, a
verification, a restore or a link issue (SR-BK0-08): the row read again, then, in the contract's
order, `backup_deleted`, `backup_in_use` (`running`, or a job on it) and `last_usable_backup` (Q4:
the kind's last backup that `counts_as_usable`), or `not_found` for a row gone since the route read
it (the runtime role may delete none: 0032). Each refusal is a `backup.deleted` failure record,
`reason` its rule, written before `DeleteRefused`. Then the write-ahead record (C-2.9), the engine's
`remove` of the row's own id and stored `location` (never a client's path), the mark, and BK-5's
freshness `recompute`. A removal or a mark that fails, in any way, is a second record
(`store_unavailable`) and `OpsUnavailable` (503), the row unmarked; the remover counts an artefact
already gone as removed, so a retry completes the delete. A lock wait past `ADMIT_WAIT_S`, or a
catalogue that fails or stalls under the lock, is `OpsUnavailable` with its failure record; an
unwritten record is `OpsAuditUnavailable` (503). Either way the grant the route spent stays spent.
Every await has its own bound (`limits`), and every record goes through the handler's
`write_ahead` (`audit_delete`).

SR-BK3-01 (decided 2026-10-19): the count and the mark serialise against the kind's verify-outcome
write through this lock, which BK-9 takes for that write (`serialized()`), not a transaction-scoped
advisory lock: the check and the mark straddle the removal, which no transaction can span, and in
v1 every outcome write is in-process. An out-of-process writer would need the advisory form.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol, TypeVar
from uuid import UUID

import structlog

from candleviewer.admin.audited import audited
from candleviewer.admin.backups import limits
from candleviewer.admin.backups.catalogue import READ_BUDGET_S
from candleviewer.admin.backups.gate import Admission, BackupConflict, BackupJobGate
from candleviewer.admin.backups.metrics import BackupFreshness
from candleviewer.admin.backups.ports import ArtefactRemover
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsUnavailable
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.context import current_request_id
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import backups as port

DeleteRule = Literal["not_found", "backup_deleted", "backup_in_use", "last_usable_backup"]
_UNAVAILABLE: Final = "store_unavailable"
_T = TypeVar("_T")  # not PEP 695 `[T]`, as in `catalogue`


class DeleteRefused(AdminError):
    """Refused after the spend, its record written: `not_found` (404), else `409 conflict`."""

    def __init__(self, rule: DeleteRule) -> None:
        super().__init__(rule)
        self.rule: DeleteRule = rule


@dataclass(frozen=True, slots=True)
class DeleteRecord:
    """One `backup.deleted` record: the spent grant's challenge, the status the row was read with
    (none when it was not read), and a refusal's or a failure's reason (none: the write-ahead)."""

    backup_id: UUID
    challenge_id: UUID
    status: port.BackupStatus | None = None
    reason: str | None = None


WriteAhead = Callable[[DeleteRecord], Awaitable[None]]


class DeleteStore(Protocol):
    """What a delete reads and writes of BK-3's `BackupStore`."""

    async def get(self, backup_id: UUID) -> port.BackupRow | None: ...

    async def usable_count(self, kind: port.BackupKind) -> int: ...

    async def mark_deleted(
        self, backup_id: UUID, *, by: UUID, at: datetime
    ) -> port.BackupRow | None: ...


class DeleteAudit(Protocol):
    async def emit(self, action: str, **record: Any) -> None: ...  # `AuditWriter.emit`


@dataclass(frozen=True, slots=True)
class _Call:
    backup_id: UUID
    who: AuditPrincipal
    challenge_id: UUID
    write_ahead: WriteAhead


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BackupDeletion:
    def __init__(
        self,
        store: DeleteStore,
        remover: ArtefactRemover,
        *,
        gate: BackupJobGate,
        audit: DeleteAudit,
        freshness: BackupFreshness | None = None,
        now: Callable[[], datetime] = utc_now,
        read_budget_s: float = READ_BUDGET_S,
        record_budget_s: float = limits.DELETE_RECORD_BUDGET_S,
        remove_budget_s: float = limits.REMOVE_BUDGET_S,
        mark_budget_s: float = limits.WRITE_BUDGET_S,
    ) -> None:
        self._store, self._remover, self._gate, self._audit = store, remover, gate, audit
        self._freshness, self._now = freshness, now
        self._read_budget_s, self._record_budget_s = read_budget_s, record_budget_s
        self._remove_budget_s, self._mark_budget_s = remove_budget_s, mark_budget_s

    @audited("backup.deleted")
    async def delete(
        self, backup_id: UUID, who: AuditPrincipal, challenge_id: UUID, write_ahead: WriteAhead
    ) -> None:
        """Delete `backup_id`'s artefact for `who`, once the grant `challenge_id` is spent."""
        call, held = _Call(backup_id, who, challenge_id, write_ahead), False
        try:
            async with self._gate.admit_delete(backup_id) as admission:
                held = True
                await self._delete(admission, call)
        except OpsUnavailable:
            if not held:  # the lock's wait outlasted its bound: recorded without it (SR-BK7A-03)
                await self._write(call, None, _UNAVAILABLE)
            raise

    @audited("backup.deleted")
    async def audit_delete(self, who: AuditPrincipal, record: DeleteRecord) -> None:
        """`backup.deleted`, severity `warning`: the spent grant's `challenge_id`, the row's
        `before_state.status` when it was read, and for a refusal or a failure `outcome: failure`
        with its `reason`."""
        before = None if record.status is None else {"status": record.status}
        failed = record.reason is not None
        await self._audit.emit(
            "backup.deleted", actor_label=who.username, actor_user_id=who.user_id,
            actor_ip=who.ip, session_id=who.session_id, object_kind="backup",
            object_id=str(record.backup_id),
            outcome=AuditOutcome.FAILURE if failed else AuditOutcome.SUCCESS,
            severity=Severity.WARNING, reason=record.reason, before_state=before,
            after_state={"challenge_id": str(record.challenge_id)}, request_id=who.request_id,
        )  # fmt: skip

    async def _delete(self, admission: Admission, call: _Call) -> None:
        row = await self._decide(admission, call)
        await self._write(call, row)  # write-ahead: nothing has changed yet
        try:
            await self._remove(row)
            await self._mark(row.id, call.who.user_id)
        except OpsUnavailable:
            await self._write(call, row, _UNAVAILABLE)  # the second record: the row is unmarked
            raise
        if self._freshness is not None:  # within its own budget, and it never raises
            await self._freshness.recompute(row)

    async def _decide(self, admission: Admission, call: _Call) -> port.BackupRow:
        """The row read again under the lock, once no conflict refuses it."""
        row: port.BackupRow | None = None
        try:
            row = await self._read(self._store.get(call.backup_id))
            rule = None if row is None else await self._conflict(admission, row)
        except OpsUnavailable:
            await self._write(call, row, _UNAVAILABLE)
            raise
        if row is None or rule is not None:
            refused: DeleteRule = rule or "not_found"  # `None`: a row gone since the route read it
            await self._write(call, row, refused)
            raise DeleteRefused(refused)
        return row

    async def _conflict(self, admission: Admission, row: port.BackupRow) -> DeleteRule | None:
        if row.deleted_at is not None:
            return "backup_deleted"
        try:
            admission.check()  # a delete's one refusal: a job on this backup
        except BackupConflict:
            return "backup_in_use"
        if row.status == "running":
            return "backup_in_use"
        if port.counts_as_usable(row) and await self._read(self._store.usable_count(row.kind)) < 2:
            return "last_usable_backup"  # the kind's last verified, undeleted backup (Q4)
        return None

    async def _read(self, pending: Awaitable[_T]) -> _T:
        """A catalogue read within its budget: an outage or a read past it is `OpsUnavailable`,
        the class logged; a statement the store refuses stays a bug (the app's 500)."""
        try:
            async with asyncio.timeout(self._read_budget_s):
                return await pending
        except (TimeoutError, StorageTierUnavailable) as exc:
            failure = type(exc).__name__
        _log().warning("admin_backups.delete_read_failed", error=failure,
                       request_id=current_request_id())  # fmt: skip
        raise OpsUnavailable("backups: store unavailable")

    async def _remove(self, row: port.BackupRow) -> None:
        try:
            async with asyncio.timeout(self._remove_budget_s):
                await self._remover.remove(row.id, row.target_path)  # the row's own location
        except Exception as exc:  # the engine's failure, or its budget spent
            failure = type(exc).__name__
        else:
            return
        _log().error("admin_backups.artefact_not_removed", backup_id=str(row.id), error=failure,
                     request_id=current_request_id())  # fmt: skip
        raise OpsUnavailable("backups: store unavailable")

    async def _mark(self, backup_id: UUID, by: UUID) -> None:
        """`deleted_at` and `deleted_by`, `WRITE_TRIES` times at most: a try after a commit lost on
        the way back matches no row (`deleted_at IS NULL`) and changes nothing. With the artefact
        gone, any failure, a refused statement too, ends in the second record and a 503 (C-2.9)."""
        at = self._now()
        for attempt in range(1, limits.WRITE_TRIES + 1):
            try:
                async with asyncio.timeout(self._mark_budget_s):
                    await self._store.mark_deleted(backup_id, by=by, at=at)
            except Exception as exc:  # an outage, a stall, or a statement refused
                _log().error("admin_backups.delete_not_marked", backup_id=str(backup_id),
                             attempt=attempt, error=type(exc).__name__,
                             request_id=current_request_id())  # fmt: skip
                continue
            return
        raise OpsUnavailable("backups: store unavailable")

    async def _write(
        self, call: _Call, row: port.BackupRow | None, reason: str | None = None
    ) -> None:
        status = None if row is None else row.status
        entry = DeleteRecord(call.backup_id, call.challenge_id, status, reason)
        try:
            async with asyncio.timeout(self._record_budget_s):
                await call.write_ahead(entry)
        except Exception as exc:  # a record that is not durable refuses the answer (C-2.9)
            _log().error("admin_backups.delete_audit_failed", error=type(exc).__name__,
                         request_id=current_request_id())  # fmt: skip
            raise OpsAuditUnavailable("backups: the record could not be written") from None
