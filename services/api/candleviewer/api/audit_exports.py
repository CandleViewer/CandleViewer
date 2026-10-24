"""The `audit_export` jobs and their files (#889 S9 and S10, ADR-0039; 22 `exportAuditLog`): the
job `exportAuditLog` schedules, and which file `downloadAuditExport` may serve, and how.

A job (S10) runs `AuditQueryService.export` with the injected `ExportSigning`, M2's signer and key
directory as `admin.wiring` mints them, and holds the signed file's manifest (`AuditExportResult`)
once the completion's `admin.audit_export` is written; else the file is removed and the job fails
`audit_unavailable` (`internal_error` for a manifest that does not validate). A failed job's
completion names its code. One export is queued or running at
a time, none while a rotation runs (`reserve`), and only its `202` is kept under its key.

A file is served only for a succeeded `audit_export` job, to the user who requested it, by the name
`write_export` gave it (`export_name`, from the job's id), opened in `<data dir>/audit-exports/`
through the backup artefact reader (`storage/backup_artefacts.py`): from `/`, one `O_NOFOLLOW`
component at a time, a regular file with one link on the directory's device, and here also of the
size its manifest (`AuditExportResult`) states. It expires at the manifest's `expires_at`, and never
later than `audit_export_ttl_s` after its job finished; the download that finds it expired deletes
it.

The sweep (C-2.18: one supervised task) runs at boot, after the hard-link probe, then every
`SWEEP_INTERVAL_S`, each run within `SWEEP_BUDGET_S`, the probe first while it has not passed. It
lists the directory, then deletes every export file and temporary name no job of the store needs:
a queued or running export keeps both of its names, a succeeded one its file until it expires.
Jobs live in memory (ADR-0004), so at boot it deletes them all.
"""

from __future__ import annotations

import asyncio
import base64
import errno
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol

import structlog
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from candleviewer.admin.backups.limits import STREAM_READ_BUDGET_S
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.admin_backup_download import DownloadAborted
from candleviewer.api.audit_verify import write_verify_record
from candleviewer.api.idempotency import IdempotencyKeyReuse
from candleviewer.api.recorder_admin import (
    AUDIT_EXPORT,
    AdminJobStore,
    Job,
    JobConflict,
    requester_key,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.export import (
    EXPORT_DIR,
    export_files,
    export_name,
    links_work,
    remove_exports,
)
from candleviewer.audit.export_job import (
    ExportJobFailed,
    ExportRequest,
    ExportSettings,
    SignedExport,
)
from candleviewer.audit.export_signing import Signer, SigningKeyDirectory
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.context import run_in_thread, spawn
from candleviewer.settings import Environment
from candleviewer.storage.backup_artefacts import (
    ArtefactError,
    ArtefactUnreadable,
    LocalArtefactStore,
    ResolvedArtefact,
)

SWEEP_INTERVAL_S: Final = 60.0
SWEEP_BUDGET_S: Final = 30.0  #: a wedged volume holds neither the boot nor a tick past it
#: 22 `AuditExportResult.download_url`: `downloadAuditExport`, under the API's base path.
DOWNLOAD_PATH: Final = "/api/v1/admin/audit/exports/{job_id}"
#: The record of an export's request, its completion and each download (22 **Audit**).
EXPORT_ACTION: Final = "admin.audit_export"
#: How an export's `Idempotency-Key` is held in the job store, apart from any other job's.
_KEYED: Final = "exportAuditLog:{key}"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ExportRunner(Protocol):
    """What an export job runs: `AuditQueryService.export` (M19), over its own repository."""

    async def export(
        self,
        request: ExportRequest,
        signer: Signer,
        keys: SigningKeyDirectory,
        *,
        job_id: uuid.UUID,
        owner: uuid.UUID,
        settings: ExportSettings,
    ) -> SignedExport: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportSigning:
    """An export job's injected parts (#889 S10, ADR-0039 decision 3): M2's signer and key
    directory, `audit`'s ports as `admin.wiring` mints them, for the job alone; the running
    rotation's read, M2's too; and the process environment and caps the file is written under."""

    signer: Signer
    keys: SigningKeyDirectory
    rotating: Callable[[], bool]
    environment: Environment
    max_rows: int
    max_bytes: int


@dataclass(frozen=True, slots=True)
class Export:
    """A succeeded export as its download sees it: its file's name, its manifest, and when the
    file expires."""

    name: str
    manifest: api.AuditExportResult
    expires_at: datetime


class AuditExports:
    """The export files of `jobs` in `<data_dir>/audit-exports/` (see the module docstring)."""

    def __init__(
        self,
        jobs: AdminJobStore,
        data_dir: Path,
        *,
        ttl_s: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        signing: ExportSigning | None = None,
    ) -> None:
        self._jobs, self._dir, self._ttl = jobs, data_dir / EXPORT_DIR, timedelta(seconds=ttl_s)
        self._root, self._clock, self._sleep, self._signing = data_dir, clock, sleep, signing
        self._files = LocalArtefactStore(str(self._dir))
        self._task: asyncio.Task[None] | None = None
        #: The probe's answer: false until it passed, and an export is refused while false (S10).
        self.links_ok = False
        self._probe_failing = False  #: a failure repeated is logged at warning, not critical

    async def unavailable(self) -> str | None:
        """Why export alone is unavailable, as its refusal is recorded (22 `503
        signing_unavailable`): `signing_unavailable` with no signing wired or no key the directory
        names, which opens no seed; `export_volume_unavailable` while the directory takes no hard
        links. None while export is available."""
        if self._signing is None or await self._signing.keys.active() is None:
            return "signing_unavailable"
        return None if self.links_ok else "export_volume_unavailable"

    def replayed(self, actor: str, key: uuid.UUID | None, digest: str) -> str | None:
        """The job of `actor`'s export with the same `Idempotency-Key` and request, whose `202` is
        answered again (22: only the `202` is kept); `IdempotencyKeyReuse` for another request."""
        found = (
            None if key is None else self._jobs.by_idempotency_key(actor, _KEYED.format(key=key))
        )
        if found is None:
            return None
        if found[1] != digest:
            raise IdempotencyKeyReuse(str(key))
        return found[0].id

    def reserve(self) -> Callable[[], None]:
        """22's single-flight before the request's record: one export queued or running, and none
        while a rotation runs; the job store's hold, else `JobConflict`."""
        if self._signing is not None and self._signing.rotating():
            raise JobConflict(AUDIT_EXPORT)
        return self._jobs.reserve(AUDIT_EXPORT)

    def submit(
        self,
        runner: ExportRunner,
        emit: Callable[..., Awaitable[None]],
        fields: dict[str, Any],
        principal: AuditPrincipal,
        request: ExportRequest,
        *,
        job_id: uuid.UUID,
        key: uuid.UUID | None,
        digest: str,
    ) -> Job:
        """`principal`'s export job, once its request is recorded under `fields`, with no `await`
        since its hold was released: its result is the manifest once the completion is written."""
        signing = self._signing
        if signing is None:  # `unavailable()` refused it first
            raise JobConflict(AUDIT_EXPORT)
        settings = ExportSettings(
            environment=signing.environment, data_dir=self._root, max_rows=signing.max_rows,
            max_bytes=signing.max_bytes,
        )  # fmt: skip

        async def record(outcome: AuditOutcome, reason: str, state: dict[str, Any]) -> bool:
            severity = Severity.INFO if outcome is _SUCCESS else Severity.WARNING
            return await write_verify_record(
                emit, fields, outcome=outcome, severity=severity, reason=reason, after_state=state,
                action=EXPORT_ACTION,
            )  # fmt: skip

        async def work(_progress: Callable[[float], None]) -> dict[str, object]:
            signed = await runner.export(
                request, signing.signer, signing.keys, job_id=job_id, owner=principal.actor_id,
                settings=settings,
            )  # fmt: skip
            code = "audit_unavailable"
            try:
                manifest = self._manifest(job_id, signed)
                if await record(_SUCCESS, "completed", _completed(job_id, signed)):
                    return manifest
            except Exception as exc:  # a manifest that does not validate, or any defect: unserved
                _log().error("audit.export.manifest_invalid", error=type(exc).__name__)
                code = "internal_error"
            await self._file_step(remove_exports, self._dir, [signed.file.name])
            raise ExportJobFailed(code)  # nothing is served without its manifest and its record

        async def ended(job: Job) -> None:
            if job.status == "failed":
                await record(
                    _FAILURE, "failed", export_window(job_id, request) | {"error": job.error}
                )

        keyed = _KEYED.format(key=key if key is not None else f"none:{job_id}")
        held = (str(principal.actor_id), keyed, digest)
        return self._jobs.submit(
            AUDIT_EXPORT, held, work, ended, job_id=str(job_id), requester=requester_key(principal)
        )

    def _manifest(self, job_id: uuid.UUID, signed: SignedExport) -> dict[str, object]:
        """22's `AuditExportResult`, validated: the download, the file's digest and size, the
        signature and the header's key, the window and the span, and `expires_at`, the TTL from
        now, never later than the job's end plus the TTL (S9-1b)."""
        plan, file = signed.plan, signed.file
        result = {
            "download_url": DOWNLOAD_PATH.format(job_id=job_id), "sha256": file.sha256,
            "signature": base64.b64encode(signed.signature).decode("ascii"),
            "signature_alg": "ed25519", "key_id": plan.key_id, "public_key": plan.public_key,
            "compressed": plan.compressed, "size_bytes": file.size_bytes,
            "row_count": file.row_count, "from": plan.from_ts, "to": plan.to_ts,
            "first_id": file.first_id, "last_id": file.last_id,
            "expires_at": self._clock() + self._ttl,
        }  # fmt: skip
        dumped: dict[str, object] = api.AuditExportResult.model_validate(result).model_dump(
            mode="json", by_alias=True
        )
        return dumped

    def find(self, job_id: str, principal: AuditPrincipal) -> Export | None:
        """`principal`'s succeeded export `job_id`, else None: unknown or evicted, another user's
        (`Job.hidden_from`), not succeeded, or with no manifest."""
        job = self._jobs.get(job_id)
        return None if job is None or job.hidden_from(principal) else self._export(job)

    def expired(self, export: Export) -> bool:
        """From `expires_at` on, which 22 says is "after" it: the boundary fails closed."""
        return self._clock() >= export.expires_at

    async def open(self, export: Export) -> ResolvedArtefact | str:
        """The file, open for reading, else why it cannot be served (logged): the reader's code
        (`artefact_missing`, `store_unavailable`) or `size_changed`."""
        try:
            file = await self._files.resolve(f"{self._dir}/{export.name}")
        except ArtefactError as exc:
            reason = exc.code
        else:
            if file.size == export.manifest.size_bytes:
                return file
            file.close()
            reason = "size_changed"
        _log().warning("audit.export.unservable", error=reason)
        return reason

    async def remove(self, export: Export) -> None:
        """Delete an expired export's file."""
        await self._file_step(remove_exports, self._dir, [export.name])

    async def sweep(self) -> None:
        """Delete every export file and temporary name no job of the store needs."""
        found = await self._file_step(export_files, self._dir)
        stale = [name for name, job_id in found or () if not self._needs(name, job_id)]
        if stale:
            await self._file_step(remove_exports, self._dir, stale)

    async def run_once(self) -> None:
        """One sweep within `SWEEP_BUDGET_S`; any failure is logged, and the next tick runs."""
        try:
            async with asyncio.timeout(SWEEP_BUDGET_S):
                await self.sweep()
        except Exception as exc:
            _log().warning("audit.export.sweep_failed", error=type(exc).__name__)

    async def start(self) -> None:
        """At boot, before serving: the hard-link probe; a sweep; then a sweep every
        `SWEEP_INTERVAL_S`. A second call starts no second task."""
        await self._probe()
        await self.run_once()
        if self._task is None:
            self._task = spawn(self._loop(), name="audit-export-sweep")

    async def _probe(self) -> None:
        """The hard-link probe within `SWEEP_BUDGET_S`, a failure logged critical, and at warning
        while it keeps failing (export alone degrades, never the boot: ADR-0039 driver 4); at
        boot, then before each sweep until it passes (#889 S10), so a remount recovers with no
        restart."""
        try:
            async with asyncio.timeout(SWEEP_BUDGET_S):
                await run_in_thread(links_work, self._dir)
            self.links_ok, self._probe_failing = True, False
        except Exception as exc:
            code = errno.errorcode.get(getattr(exc, "errno", None) or 0)
            log = _log().warning if self._probe_failing else _log().critical
            log("audit.export.link_probe_failed", error=type(exc).__name__, errno=code)
            self._probe_failing = True

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})

    async def _loop(self) -> None:
        while True:
            await self._sleep(SWEEP_INTERVAL_S)
            if not self.links_ok:
                await self._probe()
            await self.run_once()

    def _needs(self, name: str, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.kind != AUDIT_EXPORT:
            return False
        if job.status in ("queued", "running"):
            return True  # its writer's temporary name and file
        export = self._export(job)
        return export is not None and export.name == name and not self.expired(export)

    def _export(self, job: Job) -> Export | None:
        if job.kind != AUDIT_EXPORT or job.status != "succeeded":
            return None
        try:
            manifest = api.AuditExportResult.model_validate(job.result)
            name = export_name(uuid.UUID(job.id), manifest.compressed)
        except ValueError:  # pydantic's `ValidationError` too: no manifest, no file
            return None
        ended = (job.finished_at or manifest.expires_at) + self._ttl
        return Export(name, manifest, min(manifest.expires_at, ended))

    async def _file_step[T](self, step: Callable[..., T], *args: Any) -> T | None:
        """`step(*args)` in a worker thread; an `OSError` is logged with its errno, never raised."""
        try:
            return await run_in_thread(step, *args)
        except OSError as exc:
            code = errno.errorcode.get(exc.errno or 0)
            _log().error("audit.export.file_step_failed", error=type(exc).__name__, errno=code)
            return None


_SUCCESS, _FAILURE = AuditOutcome.SUCCESS, AuditOutcome.FAILURE


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def export_window(job_id: uuid.UUID, request: ExportRequest) -> dict[str, Any]:
    """What an export's records name of it: its job and its window."""
    return {"job_id": str(job_id), "from": _iso(request.from_ts), "to": _iso(request.to_ts)}


def _completed(job_id: uuid.UUID, signed: SignedExport) -> dict[str, Any]:
    """The completion's members (22 **Audit**): the job, the window, the span, the row count and
    the file's digest, its size and key, so a signature with no completion is a direct join."""
    plan, file = signed.plan, signed.file
    request = ExportRequest(plan.from_ts, plan.to_ts, plan.compressed)
    return export_window(job_id, request) | {
        "first_id": file.first_id, "last_id": file.last_id, "row_count": file.row_count,
        "sha256": file.sha256, "size_bytes": file.size_bytes, "key_id": plan.key_id,
        "compressed": plan.compressed,
    }  # fmt: skip


class ExportFileResponse(StreamingResponse):
    """`downloadAuditExport`'s `200`: the file as an attachment, `application/gzip` when compressed
    and `application/x-ndjson` otherwise, its `Repr-Digest` (RFC 9530) the manifest's SHA-256, which
    the signature covers. As a backup download (`api.admin_backup_download`), it is read one
    worker-thread chunk at a time, each within `STREAM_READ_BUDGET_S`, cut when a read stalls or
    fails or the bytes sent are not the file's size, and closed whether or not its stream starts."""

    def __init__(self, export: Export, file: ResolvedArtefact) -> None:
        self._file = file
        digest = base64.b64encode(bytes.fromhex(export.manifest.sha256)).decode()
        headers = {
            "Content-Disposition": f'attachment; filename="{export.name}"',
            "Content-Length": str(file.size),
            "Repr-Digest": f"sha-256=:{digest}:",
            "X-Content-Type-Options": "nosniff",
        }
        media = "application/gzip" if export.manifest.compressed else "application/x-ndjson"
        super().__init__(self._chunks(), headers=headers, media_type=media)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._file.close()

    async def _chunks(self) -> AsyncIterator[bytes]:
        sent, reads = 0, self._file.stream()
        try:
            while True:
                async with asyncio.timeout(STREAM_READ_BUDGET_S):
                    chunk = await anext(reads, None)
                if chunk is None:
                    break
                sent += len(chunk)
                yield chunk
        except (TimeoutError, ValueError, ArtefactUnreadable) as exc:  # stalled, closed, failed
            failure = type(exc).__name__
        else:
            if sent == self._file.size:
                return
            failure = "size_changed"
        _log().warning("audit.export.download_aborted", error=failure)
        raise DownloadAborted("audit: the export download was aborted")
