"""`GET /admin/jobs/{jobId}` (`getJob`, `admin:read`): every `202` job's poll, on the audited admin
router (E42-T01), so every poll is recorded (`admin.area_entered`) and a refused one counted, like
any admin route (#966 Q15, AD-F22); its `501` and `503` are the guard's. Jobs live in process
memory (ADR-0004): every `404` is one body, rule `job_unknown`, never issued, evicted or lost on
a restart alike (#966 Q10), and `LostJobsCount` counts what a restart loses."""

from __future__ import annotations

import os
import pathlib
import stat
from typing import Annotated, Any, Final

import structlog
from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.auth.generated_permissions import Permission
from candleviewer.observability.context import run_in_thread
from candleviewer.observability.metrics import MetricChild
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_JOB_UNKNOWN: Final[dict[str, Any]] = {  # 22-api-openapi.yaml `getJob` 404 `jobUnknown`
    "type": f"https://candleviewer.local/errors/{ErrorCode.NOT_FOUND.value}",
    "title": ERROR_META[ErrorCode.NOT_FOUND].title,
    "status": 404,
    "code": ErrorCode.NOT_FOUND.value,
    "detail": "No job with this id.",
    "errors": [{"field": "jobId", "rule": "job_unknown", "message": "the job is unknown"}],
}
#: The count is read without waiting on, following or adopting what is planted at its path (a FIFO
#: with no writer would block the boot, SEC-BK7b-01): a final symlink fails the open, a FIFO does
#: not block it, a terminal cannot become the controlling one, and the descriptor does not outlive
#: an exec.
_READ_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
_READ_MAX: Final = 17  # the longest count the file may hold (16 digits), and one byte more
#: The save's temporary file is opened without following a symlink and without waiting for a reader:
#: a FIFO planted at its name would hold the clean stop (SEC-BK7bFU-01).
_WRITE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_NONBLOCK


def make_admin_jobs_router(
    jobs: AdminJobStore, *, resolver: PrincipalResolver | None, audit: AuditEmitter | None
) -> APIRouter:
    router = admin_router(Permission.ADMIN_READ, resolver=resolver, audit=audit)

    @router.get("/jobs/{jobId}")
    async def get_job(job_id: Annotated[str, Path(alias="jobId")]) -> JSONResponse:
        job = jobs.get(job_id)
        # An `audit_export` job is its requester's alone, and `Job` records no requester: unknown
        # until E42-T02 records one and checks it here (fail closed, SR-BK7-03).
        if job is None or job.kind == "audit_export":
            return JSONResponse(_JOB_UNKNOWN, 404, media_type="application/problem+json")
        return JSONResponse(job.view())  # the shape the recorder jobs were always polled in

    return router


class LostJobsCount:
    """`cv_admin_jobs_lost_on_restart_total` (#966 Q10, SR-BK7-02). A counter in the process that
    stops is never scraped, so the next process counts. At a clean stop, once the job store has
    stopped, `save` writes how many jobs it holds, finished ones included (a restart loses every
    one): one integer in `<data dir>/admin-jobs/lost-on-restart` (`Settings.data_dir`), written to
    a temporary file, synced, then renamed over. At boot, `load` reads it, removes it, then adds it
    to the counter, so a crash in between under-counts and never double-counts. A crash skips
    `save`, so its jobs are not counted. A file or a link that cannot be read, or holds anything
    but a count (one to 16 digits), adds 0, is logged and removed. Anything else there (a FIFO, a
    socket, a directory) adds 0, is logged and left: it is never read and never waited on. The
    save never waits either: a FIFO at its temporary file fails it, and the stop goes on."""

    def __init__(self, data_dir: pathlib.Path, jobs: AdminJobStore, counter: MetricChild) -> None:
        self._path, self._jobs = data_dir / "admin-jobs" / "lost-on-restart", jobs
        self._counter = counter

    async def save(self) -> None:
        await run_in_thread(_write_count, self._path, self._jobs.held())

    async def load(self) -> None:
        self._counter.inc(await run_in_thread(_take_count, self._path))


def _write_count(path: pathlib.Path, held: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    fd = os.open(temporary, _WRITE_FLAGS, 0o600)
    try:
        os.write(fd, str(held).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def _take_count(path: pathlib.Path) -> int:
    raw, failure, removable = b"", "malformed", True
    try:
        fd = os.open(path, _READ_FLAGS)
        try:
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raw = os.read(fd, _READ_MAX)
            else:  # a FIFO, a device or a directory: never read, never removed
                failure, removable = "not_regular", False
        finally:
            os.close(fd)
    except FileNotFoundError:
        return 0  # no clean stop since the last boot counted: a first boot, or a crash
    except OSError as exc:
        failure, removable = type(exc).__name__, _is_file_or_link(path)  # a socket stays
    if removable:
        try:
            path.unlink()
        except OSError as exc:  # left in place it would be counted again: count nothing
            raw, failure = b"", type(exc).__name__
    if raw.isdigit() and len(raw) < _READ_MAX:  # a longer file is not a count, not its first digits
        return int(raw)
    structlog.get_logger(__name__).warning("admin_jobs.lost_count_unreadable", error=failure)
    return 0


def _is_file_or_link(path: pathlib.Path) -> bool:
    """Only a regular file or a link (never followed) is ours to remove."""
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) or stat.S_ISLNK(mode)
