"""The signed audit export's job (#889 S10; ADR-0039 decisions 1, 3, 4 and 7; 22 `exportAuditLog`).

In order: the active key from the injected `SigningKeyDirectory`, the one source of the key id it
names and signs with (decision 4: the key M2 checked); the span planned as of the chain head when
the job starts (`plan_export`); the file written (`write_export`, #889 S8); then the file's digest
signed through the injected `Signer`, M2's, which writes `security.audit_export_signed` ahead of
the signature and refuses to sign when it cannot (decision 7). A failure leaves as
`ExportJobFailed`, whose `code` is 22's `Job.error`, and removes the file it wrote; a removal that
fails is logged by its errno and left to the sweep, as a job cancelled at shutdown leaves its
file to the boot sweep. Nothing it raises or logs carries a message, a path or key material.
"""

from __future__ import annotations

import base64
import errno
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import structlog

from candleviewer.audit.errors import AuditError
from candleviewer.audit.export import (
    EXPORT_DIR,
    EXPORT_MAX_BYTES,
    EXPORT_MAX_ROWS,
    ExportFile,
    ExportPlan,
    ExportTooLarge,
    remove_exports,
    write_export,
)
from candleviewer.audit.export_signing import (
    SIGNING_FAILURES,
    ExportSigningFailed,
    Signer,
    SigningKey,
    SigningKeyDirectory,
)
from candleviewer.audit.repository import AuditRepository
from candleviewer.observability.context import run_in_thread
from candleviewer.settings import Environment

#: The head and anchor of an empty chain (`audit_chain()`'s genesis).
GENESIS: Final = "0" * 64
#: 22 `Job.error`: every code a failed `audit_export` job carries.
JOB_ERRORS: Final = frozenset({"export_too_large", *SIGNING_FAILURES})


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ExportJobFailed(AuditError):
    """The export job failed with `code`, its `Job.error` (`JOB_ERRORS`)."""

    def __init__(self, code: str) -> None:
        if code not in JOB_ERRORS:
            raise ValueError("not an audit export job error")
        super().__init__(f"the audit export failed ({code})")
        self.code = code


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """What the Owner asked for: the window `[from_ts, to_ts)`, aware, and whether to gzip."""

    from_ts: datetime
    to_ts: datetime
    compressed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportSettings:
    """Where the file goes and how large it may be (22 **Limits**), and the process environment
    the header names."""

    environment: Environment
    data_dir: Path
    max_rows: int = EXPORT_MAX_ROWS
    max_bytes: int = EXPORT_MAX_BYTES


@dataclass(frozen=True, slots=True)
class SignedExport:
    """The job's outcome: what it planned, the file it wrote and the signature over its digest."""

    plan: ExportPlan
    file: ExportFile
    signature: bytes


async def plan_export(
    repo: AuditRepository, request: ExportRequest, *, environment: Environment, key: SigningKey
) -> ExportPlan:
    """The span as of the chain head when the job starts (22 **Content**): its first and last id
    in the window and the first one's `prev_hash`, or an empty span; and `key`, which the header
    names."""
    head = await repo.read_head()
    head_id, head_hash = head if head is not None else (0, GENESIS)
    span = None
    if head is not None:
        window = {"from_ts": request.from_ts, "to_ts": request.to_ts}
        span = await repo.export_span(**window, head_id=head_id)
    first, last, anchor = span if span is not None else (None, None, None)
    return ExportPlan(
        from_ts=request.from_ts, to_ts=request.to_ts, first_id=first, last_id=last,
        anchor_hash=anchor, head_id=head_id, head_hash=head_hash, environment=environment,
        key_id=key.key_id, public_key=base64.b64encode(key.public_key).decode("ascii"),
        compressed=request.compressed,
    )  # fmt: skip


async def run_export(
    repo: AuditRepository,
    signer: Signer,
    keys: SigningKeyDirectory,
    request: ExportRequest,
    *,
    job_id: uuid.UUID,
    owner: uuid.UUID,
    settings: ExportSettings,
) -> SignedExport:
    """The module docstring's steps for `owner`'s export `job_id`; else `ExportJobFailed`."""
    written: ExportFile | None = None
    try:
        key = await keys.active()  # the directory alone names the key (decision 4)
        if key is None:
            raise ExportSigningFailed("signing_unavailable")
        plan = await plan_export(repo, request, environment=settings.environment, key=key)
        written = await write_export(
            plan, repo, data_dir=settings.data_dir, job_id=job_id, max_rows=settings.max_rows,
            max_bytes=settings.max_bytes,
        )  # fmt: skip
        digest = bytes.fromhex(written.sha256)
        signature = await signer.sign_audit_export(key.key_id, digest, job_id, owner)
        return SignedExport(plan, written, signature)
    except ExportSigningFailed as exc:  # before any `AuditError` handler: it is one
        code, error = exc.code, None
    except ExportTooLarge:
        code, error = "export_too_large", None
    except Exception as exc:
        code, error = "internal_error", type(exc).__name__
    _log().warning("audit.export.failed", code=code, error=error)
    if written is not None:
        await _discard(settings.data_dir, written.name)
    raise ExportJobFailed(code)  # outside the handlers: no cause, no context


async def _discard(data_dir: Path, name: str) -> None:
    """A failed job's file, removed: no file is left that no job serves."""
    try:
        await run_in_thread(remove_exports, data_dir / EXPORT_DIR, [name])
    except OSError as exc:
        _log().warning("audit.export.discard_failed", errno=errno.errorcode.get(exc.errno or 0))
