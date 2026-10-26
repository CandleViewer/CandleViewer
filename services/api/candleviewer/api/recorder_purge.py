"""`POST /admin/recorder/purge` (E16-T06): irreversible, owner-only, step-up, audited.

Order is a safety property (`22-api-openapi.yaml` `purgeRecordedData`): session -> RBAC
(`recording:write`, then owner-only capability 9a, before the body is read) -> Idempotency-Key ->
body (reason 3-280, `before` required with an offset and not later than the injected clock,
`confirm_symbol == symbol`), all before the gate so a refusal spends no code -> step-up: the
no-grace `recorder_purge` class, one fresh code bound to this exact request (method, raw target
and body) -> the durable idempotency anchor -> pinned check (`include_pinned` required) -> 409
while a purge runs -> plan the exact window `[earliest, before)` -> `retention.purge` audit with
that window and the `challenge_id` of the grant spent -> the anchor -> job. If the audit cannot be
written the answer is 503 and no job starts (C-2.9). The job executes exactly the audited plan;
each deletion inside it writes its own write-ahead `data.deleted`. The job result (and so the
closing `retention.purge` record) lists `skipped` (held at delete time) and `protected` (held
while planning), each as `{partition, reason}`.

Idempotency: the key is anchored permanently for the caller in `idempotency_anchors` with the
request's fingerprint and `before`, created right after the write-ahead record (a refusal or a 503
anchors nothing), so it outlives the process's job store and a restart. A retry with the same key
is compared on `before` first, as an instant: another bound is `409 idempotency_key_reuse` naming
the anchored one, whatever else differs; the same bound with another body is `422
idempotency_key_reused`; the same body is the job while this process knows it, else (after a
restart) a new purge of the same window with a new job, never past the anchored bound.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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
from candleviewer.api.step_up import SpentGrant
from candleviewer.api.step_up_challenge import raw_request_target, request_fingerprint
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.domain.text import refuse_unstorable_text
from candleviewer.recorder.retention import Protected, PrunePlan, RetentionBusy, RunReport
from candleviewer.storage.repositories.purge_anchors import (
    NewPurgeAnchor,
    PurgeAnchor,
    PurgeAnchorStore,
)

PURGE_JOB_KIND = "retention_purge"
#: A no-grace class (`auth.step_up.NO_GRACE_ACTION_CLASSES`): one fresh code per purge.
STEP_UP_CLASS = "recorder_purge"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
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
    before: datetime
    include_pinned: bool = False

    @field_validator("reason")
    @classmethod
    def _storable_reason(cls, value: str) -> str:
        return refuse_unstorable_text(value)


class PurgeBackend(Protocol):
    async def is_pinned(self, symbol: str) -> bool: ...

    async def plan_purge(
        self, symbol: str, before_us: int, *, include_pinned: bool
    ) -> PrunePlan: ...

    async def run(self, plan: PrunePlan, dry_run: bool) -> RunReport: ...


#: (request, action class, request fingerprint) -> the one-shot grant bound to that fingerprint
#: that this request spent, else the problem to answer (`api.step_up.require_bound_elevation`).
ElevationCheck = Callable[[Request, str, str], Awaitable[JSONResponse | SpentGrant]]


def _us(dt: datetime) -> int:
    """Microseconds since the epoch, exact (no float rounding)."""
    return (dt - _EPOCH) // timedelta(microseconds=1)


def _rfc3339(dt: datetime) -> str:
    """An instant as RFC 3339 UTC text (`Z`)."""
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(
    status: int, code: str, detail: str, field: str, rule: str, message: str
) -> JSONResponse:
    """A problem with one `errors[]` entry (`422 validation_failed`, `409`)."""
    title = "Conflict" if status == 409 else "Unprocessable"
    body: dict[str, object] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "errors": [{"field": field, "rule": rule, "message": message}],
    }
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def _reuse(found: PurgeAnchor, before_us: int) -> JSONResponse | None:
    """The refusal of a key the caller anchored to another request, `before` compared first (as
    an instant), else None (the same body)."""
    if found.before_us != before_us:
        return _invalid(
            409,
            "idempotency_key_reuse",
            "This Idempotency-Key is anchored to another purge window bound.",
            "before",
            "idempotency_bound_mismatch",
            f"anchored before is {_rfc3339(_EPOCH + timedelta(microseconds=found.before_us))}",
        )
    if not found.body_matches:
        return _problem(
            422,
            "Unprocessable",
            "Idempotency-Key reused with a different body",
            "idempotency_key_reused",
        )
    return None


def _store_down(exc: Exception) -> JSONResponse:
    logger().error("recorder_purge_anchor_unavailable", error=type(exc).__name__)
    return _problem(
        503, "Service unavailable", "idempotency store unavailable", "store_unavailable"
    )


def make_recorder_purge_router(
    jobs: AdminJobStore,
    backend: PurgeBackend | None,
    audit: _Emitter | None,
    principal_resolver: _PrincipalResolver | None,
    require_elevation: ElevationCheck | None,
    *,
    anchors: PurgeAnchorStore | None = None,
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
        if audit is None or backend is None or require_elevation is None or anchors is None:
            return _problem(503, "Service unavailable", "purge backend is not wired")
        key = request.headers.get("idempotency-key", "")
        try:
            key = str(uuid.UUID(key))
        except ValueError:
            return _problem(400, "Bad request", "Idempotency-Key (UUID) is required")
        # The body is decided before the gate: a malformed or refused request spends no code.
        try:
            raw = await request.body()
            body = PurgeRequest.model_validate_json(raw or b"{}")
            sent: object = json.loads(raw)
        except (ValidationError, ValueError):
            return _problem(422, "Unprocessable", "invalid purge request", "validation_failed")
        if body.before.tzinfo is None:
            return _problem(
                422, "Unprocessable", "before must carry a UTC offset", "validation_failed"
            )
        if body.before < _EPOCH:  # the anchor's bound is microseconds since the epoch (ia_bound)
            return _problem(
                422, "Unprocessable", "before must not precede 1970-01-01", "validation_failed"
            )
        now = clock()
        if body.before > now:  # strict: no clock-skew tolerance
            return _invalid(
                422,
                "validation_failed",
                "invalid purge request",
                "before",
                "before_in_future",
                f"before is later than the server's clock, which reads {_rfc3339(now)}",
            )
        if body.confirm_symbol != body.symbol:
            await denied("purge_confirmation_mismatch")
            return _problem(
                422,
                "Unprocessable",
                "confirm_symbol must equal symbol",
                "purge_confirmation_mismatch",
            )
        fingerprint = request_fingerprint(request.method, raw_request_target(request), sent)
        spent = await require_elevation(request, STEP_UP_CLASS, fingerprint)
        if not isinstance(spent, SpentGrant):
            await denied("purge_requires_elevation")
            return spent
        params: dict[str, object] = {
            "symbol": body.symbol,
            "reason": body.reason,
            "before": body.before.isoformat(),
            "include_pinned": body.include_pinned,
        }
        call = _Call(
            body=body,
            before_us=_us(body.before),
            params=params,
            fingerprint=fingerprint,
            actor=principal.user_id,
            key=key,
            challenge_id=spent.challenge_id,
            common=common,
        )
        anchored = await _lookup(anchors, call)
        if isinstance(anchored, JSONResponse):
            return anchored
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
            return await _accept(backend, audit, anchors, call)

    async def _lookup(anchors: PurgeAnchorStore, call: _Call) -> JSONResponse | bool:
        """The answer to a key the caller anchored already, else whether this request is anchored:
        False for a key never seen; True for the same body whose job this process does not know
        (a restart, or an evicted job), which is a new purge of the same window."""
        try:
            found = await anchors.find(call.actor, call.key, call.fingerprint)
        except Exception as exc:  # an outage: no answer from a store that may hold the key
            return _store_down(exc)
        if found is None:
            return False
        if (refused := _reuse(found, call.before_us)) is not None:
            return refused
        prior = jobs.by_idempotency_key(str(call.actor), call.key)
        if prior is not None and prior[1] == call.fingerprint:
            return JSONResponse(status_code=202, content={"job_id": prior[0].id})
        return True

    async def _accept(
        backend: PurgeBackend, audit: _Emitter, anchors: PurgeAnchorStore, call: _Call
    ) -> JSONResponse:
        body, common = call.body, call.common
        try:
            jobs.ensure_free(PURGE_JOB_KIND)
        except JobConflict:
            return _problem(409, "Conflict", "a purge job is already running", "job_running")
        # Under the reservation: a request with this key may have won the lock meanwhile.
        anchored = await _lookup(anchors, call)
        if isinstance(anchored, JSONResponse):
            return anchored
        plan = await backend.plan_purge(
            body.symbol, call.before_us, include_pinned=body.include_pinned
        )
        window = {
            "symbol": body.symbol,
            "from_us": min((i.start_us for i in plan.items), default=0),
            "to_us": max((i.end_us for i in plan.items), default=0),
            "before_us": call.before_us,
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

        job_id = uuid.uuid4()
        try:  # write-ahead (C-2.9): the exact window lands BEFORE the job exists
            await audit.emit(
                "retention.purge",
                object_id=str(job_id),
                object_label=body.symbol,
                reason=body.reason,
                severity=Severity.WARNING,
                before_state={
                    "params": call.params,
                    "window": window,
                    "challenge_id": str(call.challenge_id),
                },
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
        if not anchored:  # the permanent anchor, with the write-ahead record, before the job
            anchor = NewPurgeAnchor(
                id=job_id,
                created_by=call.actor,
                client_ref=call.key,
                request_sha256=call.fingerprint,
                before_us=call.before_us,
            )
            try:
                created = await anchors.create(anchor)
            except Exception as exc:
                await _closed_unstarted(audit, job_id, window, common, "anchor_unavailable")
                return _store_down(exc)
            if not created:  # another request anchored the key first: nothing starts here
                await _closed_unstarted(audit, job_id, window, common, "idempotency_key_held")
                return await _raced(anchors, call)
        idem = (str(call.actor), call.key, call.fingerprint)
        try:
            job = jobs.submit(PURGE_JOB_KIND, idem, work, done, job_id=str(job_id))
        except JobConflict:
            return _problem(409, "Conflict", "a purge job is already running", "job_running")
        return JSONResponse(status_code=202, content={"job_id": job.id})

    async def _raced(anchors: PurgeAnchorStore, call: _Call) -> JSONResponse:
        """The answer when the insert found the key held: the anchor that won, re-read and judged
        by the contract's rules (`before` first, then the body). The same body is that request's
        purge, which it is starting: its job if this process knows it, else `409 job_running`,
        the nearest code the contract gives this operation (it defines no `idempotency_in_flight`
        here), never a second purge."""
        answer = await _lookup(anchors, call)
        if isinstance(answer, JSONResponse):
            return answer
        if not answer:  # the store reported the key held, then no row for it: an outage
            return _store_down(RuntimeError("purge anchor vanished"))
        return _problem(409, "Conflict", "a purge job is already running", "job_running")

    async def _closed_unstarted(
        audit: _Emitter,
        job_id: uuid.UUID,
        window: dict[str, object],
        common: dict[str, object],
        reason: str,
    ) -> None:
        """Close the intent record of a purge that never started (best effort: the answer
        stands)."""
        try:
            await audit.emit(
                "retention.purge",
                outcome=AuditOutcome.FAILURE,
                severity=Severity.ERROR,
                reason=reason,
                object_id=str(job_id),
                after_state={"window": window, "result": {}},
                **common,
            )
        except Exception as exc:
            logger().error("recorder_purge_audit_failed", error=type(exc).__name__)

    return router


@dataclass(frozen=True, slots=True)
class _Call:
    """One validated, step-up-authorised purge request, as `_accept` takes it."""

    body: PurgeRequest
    before_us: int
    params: dict[str, object]
    fingerprint: str
    actor: uuid.UUID
    key: str
    challenge_id: uuid.UUID
    common: dict[str, object]


__all__ = [
    "PURGE_JOB_KIND",
    "PurgeBackend",
    "PurgeRequest",
    "RetentionBusy",
    "make_recorder_purge_router",
]
