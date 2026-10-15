"""`POST /admin/recorder/purge` (E16-T06): irreversible, owner-only, step-up, audited.

Order is a safety property: session -> RBAC (`recording:write`, then owner-only capability 9a,
before the body is read) ->
step-up (`recorder` class, server-side elevation) -> Idempotency-Key -> body (reason 3-280,
`confirm_symbol == symbol`) -> pinned check (`include_pinned` required) -> plan the exact
window -> `retention.purge` audit with that window -> job. If the audit cannot be written the
answer is 503 and no job starts (C-2.9). The job executes exactly the audited plan; each
deletion inside it writes its own write-ahead `data.deleted`. The job result (and so the closing
`retention.purge` record) lists `skipped` (held at delete time) and `protected` (held while
planning), each as `{partition, reason}`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.api.recorder_admin import (
    RECORDING_WRITE,
    AdminJobStore,
    Job,
    JobConflict,
    _Emitter,
    _PrincipalResolver,
    _problem,
    logger,
)
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.recorder.retention import Protected, PrunePlan, RetentionBusy, RunReport

PURGE_JOB_KIND = "retention_purge"
STEP_UP_CLASS = "recorder"
_SYMBOL = r"^[A-Z0-9]{2,20}USDT$"


def _holds(held: list[Protected]) -> list[dict[str, str]]:
    """`[{partition, reason}]`: how the job result and the closing `retention.purge` record
    name partitions the purge kept (no paths beyond the partition key)."""
    return [{"partition": p.item.key, "reason": p.reason} for p in held]


class PurgeRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    symbol: str = Field(pattern=_SYMBOL)
    confirm_symbol: str = Field(pattern=_SYMBOL)
    reason: str = Field(min_length=3, max_length=280)
    before: datetime | None = None
    include_pinned: bool = False


class PurgeBackend(Protocol):
    async def is_pinned(self, symbol: str) -> bool: ...

    async def plan_purge(
        self, symbol: str, before_us: int, *, include_pinned: bool
    ) -> PrunePlan: ...

    async def run(self, plan: PrunePlan, dry_run: bool) -> RunReport: ...


#: (request) -> None when the session holds the `recorder` elevation, else the 403 response.
ElevationCheck = Callable[[Request, str], Awaitable[JSONResponse | None]]


def _us(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000)


def make_recorder_purge_router(
    jobs: AdminJobStore,
    backend: PurgeBackend | None,
    audit: _Emitter | None,
    principal_resolver: _PrincipalResolver | None,
    require_elevation: ElevationCheck | None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["recording"])
    reserve = asyncio.Lock()

    @router.post("/recorder/purge")
    async def purge(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        principal = await principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        common: dict[str, object] = {
            "actor_label": principal.username,
            "actor_user_id": principal.user_id,
            "actor_ip": principal.ip,
            "session_id": principal.session_id,
            "object_kind": "recorded_data",
            "request_id": principal.request_id,
        }

        async def denied(reason: str) -> None:
            if audit is not None:
                await audit.emit(
                    "retention.purge",
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason=reason,
                    **common,
                )

        if not principal.has(RECORDING_WRITE):  # RBAC before anything else (C-12.4)
            await denied(f"missing_permission:{RECORDING_WRITE}")
            return _problem(403, "Forbidden", f"requires {RECORDING_WRITE}")
        # Capability 9a (04-security-program §7.2 row 9a) is owner-only even though managers hold
        # `recording:write`; `is_owner` is resolved via `PrincipalSnapshot.is_owner` (SR-017).
        if not principal.is_owner:
            await denied("purge_owner_only")
            return _problem(403, "Forbidden", "purging recorded data is owner-only", "forbidden")
        if audit is None or backend is None or require_elevation is None:
            return _problem(503, "Service unavailable", "purge backend is not wired")
        refusal = await require_elevation(request, STEP_UP_CLASS)
        if refusal is not None:
            await denied("purge_requires_elevation")
            return refusal
        key = request.headers.get("idempotency-key", "")
        try:
            key = str(uuid.UUID(key))
        except ValueError:
            return _problem(400, "Bad request", "Idempotency-Key (UUID) is required")
        try:
            raw = await request.body()
            body = PurgeRequest.model_validate_json(raw or b"{}")
        except (ValidationError, ValueError):
            return _problem(422, "Unprocessable", "invalid purge request", "validation_failed")
        if body.confirm_symbol != body.symbol:
            await denied("purge_confirmation_mismatch")
            return _problem(
                422,
                "Unprocessable",
                "confirm_symbol must equal symbol",
                "purge_confirmation_mismatch",
            )
        now = clock()
        if body.before is not None and body.before.tzinfo is None:
            return _problem(
                422, "Unprocessable", "before must carry a UTC offset", "validation_failed"
            )
        before = min(body.before or now, now)
        params: dict[str, object] = {
            "symbol": body.symbol,
            "reason": body.reason,
            "before": body.before.isoformat() if body.before else None,
            "include_pinned": body.include_pinned,
        }
        body_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        actor = str(principal.user_id)
        prior = jobs.by_idempotency_key(actor, key)
        if prior is not None:
            if prior[1] != body_hash:
                return _problem(
                    422,
                    "Unprocessable",
                    "Idempotency-Key reused with a different body",
                    "idempotency_key_reused",
                )
            return JSONResponse(status_code=202, content={"job_id": prior[0].id})
        if await backend.is_pinned(body.symbol) and not body.include_pinned:
            await denied("retention_pinned_refused")
            return _problem(
                422,
                "Unprocessable",
                "symbol is pinned; set include_pinned to purge it",
                "retention_pinned_refused",
            )
        # Review (b): hold the reservation from the free-check through `submit`, so a concurrent
        # loser is refused 409 BEFORE it writes an intent record (no orphan audit entries).
        if reserve.locked():
            return _problem(409, "Conflict", "a purge job is already running", "job_running")
        async with reserve:
            return await _accept(
                backend, audit, body, before, params, body_hash, actor, key, common
            )

    async def _accept(
        backend: PurgeBackend,
        audit: _Emitter,
        body: PurgeRequest,
        before: datetime,
        params: dict[str, object],
        body_hash: str,
        actor: str,
        key: str,
        common: dict[str, object],
    ) -> JSONResponse:
        try:
            jobs.ensure_free(PURGE_JOB_KIND)
        except JobConflict:
            return _problem(409, "Conflict", "a purge job is already running", "job_running")
        plan = await backend.plan_purge(
            body.symbol, _us(before), include_pinned=body.include_pinned
        )
        window = {
            "symbol": body.symbol,
            "from_us": min((i.start_us for i in plan.items), default=0),
            "to_us": max((i.end_us for i in plan.items), default=0),
            "before_us": _us(before),
            "partitions": len(plan.items),
            "rows": plan.total_rows,
            "bytes": plan.total_bytes,
            "protected": len(plan.protected),
            "plan_id": plan.plan_id,
        }

        async def work(progress: Callable[[float], None]) -> dict[str, object]:
            report = await backend.run(plan, False)
            progress(100.0)
            return {
                "deleted": len(report.deleted),
                "freed_bytes": report.freed_bytes,
                "skipped": _holds(report.skipped),  # held at delete time (the re-check)
                "protected": _holds(report.protected),  # held while planning (never an item)
                "failed": len(report.failed),
            }

        async def done(job: Job) -> None:
            ok = job.status == "succeeded"
            await audit.emit(
                "retention.purge",
                outcome=AuditOutcome.SUCCESS if ok else AuditOutcome.FAILURE,
                severity=Severity.INFO if ok else Severity.ERROR,
                reason=None if ok else job.error,
                object_id=job.id,
                after_state={"window": window, "result": job.result or {}},
                **common,
            )

        job_id = str(uuid.uuid4())
        try:  # write-ahead (C-2.9): the exact window lands BEFORE the job exists
            await audit.emit(
                "retention.purge",
                object_id=job_id,
                object_label=body.symbol,
                reason=body.reason,
                severity=Severity.WARNING,
                before_state={"params": params, "window": window},
                **common,
            )
        except Exception as exc:
            logger().error("recorder_purge_audit_failed", error=type(exc).__name__)
            return _problem(
                503,
                "Service unavailable",
                "audit write failed; job not started",
                "audit_unavailable",
            )
        try:
            job = jobs.submit(PURGE_JOB_KIND, (actor, key, body_hash), work, done, job_id=job_id)
        except JobConflict:
            return _problem(409, "Conflict", "a purge job is already running", "job_running")
        return JSONResponse(status_code=202, content={"job_id": job.id})

    return router


__all__ = [
    "PURGE_JOB_KIND",
    "PurgeBackend",
    "PurgeRequest",
    "RetentionBusy",
    "make_recorder_purge_router",
]
