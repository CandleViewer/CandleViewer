"""The files of `audit_export` jobs (#889 S9, ADR-0039; 22 `exportAuditLog`, **Download**): which
one `downloadAuditExport` may serve, and how.

A file is served only for a succeeded `audit_export` job, to the user who requested it, by the name
`write_export` gave it (`export_name`, from the job's id), opened in `<data dir>/audit-exports/`
through the backup artefact reader (`storage/backup_artefacts.py`): from `/`, one `O_NOFOLLOW`
component at a time, a regular file with one link on the directory's device, and here also of the
size its manifest (`AuditExportResult`) states. It expires at the manifest's `expires_at`, and never
later than `audit_export_ttl_s` after its job finished; the download that finds it expired deletes
it.
"""

from __future__ import annotations

import asyncio
import base64
import errno
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from candleviewer.admin.backups.limits import STREAM_READ_BUDGET_S
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.admin_backup_download import DownloadAborted
from candleviewer.api.recorder_admin import AUDIT_EXPORT, AdminJobStore, Job
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.export import EXPORT_DIR, export_name, remove_exports
from candleviewer.observability.context import run_in_thread
from candleviewer.storage.backup_artefacts import (
    ArtefactError,
    ArtefactUnreadable,
    LocalArtefactStore,
    ResolvedArtefact,
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


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
    ) -> None:
        self._jobs, self._dir, self._ttl = jobs, data_dir / EXPORT_DIR, timedelta(seconds=ttl_s)
        self._clock = clock
        self._files = LocalArtefactStore(str(self._dir))

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
