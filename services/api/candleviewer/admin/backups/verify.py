"""Backup verifications (E42-T05 #966 BK-9): `verifyBackup`, digest first. The engine executes and
this records (#966 Q1): its `ScratchVerifier` restores into scratch; all else is here.

`start`, in the plan's order: unwired, `OpsNotWired` (501); unknown, `None` (404); `running`,
deleted or `encrypted: false`, `VerifyNotUsable` (409 `backup_not_usable`); `VERIFIES_PER_HOUR`
spent, `VerifiesLimited` (429). Under the admission lock (a wait past its bound is 503, before any
record) the limit and the row are read again, then a running verification or restore is
`BackupConflict` (409). The caller's `write_ahead` writes `backup.verified` `stage: requested`
(unwritten: `OpsAuditUnavailable`, 503); the start counts; the `backup_verify` job starts (one the
job store refuses ends `internal_error`, 503).

The job checks within its deadline less `OUTCOME_MARGIN_S` (past it, `internal_error`): no bound
`backup.run` record is `checksum_unbound`; with a digest on the row or in the record, the file is
resolved in the backup root within `VERIFY_RESOLVE_BUDGET_S` (`artefact_missing`), hashed and
compared in constant time with both (`checksum_mismatch`); only then the engine verifies that same
open file, or the location of a directory or a repository (Q8): its every failure but the
environment's is `verify_failed` (SR-CD2-02). An unreadable store or trail is `store_unavailable`,
any other failure of this module's own steps `internal_error`. Every path closes the artefact.

The outcome is written in the job (the job store fixes its status before `on_done`), under
`BackupJobGate.serialized()` for up to `OUTCOME_WAIT_S` (SR-BK3-01): the `finished` record first
(C-2.9), then, for a pass or a conclusive failure, the row and the freshness. An inconclusive end,
a lock wait past its bound (`store_unavailable`, recorded with the check's result as `check`) or an
unwritten record (`audit_unavailable`) leaves the row; an outcome the row did not take (tried
`WRITE_TRIES` times) ends `store_unavailable`. If the gate's deadline cuts the check short, its
`on_done` records the end. Failures count by reason. A record that names a `checksum_mismatch`
(its code, or the check it kept) is severity `error`, possible tampering; any other failure is a
warning (the coordinator's decision 12). The freshness is contained and bounded: its failure never
changes the end. A shutdown cancels the job where it stands, so a `requested` record may have no
`finished` one, or a `finished` record no row write followed."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Final, cast, get_args
from uuid import UUID, uuid4

import structlog

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.artefact_port import ArtefactReader, OpenArtefact
from candleviewer.admin.backups.catalogue import READ_BUDGET_S, BackupCatalogue
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.metrics import count_verify_failure
from candleviewer.admin.backups.ports import (
    CONCLUSIVE,
    BackupJobError,
    Freshness,
    JobEnd,
    JobRunner,
    Outcomes,
    Progress,
    RunRecords,
    ScratchVerifier,
)
from candleviewer.admin.backups.rows import Actor, RunAudit, recorded, run_record
from candleviewer.admin.backups.runs import StartLimit
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import Severity
from candleviewer.storage.backup_artefacts import ArtefactMissing, ArtefactUnreadable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import backups as port

WriteAhead = Callable[[UUID, UUID], Awaitable[None]]  # (backup, job): the `requested` record
Outcome = tuple[port.VerifyMethod, port.BackupErrorCode | None]  # `(method, None)` is a pass
_CHECKED: Final = "checksum"  # a failure's method: the store keeps the last pass's
_METHODS: Final = frozenset(get_args(port.VerifyMethod))
_UNRECORDED: Final = "backups.verify_unrecorded"  # `rows.recorded`'s log event for these records


def _log() -> structlog.stdlib.BoundLogger:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class VerifyNotUsable(AdminError):
    """409 `conflict`, rule `backup_not_usable`: nothing written."""


class VerifiesLimited(AdminError):
    """429 `rate_limited`: the caller started `VERIFIES_PER_HOUR` verifications in the hour."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__("backups: the hourly verification limit is spent")
        self.retry_after_s = retry_after_s


def _actor(who: AuditPrincipal) -> Actor:
    return {
        "actor_label": who.username, "actor_user_id": who.user_id, "actor_ip": who.ip,
        "session_id": who.session_id, "request_id": who.request_id,
    }  # fmt: skip


def _same(actual: bytes, expected: str | None) -> bool:
    """Constant time (`hmac.compare_digest`); no expected digest matches nothing."""
    return expected is not None and hmac.compare_digest(actual, expected.encode())


def _failed(step: str, exc: Exception) -> Outcome:
    """Inconclusive: an unreadable store, trail or volume, else `internal_error`; class only."""
    _log().warning("backups.verify_check_failed", step=step, error=type(exc).__name__)
    unread = isinstance(exc, ArtefactUnreadable | StorageTierUnavailable | TimeoutError)
    return _CHECKED, "store_unavailable" if unread else "internal_error"


class BackupVerifications:
    def __init__(
        self, catalogue: BackupCatalogue, store: Outcomes | None, verifier: ScratchVerifier | None,
        reader: ArtefactReader | None, *, evidence: RunRecords, gate: BackupJobGate,
        jobs: JobRunner, audit: RunAudit, limit: StartLimit, freshness: Freshness | None = None,
        now: Callable[[], datetime] = utc_now, new_id: Callable[[], UUID] = uuid4,
        check_s: float = limits.JOB_DEADLINE_S["backup_verify"] - limits.OUTCOME_MARGIN_S,
    ) -> None:  # fmt: skip
        self._catalogue, self._store, self._verifier = catalogue, store, verifier
        self._reader, self._evidence, self._gate, self._jobs = reader, evidence, gate, jobs
        self._audit, self._limit, self._freshness, self._now = audit, limit, freshness, now
        self._new_id, self._check_s = new_id, check_s

    async def start(
        self, who: AuditPrincipal, backup_id: UUID, *, write_ahead: WriteAhead
    ) -> UUID | None:
        """The verification's job id, or `None` for an unknown backup."""
        store, verifier, reader = self._store, self._verifier, self._reader
        if store is None or verifier is None or reader is None:
            raise OpsNotWired("backups: no verifier wired")
        user, actor = str(who.user_id), _actor(who)
        if await self._usable(backup_id) is None:
            return None
        self._limited(user)  # a spent limit never waits for the lock
        async with self._gate.admit("backup_verify", backup_id) as admission:
            self._limited(user)
            row = await self._usable(backup_id)
            if row is None:
                return None
            admission.check()
            job_id = self._new_id()
            requested = write_ahead(backup_id, job_id)
            if not await recorded(requested, "requested", backup_id, _UNRECORDED):
                raise OpsAuditUnavailable("backups: the record could not be written; nothing ran")
            self._limit.record_start(user)

            concluding: list[bool] = []  # from here on, the job writes its own end

            async def work(progress: Progress) -> dict[str, object]:
                try:
                    async with asyncio.timeout(self._check_s):
                        method, error = await self._check(row, verifier, reader, progress)
                except TimeoutError:  # past its own deadline: inconclusive, and still recorded
                    method, error = _CHECKED, "internal_error"
                concluding.append(True)
                await self._conclude(store, actor, row, job_id, (method, error))
                return {"backup_id": str(backup_id), "verify_method": method}

            async def done(end: JobEnd) -> None:  # the gate's deadline cut the check short
                if not concluding:  # its end, `internal_error` (the job store's), recorded now
                    await self._end(store, actor, row, job_id, (_CHECKED, "internal_error"))
                    count_verify_failure("internal_error")

            try:
                admission.submit(self._jobs, job_id, work, done)
            except Exception as exc:  # the job store refused it: the request ends, under the lock
                failure = {"backup_id": str(backup_id), "error": type(exc).__name__}
                _log().error("backups.verify_not_submitted", **failure)
                ended = await self._end(store, actor, row, job_id, (_CHECKED, "internal_error"))
                count_verify_failure(ended or "internal_error")
                raise OpsUnavailable("backups: the verification could not start") from None
        return job_id

    async def audit_requested(self, who: AuditPrincipal, backup_id: UUID, job_id: UUID) -> None:
        """Verification `job_id`'s `requested` record, for a `write_ahead`."""
        state: dict[str, object] = {"stage": "requested", "job_id": str(job_id)}
        await self._audit.emit("backup.verified", **run_record(_actor(who), backup_id, state, None))

    def _limited(self, user: str) -> None:
        wait = self._limit.retry_after(user)
        if wait is not None:
            raise VerifiesLimited(wait)

    async def _usable(self, backup_id: UUID) -> port.BackupRow | None:
        row = await self._catalogue.get(backup_id)  # within the catalogue's own read budget
        if row is not None and (row.status == "running" or row.deleted_at or not row.encrypted):
            raise VerifyNotUsable("backups: the backup is not usable")
        return row

    async def _check(
        self, row: port.BackupRow, verifier: ScratchVerifier, reader: ArtefactReader, p: Progress
    ) -> Outcome:
        """Digest first (Q7): the verifier runs only once both digests match the file hashed."""
        try:
            async with asyncio.timeout(limits.EVIDENCE_BUDGET_S):
                bound = await self._evidence.run_record(row.id)
        except Exception as exc:
            return _failed("evidence", exc)
        if bound is None:
            return _CHECKED, "checksum_unbound"
        if row.checksum_sha256 is None and bound.digest is None:  # a directory or a repository
            return await self._scratch(row, verifier, None, p)
        try:
            async with asyncio.timeout(limits.VERIFY_RESOLVE_BUDGET_S):  # its own, not the link's
                artefact = await reader.resolve(row.target_path)
        except ArtefactMissing:
            return _CHECKED, "artefact_missing"
        except Exception as exc:  # a cancelled walk closes its file
            return _failed("resolve", exc)
        try:
            digest = (await artefact.digest()).encode()
            # `&`, not `and`: both comparisons always run (constant time, whichever differs)
            if not _same(digest, row.checksum_sha256) & _same(digest, bound.digest):
                return _CHECKED, "checksum_mismatch"  # the verifier never sees it
            return await self._scratch(row, verifier, artefact, p)
        except Exception as exc:
            return _failed("digest", exc)
        finally:
            artefact.close()  # every path, a cancel included; once is enough

    async def _scratch(
        self, row: port.BackupRow, verifier: ScratchVerifier, f: OpenArtefact | None, p: Progress
    ) -> Outcome:
        try:
            method = await verifier.verify(row.id, row.target_path, f, p)
        except Exception as exc:  # SR-CD2-02: a content failure, unless the environment's
            unread = _failed("verify", exc)[1] == "store_unavailable"  # logged by class
            if unread or (isinstance(exc, BackupJobError) and exc.code == "store_unavailable"):
                return _CHECKED, "store_unavailable"  # the environment's fault: inconclusive
            return _CHECKED, "verify_failed"
        return (method, None) if method in _METHODS else (_CHECKED, "verify_failed")

    async def _conclude(
        self, store: Outcomes, actor: Actor, row: port.BackupRow, job_id: UUID, outcome: Outcome
    ) -> None:
        """The outcome under the lock (`OUTCOME_WAIT_S`); a failure raises its code, counted."""
        try:
            async with self._gate.serialized(limits.OUTCOME_WAIT_S):
                error = await self._end(store, actor, row, job_id, outcome)
        except OpsUnavailable:  # its wait spent: inconclusive, the row untouched, the check kept
            lost: Outcome = (_CHECKED, "store_unavailable")
            error = await self._end(store, actor, row, job_id, lost, kept=outcome)
        if error is not None:
            count_verify_failure(error)
            raise BackupJobError(error)

    async def _end(
        self,
        store: Outcomes,
        actor: Actor,
        row: port.BackupRow,
        job_id: UUID,
        outcome: Outcome,
        kept: Outcome | None = None,
    ) -> port.BackupErrorCode | None:
        """The `finished` record (with the check's own result, `kept`, when the outcome could not
        be written); for a pass or a conclusive failure then the row, tried `WRITE_TRIES` times,
        and the freshness. The job's error, `None` for a pass the row took."""
        method, error = outcome
        state: dict[str, object] = {"stage": "finished", "job_id": str(job_id), "error": error}
        if error is None:
            state["verify_method"] = method
        if kept is not None:
            state["check"] = kept[1]  # the check's code, `None` for a pass
        fields = run_record(actor, row.id, state, error)
        if "checksum_mismatch" in (error, state.get("check")):  # possible tampering: decision 12
            fields["severity"] = Severity.ERROR
        record = self._audit.emit("backup.verified", **fields)
        if not await recorded(record, "finished", row.id, _UNRECORDED):
            return "audit_unavailable"  # write-ahead: the row stays as it was
        if error is not None and error not in CONCLUSIVE:
            return error
        at, marked = self._now(), None
        for attempt in range(1, limits.WRITE_TRIES + 1):  # guarded, so a retry is safe
            try:
                async with asyncio.timeout(limits.WRITE_BUDGET_S):
                    marked = await store.record_verify_outcome(
                        row.id, method=method, at=at, error=error
                    )
                break
            except Exception as exc:  # the record stands; only the row is tried again
                where = {"backup_id": str(row.id), "attempt": attempt}
                _log().error("backups.verify_not_marked", **where, error=type(exc).__name__)
        if marked is None:
            return "store_unavailable"  # a record no row followed: the row is the truth
        if self._freshness is not None:  # contained and bounded under the lock: never the end
            with contextlib.suppress(Exception):
                async with asyncio.timeout(READ_BUDGET_S):
                    if error is None:
                        self._freshness.record_success(marked)  # synchronous, in memory
                    else:
                        await self._freshness.recompute(marked)
        return error
