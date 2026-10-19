"""`restoreBackup`'s preconditions (E42-T05 #966 BK-13), in the backup service so every caller
inherits them; no route until BK-14, after D7 (#3084). `RestoreGuard.admit` holds the backups
admission lock from its first check through the job's submit, and checks in the contract's order:

1. maintenance mode: `False` refuses `maintenance_mode_required`; `None`, a non-bool, a failure or a
   read past its bound is 503 `store_unavailable`, never "on";
2. `admission.check()`: a run, a verification (Q6) or a restore running refuses
   `backup_or_restore_running`;
3. a usable backup: the row `ok`, `verified` or `restored`, kept, `encrypted`, its digest equal to
   the one its `backup.run` record bound (Q7); else `backup_not_usable` (BK-9's `AuditRunEvidence`
   adds the record-sourced checks of the threat model's §6 step 3);
4. positions: unknown (`None`, a failure, a read past its bound, a negative count) needs
   `acknowledge_unknown_positions` (`positions_unknown`), more than zero needs
   `acknowledge_open_positions` (`open_positions_unacknowledged`); neither implies the other;
5. #3084's `RevocationsCheck`, required with no default: its rule refuses; unread, 503.

Each read is bounded by `RESTORE_READ_BUDGET_S`, each record by `RESTORE_RECORD_BUDGET_S`
(SR-BK7-01). Every attempt writes `backup.restore` at severity `error` before its answer (C-2.9),
naming the spent grant's `challenge_id`, the components and both acknowledgements: a refusal with
its rule (or `store_unavailable`) as `reason`, an acceptance with the operator's `reason` and the
job id, ahead of the job; unwritten, 503 `audit_unavailable` and no job. A lock wait past
`ADMIT_WAIT_S` is 503 after its failure record (#3695). An attempt without a job, a 503 too, counts
`cv_restore_jobs_total{result="refused"}` (Q17).

The job is the only caller of `RestoreExecutor.restore`, held privately; its result is
`{backup_id}` until #3084 defines one. Its end writes `stage: finished` first, within its bound
(SR-BK7A-02), then counts `succeeded`, `failed` or `cancelled` (the deadline cancelled the
executor, SR-BK7A-04); an unwritten end marks a succeeded job `audit: "unavailable"` (#3674). A
shutdown cancels a job with no end record. The executor holds the trading halt outside the
database it replaces (its port); nothing here lifts it."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hmac import compare_digest
from typing import Final, Protocol, TypeVar
from uuid import UUID, uuid4

import structlog

from candleviewer.admin.backups import limits, ports
from candleviewer.admin.backups.gate import BackupConflict, BackupJobGate, JobAdmission
from candleviewer.admin.backups.metrics import RestoreResult, count_restore
from candleviewer.admin.errors import OpsAuditUnavailable, OpsUnavailable
from candleviewer.admin.http import AuditEmitter
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.storage.repositories.backups import BackupRow

_T = TypeVar("_T")  # not PEP 695 `[T]`: Semgrep 1.99.0 (CI) would skip the rest of this file
USABLE: Final = frozenset({"ok", "verified", "restored"})
_DETAILS: Final = {  # the contract's examples
    "maintenance_mode_required": "Restore requires maintenance mode to be on.",
    "positions_unknown": "The open-position state could not be read; acknowledge it to restore.",
}


@dataclass(frozen=True, slots=True)
class RestoreRequest:
    """`restoreBackup`'s validated body; the route has matched `confirm_backup_id` already."""

    backup_id: UUID
    reason: str
    components: frozenset[ports.Component]
    acknowledge_open_positions: bool = False
    acknowledge_unknown_positions: bool = False


@dataclass(frozen=True, slots=True)
class RestoreAccepted:
    """`202`: the `backup_restore` job started."""

    job_id: UUID


@dataclass(frozen=True, slots=True)
class RestoreRefused:
    """`409`: no job was created, and it is never stored under the `Idempotency-Key`."""

    rule: str
    open_positions: int | None = None

    @property
    def detail(self) -> str | None:
        if self.rule == "open_positions_unacknowledged":
            return f"{self.open_positions} positions are open; acknowledge them to restore."
        return _DETAILS.get(self.rule)


class Spent(Protocol):
    """The one-shot `backups` grant the route spent (`api.step_up.SpentGrant`, #2799)."""

    @property
    def challenge_id(self) -> UUID: ...


class BackupRows(Protocol):
    async def get(self, backup_id: UUID) -> BackupRow | None: ...  # `BackupCatalogue.get`


class RevocationsCheck(Protocol):
    """#3084 (D7): what the owner's restore decision adds, checked last under the lock."""

    async def refusal(self, backup: BackupRow, request: RestoreRequest) -> str | None:
        """`None` admits; anything else is the contract rule the restore is refused with."""


class _Unread(Exception):
    """A precondition that could not be read: 503 `store_unavailable`."""


@dataclass(slots=True)
class _Attempt:
    request: RestoreRequest
    who: AuditPrincipal
    state: dict[str, object]  # every record's `after_state`, as far as the checks got


class RestoreGuard:
    """The one way to `RestoreExecutor.restore` (module docstring)."""

    __slots__ = (
        "_audit", "_evidence", "_executor", "_gate", "_jobs", "_maintenance", "_new_id",
        "_positions", "_revocations", "_rows",
    )  # fmt: skip

    def __init__(
        self,
        executor: ports.RestoreExecutor,
        *,
        revocations: RevocationsCheck,
        gate: BackupJobGate,
        jobs: ports.JobRunner,
        audit: AuditEmitter,
        rows: BackupRows,
        evidence: ports.RunEvidence,
        maintenance: ports.MaintenanceState,
        positions: ports.OpenPositions,
        new_id: Callable[[], UUID] = uuid4,
    ) -> None:
        if revocations is None:  # no default: no guard skips it (#3084)
            raise TypeError("a restore guard needs #3084's revocations check")
        self._executor, self._revocations, self._gate = executor, revocations, gate
        self._jobs, self._audit, self._rows, self._evidence = jobs, audit, rows, evidence
        self._maintenance, self._positions, self._new_id = maintenance, positions, new_id

    async def admit(
        self, request: RestoreRequest, principal: AuditPrincipal, spent: Spent
    ) -> RestoreAccepted | RestoreRefused:
        """The restore's job, or why not, once the route spent `spent`."""
        state: dict[str, object] = {
            "stage": "requested", "challenge_id": str(spent.challenge_id),
            "components": sorted(request.components),
            "acknowledge_open_positions": request.acknowledge_open_positions,
            "acknowledge_unknown_positions": request.acknowledge_unknown_positions,
        }  # fmt: skip
        at, held = _Attempt(request, principal, state), False
        try:
            async with self._gate.admit("backup_restore", request.backup_id) as admission:
                held = True
                try:
                    return await self._checked(admission, at)
                except _Unread:
                    await self._decline(at, "store_unavailable")
                    raise OpsUnavailable("backups: store unavailable") from None
        except OpsUnavailable:
            if not held:  # the lock wait outlasted its bound, after the grant's spend (#3695)
                await self._decline(at, "store_unavailable")
            raise

    async def _checked(
        self, admission: JobAdmission, at: _Attempt
    ) -> RestoreAccepted | RestoreRefused:
        request, read = at.request, self._read
        on = await read(self._maintenance.read, "maintenance")
        if on is False:
            return await self._decline(at, "maintenance_mode_required")
        if on is not True:  # unreadable: never "on"
            raise _Unread
        try:
            admission.check()
        except BackupConflict as running:
            return await self._decline(at, running.rule)
        row = await read(self._rows.get, "row", request.backup_id)
        if row is None or not await self._usable(row, request.backup_id):
            return await self._decline(at, "backup_not_usable")
        try:
            count = await read(self._positions.count_open, "positions")
        except _Unread:
            count = None
        if count is not None and count < 0:
            count = None
        at.state["open_positions"] = count
        if count is None and not request.acknowledge_unknown_positions:
            return await self._decline(at, "positions_unknown")
        if count and not request.acknowledge_open_positions:
            return await self._decline(at, "open_positions_unacknowledged", count)
        rule = await read(self._revocations.refusal, "revocations", row, request)
        if rule is not None:
            return await self._decline(at, rule)
        return await self._start(admission, at, row.target_path)

    async def _usable(self, row: BackupRow, backup_id: UUID) -> bool:
        if row.status not in USABLE or row.deleted_at is not None or not row.encrypted:
            return False
        bound = await self._read(self._evidence.bound_digest, "evidence", backup_id)
        digest = row.checksum_sha256
        if digest is None or bound is None:
            return False
        return compare_digest(digest.encode(), bound.encode())  # bytes: any text, no TypeError

    async def _read(self, read: Callable[..., Awaitable[_T]], what: str, *args: object) -> _T:
        """`read(*args)` within its budget; failing or past it, `_Unread` (its class logged)."""
        try:
            async with asyncio.timeout(limits.RESTORE_READ_BUDGET_S):
                return await read(*args)
        except Exception as exc:
            log = structlog.get_logger(__name__)  # per call, never module-level (#2008)
            log.warning("backups.restore_read_failed", read=what, error=type(exc).__name__)
            raise _Unread from None

    async def _start(self, admission: JobAdmission, at: _Attempt, location: str) -> RestoreAccepted:
        job_id, request, executor = self._new_id(), at.request, self._executor
        at.state["job_id"] = str(job_id)
        try:
            await self._write(at, AuditOutcome.SUCCESS, request.reason)
        except OpsAuditUnavailable:
            count_restore("refused")
            raise
        cancelled: list[bool] = []

        async def work(progress: ports.Progress) -> dict[str, object]:
            try:
                await executor.restore(request.backup_id, location, request.components, progress)
            except asyncio.CancelledError:  # its deadline or a shutdown; trading stays halted
                cancelled.append(True)
                raise
            return {"backup_id": str(request.backup_id)}

        async def done(end: ports.JobEnd) -> None:
            await self._finish(at, "cancelled" if cancelled else end.status, end)

        try:
            admission.submit(self._jobs, job_id, work, done)
        except Exception:  # its record says accepted: end it
            await self._finish(at, "failed", ports.JobEnd("failed", None, "internal_error"))
            raise
        return RestoreAccepted(job_id)

    async def _finish(self, at: _Attempt, result: RestoreResult, end: ports.JobEnd) -> None:
        """A job's end: its `finished` record first, within its bound, then its count."""
        outcome = AuditOutcome.SUCCESS if result == "succeeded" else AuditOutcome.FAILURE
        try:
            await self._write(at, outcome, end.error, stage="finished", result=result)
        except OpsAuditUnavailable:
            if end.result is not None:  # the trail lacks the end: the job says so (#3674)
                end.result["audit"] = "unavailable"
        count_restore(result)

    async def _decline(self, at: _Attempt, rule: str, count: int | None = None) -> RestoreRefused:
        count_restore("refused")
        await self._write(at, AuditOutcome.FAILURE, rule)
        return RestoreRefused(rule, count)

    async def _write(
        self, at: _Attempt, outcome: AuditOutcome, reason: str | None, **state: object
    ) -> None:
        """One `backup.restore` record within its budget; unwritten, `OpsAuditUnavailable`."""
        who = at.who
        try:
            async with asyncio.timeout(limits.RESTORE_RECORD_BUDGET_S):
                await self._audit.emit(
                    "backup.restore", actor_label=who.username, actor_user_id=who.user_id,
                    actor_ip=who.ip, session_id=who.session_id, object_kind="backup",
                    object_id=str(at.request.backup_id), outcome=outcome, severity=Severity.ERROR,
                    reason=reason, after_state=at.state | state, request_id=who.request_id,
                )  # fmt: skip
        except Exception as exc:  # not made durable in time (C-2.9)
            log = structlog.get_logger(__name__)
            log.error("backups.restore_unrecorded", outcome=outcome, error=type(exc).__name__)
            raise OpsAuditUnavailable("backups: the record could not be written") from None
