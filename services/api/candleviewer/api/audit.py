"""`GET /admin/audit`, `POST /admin/audit/verify`, `POST /admin/audit/export`,
`POST /admin/audit/chain-breaks/{firstBadId}/acknowledge` (#2904, `acknowledgeAuditChainBreak`)
(E09-T02 acceptance criteria: "Endpoints ... `GET /admin/audit` ... `POST
/admin/audit/verify` ... `POST /admin/audit/export`"; the signed export since #889
S10), the export's download, `GET /admin/audit/exports/{jobId}` (#889 S9), and
the export signing keys, `GET /admin/audit/signing-keys` (#889 S7).

QA defect #1596 blocker 1: `candleviewer.audit.query.AuditQueryService` and
`candleviewer.audit.access.authorize` existed but no `APIRouter` mounted
them — `grep -rn 'APIRouter' services/api/candleviewer/audit` found
nothing. This module is the thin HTTP adapter `api/auth.py` already
establishes the pattern for: structural Protocols for the injected
services (no import edge beyond what `audit`'s own public surface already
requires), RFC 7807 problem responses, and audit-of-the-audit-denial via
`candleviewer.audit.access.authorize` (ticket AC "Non-owner cannot read the
audit log" — the denial is itself audited, before the 403 is returned).

Principal resolution: `auth`'s session/RBAC-context middleware is out of
this ticket's scope (E09-T02 does not own it; `auth/service.py` is still
the M18 scaffold with no session verification). Per `x-rbac: {scope: none}`
these routes fail closed rather than guess: a caller is resolved via an
injected `PrincipalResolver` (structurally typed, mirrors `AuditServiceLike`
in `api/auth.py`); the composition root wires a real one when M18 lands
session verification. Until then `create_app()` passes `None` for
`principal_resolver`, and every request is refused with `501 Not
Implemented` (never silently allowed) — no session-verification module
exists yet to say yes or no. Once a resolver *is* wired (PR #1608 review
finding 1: `app.py` now passes one) but it reports "no verified session"
for a given request, that is a normal 401 per the resolver's own contract
(finding 4) — `501` is reserved for the "nothing is wired at all" case.
"""

from __future__ import annotations

import functools
import hashlib
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from candleviewer.api.audit_budget import (
    DENIAL_ACTION,
    AuditRecordBudget,
    BudgetActor,
    BudgetedEmitter,
    BudgetWriteFailed,
    ReadReservation,
    filters_digest,
)
from candleviewer.api.audit_exports import (
    EXPORT_ACTION,
    AuditExports,
    Export,
    ExportFileResponse,
    export_window,
)
from candleviewer.api.audit_limiter import (
    DOWNLOAD_RATE_PER_HOUR,
    EXPORT_RATE_PER_HOUR,
    AuditQueryLimiter,
    AuditQueryRefused,
    AuditVerifyLimiter,
)
from candleviewer.api.audit_signing_keys import signing_key_view
from candleviewer.api.audit_verify import (
    VERIFY_DEADLINE_S,
    VERIFY_STOP_ERRORS,
    BreakHalt,
    observe_stop,
    observe_verify,
    raise_break_event,
    record_halt,
    result_record,
    verify_stop,
    write_verify_record,
)
from candleviewer.api.idempotency import IdempotencyKeyReuse, request_fingerprint
from candleviewer.api.recorder_admin import JobConflict
from candleviewer.api.step_up import (
    SpentGrant,
    StepUpAuth,
    require_bound_elevation,
    require_session_elevation,
)
from candleviewer.api.step_up_challenge import ChallengeText, export_audit_text, raw_request_target
from candleviewer.api.step_up_challenge import request_fingerprint as bound_fingerprint
from candleviewer.audit.access import (
    AuditAccessDenied,
    AuditPrincipal,
    AuditView,
    authorize,
    redact_entry_for_view,
)
from candleviewer.audit.break_halt import AckOutcome, AckRequest, AuditBreakHalt, BreakIdentity
from candleviewer.audit.cursor import AuditCursor, InvalidAuditCursor, decode_cursor
from candleviewer.audit.export_job import ExportRequest, ExportSettings, SignedExport
from candleviewer.audit.export_signing import Signer, SigningKeyDirectory
from candleviewer.audit.hashing import ChainHasherBusy
from candleviewer.audit.models import (
    AUDIT_QUERY_DEFAULT_LIMIT,
    AuditBreakAckRequest,
    AuditExportRequest,
    AuditOutcome,
    AuditQueryRequest,
    AuditVerifyRequest,
    ExportResult,
    Severity,
)
from candleviewer.audit.query import VERIFY_MAX_SPAN, VerifyPlan, VerifyRangeBeyondHead
from candleviewer.audit.verify_slot import VerifySlot
from candleviewer.observability.audit_query_metrics import cv_audit_query_duration_seconds
from candleviewer.observability.health_probes import SystemEventWriter
from candleviewer.storage.backup_artefacts import ResolvedArtefact
from candleviewer.storage.errors import AuditEntryTooLarge, StorageTierUnavailable


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Emitter(Protocol):
    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: Any = None,
        actor_ip: str | None = None,
        session_id: Any = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        object_label: str | None = None,
        outcome: Any = ...,
        severity: Any = ...,
        reason: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: Any = None,
        env: Any = None,
    ) -> None: ...


class AuditQueryServiceLike(Protocol):
    """Structural type for `candleviewer.audit.query.AuditQueryService`."""

    async def query(
        self,
        *,
        restrict_to_actor: str | None,
        actor_user_id: str | None = None,
        actions: list[str] | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        severity: str | None = None,
        outcome: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        q: str | None = None,
        after: AuditCursor | None = None,
        limit: int = AUDIT_QUERY_DEFAULT_LIMIT,
        ip: str | None = None,
        timeout_ms: int | None = None,
        owner: bool = False,
        raw: bool = False,
    ) -> Any: ...

    async def plan_verify(
        self, *, from_id: int | None, to_id: int | None, max_span: int = ...
    ) -> VerifyPlan: ...

    async def run_verify(
        self, plan: VerifyPlan, *, batch_size: int = ..., deadline_s: float | None = ...
    ) -> Any: ...

    @property
    def verify_slot(self) -> VerifySlot: ...

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


class AuditWriterLike(_Emitter, Protocol):
    """Only the `emit()` subset `authorize()` needs to record a denial."""


class AuditServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def query(self) -> AuditQueryServiceLike: ...

    @property
    def writer(self) -> AuditWriterLike: ...


class BreakAck(Protocol):
    """`audit.break_halt.AuditBreakHaltService`, as `acknowledgeAuditChainBreak` uses it."""

    @property
    def halt(self) -> AuditBreakHalt: ...

    async def acknowledge(
        self, request: AckRequest, *, is_owner: bool, emit: Callable[..., Awaitable[None]]
    ) -> AckOutcome: ...


class _StepUpEmitter:
    """The writer, as the step-up gate records a mismatched grant through it."""

    def __init__(self, writer: _Emitter) -> None:
        self._writer = writer

    async def emit(self, action: str, **kwargs: Any) -> None:
        await self._writer.emit(action, **kwargs)


class PrincipalResolver(Protocol):
    """Resolves the authenticated caller for an `/admin/audit*` request.

    Structurally typed so this router never imports a concrete session
    module; the composition root injects the real implementation once M18
    exposes one. Returning `None` means "no verified session" (401) — a
    resolver being wired at all vs. it finding no session are distinct
    (PR #1608 review finding 4): a *missing* resolver (`make_audit_router`'s
    own `principal_resolver=None` default) is `501`, since that means
    session verification is not implemented yet, not that this particular
    caller is unauthenticated."""

    async def resolve(self, request: Request) -> AuditPrincipal | None: ...


#: `errors[]` is bounded and names only the field and the rule: a validation message can
#: quote the rejected value (`ipaddress` does), so none is returned.
_MAX_ERRORS = 10
#: Contract parameter names where they differ from the `AuditQueryRequest` field names.
_PARAM_NAMES = {"actions": "action", "from_ts": "from", "to_ts": "to"}
#: Contract (`queryAuditLog`): a `200` page is never cached; it carries IPs and payloads. The
#: verify and export routes answer the same way, as their answers name a range, a chain state
#: or who was refused. `_no_store` is the one place the header is set.
_NO_STORE: Final = {"Cache-Control": "no-store"}
#: `listAuditSigningKeys`' own filter set, which no `queryAuditLog` call has (#889 S7).
_SIGNING_KEYS: Final = {"view": "signing_keys"}


def _problem(
    status_code: int,
    title: str,
    detail: str,
    *,
    code: str,
    retry_after_s: int | None = None,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "type": f"https://candleviewer.local/errors/{code}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    if errors is not None:
        content["errors"] = errors
    response = JSONResponse(
        status_code=status_code, content=content, media_type="application/problem+json"
    )
    if retry_after_s is not None:
        response.headers["Retry-After"] = str(retry_after_s)
    return response


def _invalid(exc: ValidationError, model: type[BaseModel], status_code: int = 422) -> JSONResponse:
    """`validation_failed` without echoing the input. A field the model does not declare
    (an unknown body key) is reported as `(unknown)`, never by its client-chosen name."""
    known = set(model.model_fields) | {f.alias for f in model.model_fields.values() if f.alias}
    errors = []
    for err in exc.errors(include_url=False, include_context=False, include_input=False):
        name = str(err["loc"][0]) if err["loc"] else ""
        field = _PARAM_NAMES.get(name, name) if name in known or not name else "(unknown)"
        errors.append({"field": field, "rule": err["type"]})
    return _problem(
        status_code,
        "Request validation failed",
        f"{exc.error_count()} field(s) failed validation",
        code="validation_failed",
        errors=errors[:_MAX_ERRORS],
    )


#: The verify body holds two ids at most, the export body two instants and a flag; a longer one
#: is refused without reading the rest.
_VERIFY_BODY_MAX_BYTES = 1024
#: The acknowledgement body: a kind and a reason of at most 280 characters.
_ACK_BODY_MAX_BYTES: Final = 2048
_INT64_MAX: Final = 2**63 - 1
#: `exportAuditLog`'s request fingerprint covers the contract path (22 Idempotency).
_EXPORT_PATH: Final = "/admin/audit/export"
#: Why export alone is unavailable, its `503 signing_unavailable`'s detail by its record's reason.
_EXPORT_DOWN: Final = {
    "signing_unavailable": "The export signing key is missing or cannot be opened.",
    "export_volume_unavailable": "The export directory cannot take an export file.",
}


async def _read_capped(request: Request, limit: int) -> bytes | None:
    """The request body, or `None` once it would pass `limit` bytes: a declared
    `Content-Length` over it is refused unread, and no chunk past it is kept."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            return None
        body += chunk
    return bytes(body)


def _unavailable(detail: str = "audit record could not be written") -> JSONResponse:
    return _problem(503, "Service unavailable", detail, code="store_unavailable", retry_after_s=1)


_SUCCESS, _FAILURE = AuditOutcome.SUCCESS, AuditOutcome.FAILURE
_INFO, _WARNING = Severity.INFO, Severity.WARNING


def _rule(field: str, rule: str, detail: str) -> JSONResponse:
    """A `422 validation_failed` naming the field and the rule it broke, never a value."""
    errors = [{"field": field, "rule": rule}]
    return _problem(
        422, "Request validation failed", detail, code="validation_failed", errors=errors
    )


def _scheduled(job_id: str, *, replayed: bool = False) -> JSONResponse:
    """22's `202`: the job, its `download_url` null; a repeat's carries `Idempotency-Replayed`."""
    content = ExportResult(job_id=uuid.UUID(job_id)).model_dump(mode="json")
    answer = JSONResponse(status_code=202, content=content)
    if replayed:
        answer.headers["Idempotency-Replayed"] = "true"
    return answer


def _verify_unavailable(exc: Exception) -> JSONResponse:
    """The `503` for a verify that stopped early, with `Retry-After` but for an entry over the
    per-entry cap: no retry can pass that one until the cap is raised, so it has none."""
    detail = verify_stop(exc)[1]
    if isinstance(exc, AuditEntryTooLarge):
        return _problem(503, "Service unavailable", detail, code="store_unavailable")
    return _unavailable(detail)


def _no_store[**P, R: Response](
    handler: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Every response the handler returns carries `_NO_STORE`, a refusal included, so no
    browser or proxy cache keeps an audit page, a verify result, an export file or a refusal.
    FastAPI reads the handler's own signature through `functools.wraps`."""

    @functools.wraps(handler)
    async def no_store(*args: P.args, **kwargs: P.kwargs) -> R:
        response = await handler(*args, **kwargs)
        response.headers.update(_NO_STORE)
        return response

    return no_store


def _budget_actor(principal: AuditPrincipal) -> BudgetActor:
    # The Owner's cap and tracked entry follow the resolved `is_owner` only
    # (`PrincipalSnapshot.is_owner`, SR-017), never a role name or a grant. The budget is the
    # actor's (#3085): a viewer never spends the target's.
    owner = principal.is_owner
    return BudgetActor(str(principal.actor_id), principal.actor_name, principal.actor_id, owner)


def _request_fields(principal: AuditPrincipal) -> dict[str, Any]:
    return {
        "actor_label": principal.actor_name,
        "actor_user_id": principal.actor_id,
        "actor_ip": principal.ip,
        "session_id": principal.session_id,
        "object_kind": "audit_log",
        "request_id": principal.request_id,
    }


def _export_fields(principal: AuditPrincipal, job_id: str) -> dict[str, Any]:
    """`_request_fields` naming the export: its job id when that is a canonical UUID, so no other
    text from the request reaches the append-only log."""
    try:
        named = str(uuid.UUID(job_id)) == job_id
    except ValueError:
        named = False
    object_id = job_id if named else None
    return _request_fields(principal) | {"object_kind": "audit_export", "object_id": object_id}


def _recorded_filters(req: AuditQueryRequest, actor_user_id: str | None) -> dict[str, Any]:
    """The filter set as recorded and digested: validated canonical values under their
    contract names, without paging or unset filters (`ip` stays under `ip`, which the
    audit redactor hashes). The two free-text filters, `q` (contract) and `subject_id`,
    are kept only as a digest and their length, so text typed into them, control
    characters included, never reaches the append-only log verbatim."""
    narrowed = req.model_copy(update={"actor_user_id": actor_user_id})
    dumped = narrowed.model_dump(mode="json", exclude={"limit"}, exclude_none=True)
    for name in ("q", "subject_id"):
        text = dumped.pop(name, None)
        if text is not None:
            dumped[f"{name}_sha256"] = hashlib.sha256(text.encode()).hexdigest()
            dumped[f"{name}_len"] = len(text)
    return {_PARAM_NAMES.get(k, k): v for k, v in dumped.items()}


def _filter_class(filters: dict[str, Any], restrict: str | None) -> str:
    """The closed `filter_class` label (`FILTER_CLASSES`): which filters shaped the page,
    never their values."""
    if filters["q"] is not None or filters["ip"] is not None:
        return "q" if filters["q"] is not None else "ip"
    if restrict is not None or filters["actor_user_id"] is not None:
        return "actor_action" if filters["actions"] else "actor"
    for name, columns in _CLASS_COLUMNS:
        if any(filters[c] is not None for c in columns):
            return name
    return "none"


_CLASS_COLUMNS = (
    ("action", ("actions",)),
    ("object", ("subject_type", "subject_id")),
    ("severity", ("severity",)),
    ("outcome", ("outcome",)),
    ("range", ("from_ts", "to_ts")),
)


def make_audit_router(
    audit_service: AuditServiceLike | None,
    principal_resolver: PrincipalResolver | None = None,
    *,
    limiter: AuditQueryLimiter | None = None,
    budget: AuditRecordBudget | None = None,
    query_timeout_ms: int = 4000,
    verify_max_span: int = VERIFY_MAX_SPAN,
    verify_limiter: AuditVerifyLimiter | None = None,
    verify_deadline_s: float = VERIFY_DEADLINE_S,
    verify_events: SystemEventWriter | None = None,
    exports: AuditExports | None = None,
    step_up: StepUpAuth | None = None,
    download_limiter: AuditVerifyLimiter | None = None,
    signing_keys: SigningKeyDirectory | None = None,
    export_limiter: AuditVerifyLimiter | None = None,
    export_max_range_days: int = 31,
    break_halt: BreakHalt | None = None,
    break_ack: BreakAck | None = None,
) -> APIRouter:
    """Bind `/admin/audit*` to a concrete `AuditService` instance.

    `break_halt` is the audit-chain break halt (#2904): a break an on-demand verify finds halts
    position-opening order entry before the run's records are written. `break_ack` serves its
    acknowledgement (`acknowledgeAuditChainBreak`); without it, or without `step_up`, that is a
    `503` and nothing is lifted.

    `audit_service=None` (fake/CI-default backend, mirrors `AuthService`'s
    own optionality) and `principal_resolver=None` (no session module wired
    yet) both degrade to `503`/`501` responses rather than raising at import
    time, so `create_app()` stays constructible with fakes only (C-2.16-
    adjacent: the router itself never touches a datastore or the network).

    Read and refusal records go through `budget` (contract "Audit budget"): a record
    over the user's cap is counted instead, which makes a read `429` and leaves a
    refusal unchanged but for `Retry-After`; a due record that cannot be written makes
    the call `503` with nothing returned (C-2.9).

    The export schedules `exports`' signed job, at most `export_limiter`'s hourly count of a
    window of `export_max_range_days` (#889 S10); without `exports` export is unavailable. The
    download serves `exports`' files with `step_up`'s `audit` class and `download_limiter`'s hourly
    count; without `exports` or `step_up` it serves none. The signing-key list reads
    `signing_keys`, M2's directory; without it the keys are a `503`.

    A Viewer holds no `audit:read` and gets `403` on every route here, as decided on
    #2083. Whether C-12.4's "Viewer (read-only, including audit)" should change that is
    the owner's decision on #2428 (design D7); nothing in this router grants it.
    """
    router = APIRouter(prefix="/admin/audit", tags=["admin"])
    query_limiter = limiter if limiter is not None else AuditQueryLimiter()
    record_budget = budget if budget is not None else AuditRecordBudget()
    verify_limits = verify_limiter if verify_limiter is not None else AuditVerifyLimiter()
    downloads = (
        download_limiter
        if download_limiter is not None
        else AuditVerifyLimiter(rate_per_hour=DOWNLOAD_RATE_PER_HOUR)
    )
    export_starts = (
        export_limiter
        if export_limiter is not None
        else AuditVerifyLimiter(rate_per_hour=EXPORT_RATE_PER_HOUR)
    )

    class _HttpProblem(Exception):
        def __init__(self, response: JSONResponse) -> None:
            self.response = response

    def _over_cap(key: str, detail: str = "audit record budget reached") -> JSONResponse:
        retry = record_budget.retry_after(key)
        return _problem(429, "Too many requests", detail, code="rate_limited", retry_after_s=retry)

    def _forbidden(key: str, emitter: BudgetedEmitter, detail: str) -> JSONResponse:
        # `Retry-After` only for a refusal over the caller's own record cap.
        retry = record_budget.retry_after(key) if emitter.suppressed else None
        return _problem(403, "Forbidden", detail, code="forbidden", retry_after_s=retry)

    async def _authorize_or_raise(
        request: Request, operation: str
    ) -> tuple[AuditServiceLike, AuditPrincipal, AuditView]:
        if audit_service is None or not audit_service.is_active:
            raise _HttpProblem(_unavailable("audit backend is not wired"))
        if principal_resolver is None:
            raise _HttpProblem(
                _problem(
                    501,
                    "Not implemented",
                    "no principal resolver wired — session verification is out of this "
                    "ticket's scope",
                    code="not_implemented",
                )
            )
        principal = await principal_resolver.resolve(request)
        if principal is None:
            raise _HttpProblem(
                _problem(
                    401,
                    "Unauthorized",
                    "no verified session for this request",
                    code="unauthenticated",
                )
            )
        emitter = record_budget.emitter(audit_service.writer, _budget_actor(principal))
        try:
            view = await authorize(principal, operation, emitter)
        except BudgetWriteFailed as exc:
            raise _HttpProblem(_unavailable()) from exc
        except AuditAccessDenied as exc:
            raise _HttpProblem(_forbidden(str(principal.actor_id), emitter, str(exc))) from exc
        return audit_service, principal, view

    @router.get("")
    @_no_store
    async def query_audit_log(
        request: Request,
        # Every parameter is declared as text (`action` as a list of text), to validate
        # query parameters after authorisation, in `AuditQueryRequest` below.
        actor_user_id: str | None = None,
        # Without `Query()` a list parameter is read from a JSON body, even on a GET.
        action: Annotated[list[str] | None, Query()] = None,
        subject_type: str | None = None,
        outcome: str | None = None,
        severity: str | None = None,
        # `from` is a Python keyword; the OpenAPI contract (22-api-openapi.yaml) names
        # the query parameter `from`, so alias it — without the alias `?from=` was
        # silently ignored and the lower time bound dropped.
        from_: Annotated[str | None, Query(alias="from")] = None,
        to: str | None = None,
        cursor: str | None = None,
        limit: str | None = None,
        ip: str | None = None,
        subject_id: str | None = None,
        q: str | None = None,
    ) -> JSONResponse:
        try:
            service, principal, view = await _authorize_or_raise(request, "query")
        except _HttpProblem as problem:
            return problem.response
        actor = _budget_actor(principal)
        emitter = record_budget.emitter(service.writer, actor)
        hidden = [name for name, value in (("ip", ip), ("q", q)) if value is not None]
        if view is not AuditView.RAW and hidden:
            # Contract: `ip` and `q` are Owner only. The redacted projection hides the IP and
            # the payload, so filtering on them would reveal them one query at a time.
            return await _refuse(emitter, principal, f"filter_not_permitted:{hidden[0]}")
        try:
            after = None if cursor is None else decode_cursor(cursor)
        except InvalidAuditCursor as exc:
            return _problem(400, "Invalid cursor", str(exc), code="invalid_cursor")
        try:
            req = AuditQueryRequest.model_validate(
                {
                    "actor_user_id": actor_user_id,
                    "actions": action,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "ip": ip,
                    "severity": severity,
                    "outcome": outcome,
                    "from_ts": from_,
                    "to_ts": to,
                    "q": q,
                    "limit": AUDIT_QUERY_DEFAULT_LIMIT if limit is None else limit,
                }
            )
        except ValidationError as exc:
            return _invalid(exc, AuditQueryRequest)
        filters = req.model_dump()
        try:
            lease = query_limiter.acquire(actor.key)
        except AuditQueryRefused as exc:
            record_budget.count_suppressed(actor)
            return _problem(
                429,
                "Too many requests",
                "audit query limit reached",
                code="rate_limited",
                retry_after_s=exc.retry_after_s,
            )
        try:
            if view is not AuditView.RAW:
                own = str(principal.user_id)  # the subject's: the target's events while viewing
                if req.actor_user_id not in (None, own):
                    refused = await _record_cross_actor(emitter, principal, req.actor_user_id)
                    if refused is not None:
                        return refused
                # SR-067: a non-owner reads only its own events. The repository applies
                # the scope in the SQL of every page, whatever `actor_user_id` was sent.
                filters["actor_user_id"] = own
            recorded = _recorded_filters(req, filters["actor_user_id"])
            plan = record_budget.plan_read(actor, filters_digest(recorded))
            try:
                return await _run_query(service, principal, view, filters, after, plan, recorded)
            finally:
                plan.release()  # a read that served nothing gives its reservation back
        finally:
            lease.release()

    async def _refuse(
        emitter: BudgetedEmitter, principal: AuditPrincipal, reason: str
    ) -> JSONResponse:
        try:
            await emitter.emit(
                DENIAL_ACTION,
                **_request_fields(principal),
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=reason,
            )
        except BudgetWriteFailed:
            return _unavailable()
        return _forbidden(str(principal.actor_id), emitter, "filter not permitted for this caller")

    async def _record_cross_actor(
        emitter: BudgetedEmitter, principal: AuditPrincipal, requested: str
    ) -> JSONResponse | None:
        """Record the attempt before the narrowed read runs (contract: "the attempt is
        recorded"). Over the cap the read is `429`; unwritable is `503`; both serve nothing."""
        try:
            await emitter.emit(
                DENIAL_ACTION,
                **_request_fields(principal),
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="cross_actor_filter_narrowed",
                after_state={"requested_actor": requested},
            )
        except BudgetWriteFailed:
            return _unavailable()
        return _over_cap(str(principal.actor_id)) if emitter.suppressed else None

    async def _run_query(
        service: AuditServiceLike,
        principal: AuditPrincipal,
        view: AuditView,
        filters: dict[str, Any],
        after: AuditCursor | None,
        plan: ReadReservation,
        recorded: dict[str, Any],
    ) -> JSONResponse:
        key = str(principal.actor_id)  # the actor's limit (#3085)
        if plan.action == "refuse":
            return _over_cap(key)
        if plan.action == "unwritable":
            return _unavailable()
        # Fail closed: any view but the Owner's raw one is scoped to the subject's own entries,
        # the target's while viewing (#3085: a `scope: self` read answers as the target's).
        restrict = None if view is AuditView.RAW else str(principal.user_id)
        started = time.perf_counter()
        try:
            page = await service.query.query(
                **filters,
                restrict_to_actor=restrict,
                # Only the Owner's raw view fetches the Owner-only columns. Stated from the
                # view, never inferred from the scope or the read-slot flag below.
                raw=view is AuditView.RAW,
                after=after,
                timeout_ms=query_timeout_ms,
                # The read slot kept for the Owner follows `is_owner` only (SR-017).
                owner=principal.is_owner,
            )
        except ValidationError as exc:
            return _invalid(exc, AuditQueryRequest)
        except TimeoutError:
            return _unavailable("audit query exceeded its time budget")
        except ChainHasherBusy:
            return _unavailable("audit read capacity reached")
        except StorageTierUnavailable:
            # The store error carries only its SQLSTATE (or that every read slot is in
            # use); it is logged where it is raised.
            return _unavailable("audit store unavailable")
        elapsed = time.perf_counter() - started
        cv_audit_query_duration_seconds.labels(_filter_class(filters, restrict)).observe(elapsed)
        if restrict is not None:
            if any(str(e.actor_user_id) != restrict for e in page.items):
                # The scope is applied in the SQL; a row outside it is never served.
                _log().error("audit.read.out_of_scope", view=view.value)
                return _unavailable("audit store unavailable")
            items = [redact_entry_for_view(e, view) for e in page.items]
            page = page.model_copy(update={"items": items})
        if plan.action == "record":
            # The filters and the returned count, never the entries.
            detail = {"view": view.value, "filters": recorded, "returned_count": len(page.items)}
            try:
                await record_budget.write_read(
                    plan, service.writer, _request_fields(principal), detail
                )
            except BudgetWriteFailed:
                return _unavailable()
        plan.commit()
        return JSONResponse(status_code=200, content=_jsonable(page))

    @router.post("/verify")
    @_no_store
    async def verify_audit_chain(request: Request) -> JSONResponse:
        try:
            service, principal, _ = await _authorize_or_raise(request, "verify")
        except _HttpProblem as problem:
            return problem.response
        # The optional body is read only now: 401 and 403 come before its validation.
        raw = await _read_capped(request, _VERIFY_BODY_MAX_BYTES)
        if raw is None:
            detail = f"the body is over {_VERIFY_BODY_MAX_BYTES} bytes"
            errors = [{"field": "", "rule": "max_body_bytes"}]
            return _problem(
                422, "Request validation failed", detail, code="validation_failed", errors=errors
            )
        try:
            req = AuditVerifyRequest.model_validate_json(raw or b"{}")
        except ValidationError as exc:
            return _invalid(exc, AuditVerifyRequest)
        if req.from_id is not None and req.to_id is not None:
            if req.to_id - req.from_id >= verify_max_span:
                return _problem(
                    422,
                    "Request validation failed",
                    f"the range spans more than audit_verify_max_span ({verify_max_span}) ids",
                    code="validation_failed",
                    errors=[{"field": "to_id", "rule": "max_verify_span"}],
                )
        try:  # one head read at range defaulting (#2446)
            plan = await service.query.plan_verify(
                from_id=req.from_id, to_id=req.to_id, max_span=verify_max_span
            )
        except VerifyRangeBeyondHead:
            return _problem(404, "Not found", "from_id is beyond the chain head", code="not_found")
        except VERIFY_STOP_ERRORS as exc:
            return _verify_unavailable(exc)
        # Then the per-user limit (429) and single-flight (409). The head read (range
        # defaulting, above) comes first, as the contract orders the checks; a caller who is
        # not authorised never reaches it. A refusal writes no record: it is counted and
        # carried by the user's next record (contract "Audit budget").
        actor = _budget_actor(principal)
        retry = verify_limits.retry_after(actor.key)
        if retry is not None:
            record_budget.count_suppressed(actor)
            detail = "audit verify limit reached"
            return _problem(
                429, "Too many requests", detail, code="rate_limited", retry_after_s=retry
            )
        slot = service.query.verify_slot
        if not slot.try_acquire():
            record_budget.count_suppressed(actor)
            detail = "a verification is already running"
            return _problem(409, "Conflict", detail, code="conflict")
        try:
            return await _run_verify(service, principal, plan)
        finally:
            slot.release()  # also after a deadline overrun, which is 503

    async def _run_verify(
        service: AuditServiceLike, principal: AuditPrincipal, plan: VerifyPlan
    ) -> JSONResponse:
        """Write-ahead `started` record, the run, then its result record (#2392). The
        records go straight to the writer, never through the budget; one that cannot be
        written makes the call 503 and serves nothing. A run that stops early is recorded
        as failure/warning with the reason it stopped (`internal_error` for anything
        unexpected, also 503), and a full-range stop turns a chain gauge of 1 into NaN (0
        stays until a full-range run passes); a cancellation propagates. Each of these 503s
        carries `Retry-After` but `entry_too_large`, which no retry can pass until the cap is
        raised. A break's system event comes after the result record, in a `finally` so a
        record that cannot be written still raises it; it is best effort and delays the
        response by at most `EVENT_TIMEOUT_S` (2 s)."""
        emit, fields = service.writer.emit, _request_fields(principal)
        span = {"from_id": plan.from_id, "to_id": plan.to_id}
        if not await write_verify_record(
            emit, fields, outcome=_SUCCESS, severity=_INFO, reason="started", after_state=span
        ):
            return _unavailable()
        verify_limits.record_start(str(principal.actor_id))  # only a run that starts counts
        try:
            result = await service.query.run_verify(plan, deadline_s=verify_deadline_s)
        except VERIFY_STOP_ERRORS as exc:
            observe_stop(full_chain=plan.full_chain)
            if isinstance(exc, AuditEntryTooLarge):  # the entry's id and the class only
                _log().warning(
                    "audit.verify.entry_too_large", entry_id=exc.entry_id, error=type(exc).__name__
                )
            reason = verify_stop(exc)[0]
            await write_verify_record(
                emit, fields, outcome=_FAILURE, severity=_WARNING, reason=reason, after_state=span
            )
            return _verify_unavailable(exc)
        except Exception as exc:  # anything else, e.g. MemoryError: never a 500, never a pass
            observe_stop(full_chain=plan.full_chain)
            _log().error("audit.verify.failed", error=type(exc).__name__)
            await write_verify_record(
                emit,
                fields,
                outcome=_FAILURE,
                severity=_WARNING,
                reason="internal_error",
                after_state=span,
            )
            return _unavailable("audit verify failed")
        owed = None if break_halt is None else break_halt.trip(result)  # #2904: before any await
        observe_verify(result)  # the chain series follow the run, recorded or not
        outcome, severity, reason, after = result_record(result)
        request_id = principal.request_id
        try:  # the record first: it alone decides the response
            if not await write_verify_record(
                emit, fields, outcome=outcome, severity=severity, reason=reason, after_state=after
            ):
                return _unavailable()
        finally:
            await raise_break_event(
                verify_events, result, None if request_id is None else str(request_id)
            )
            await record_halt(break_halt, owed, result, "on_demand")
        return JSONResponse(status_code=200, content=_jsonable(result))

    @router.post("/chain-breaks/{firstBadId}/acknowledge")
    @_no_store
    async def acknowledge_audit_chain_break(
        request: Request, first_bad_id: Annotated[str, Path(alias="firstBadId")]
    ) -> JSONResponse:
        """`acknowledgeAuditChainBreak` (#2904) in 22's **Order of the checks**: `401`, `403
        forbidden` (Owner only, `admin.audit_denied`), the path and body (`422`), the no-grace
        `killswitch` step-up bound to this request, then the named break: `409` when this process
        holds no halt on it (`audit.chain_break_ack_denied`), `503 audit_unavailable` when the
        write-ahead `audit.chain_break_acknowledged` cannot be written (the halt stays)."""
        try:
            service, principal, _ = await _authorize_or_raise(request, "ack_break")
        except _HttpProblem as problem:
            return problem.response
        checked = await _ack_request(request, first_bad_id)
        if isinstance(checked, JSONResponse):
            return checked
        identity, body = checked
        if break_ack is None or step_up is None:  # a wiring fault: nothing is lifted (C-2.21)
            detail = "break acknowledgement not wired"
            return _problem(503, "Service unavailable", detail, code="service_unavailable")
        restated = f"Acknowledge the audit-chain break at entry {identity.object_id}"
        spent = await require_bound_elevation(
            step_up,
            principal.session_id,
            "killswitch",
            fingerprint=bound_fingerprint(
                request.method, raw_request_target(request), body.model_dump(mode="json")
            ),
            emitter=_StepUpEmitter(service.writer),
            text=ChallengeText(f"{restated} and resume order entry"),
        )
        if not isinstance(spent, SpentGrant):
            return spent
        ack = AckRequest(
            identity=identity,
            reason=body.reason,
            actor_user_id=principal.actor_id,
            actor_label=principal.actor_name,
            session_id=principal.session_id,
            actor_ip=principal.ip,
            request_id=principal.request_id,
            challenge_id=spent.challenge_id,
        )
        # Owner-ness follows `PrincipalSnapshot.is_owner` alone (SR-017), as the console's.
        owner = principal.is_owner
        outcome = await break_ack.acknowledge(ack, is_owner=owner, emit=service.writer.emit)
        if outcome is AckOutcome.NOT_ENGAGED:
            return _problem(409, "Conflict", "no halt is engaged on that break", code="conflict")
        if outcome is AckOutcome.NOT_OWNER:  # pragma: no cover - `authorize` refused non-Owners
            return _problem(403, "Forbidden", "owner only", code="forbidden")
        if outcome is AckOutcome.RECORD_FAILED:
            detail = "the acknowledgement could not be recorded; the halt stays"
            return _problem(
                503, "Service unavailable", detail, code="audit_unavailable", retry_after_s=1
            )
        content = {
            "first_bad_id": identity.first_bad_id,
            "kind": identity.kind,
            "halted": break_ack.halt.engaged,
        }
        return JSONResponse(status_code=200, content=content)

    async def _ack_request(
        request: Request, first_bad_id: str
    ) -> tuple[BreakIdentity, AuditBreakAckRequest] | JSONResponse:
        """The named break and the body, checked strictly; else the `422`, naming no value."""
        if (
            not (first_bad_id.isascii() and first_bad_id.isdigit())
            or int(first_bad_id) > _INT64_MAX
        ):
            return _rule("firstBadId", "int64", "firstBadId is not a non-negative integer")
        raw = await _read_capped(request, _ACK_BODY_MAX_BYTES)
        if raw is None:
            return _rule("", "max_body_bytes", f"the body is over {_ACK_BODY_MAX_BYTES} bytes")
        try:
            body = AuditBreakAckRequest.model_validate_json(raw)
        except ValidationError as exc:
            return _invalid(exc, AuditBreakAckRequest)
        return BreakIdentity(int(first_bad_id), str(body.kind)), body

    @router.get("/signing-keys")
    @_no_store
    async def list_audit_signing_keys(request: Request) -> JSONResponse:
        """`listAuditSigningKeys` (#889 S7, ADR-0039 decision 4): Owner only, as verify; a read of
        the audit area under the budget, as a filter set of its own (`admin.audit_read` naming
        `object_kind` `audit_signing_key`); each key's `verified` mark is M2's. Over the cap:
        `429`; a due record unwritten or the key store unreadable: `503`, nothing returned."""
        try:
            service, principal, _ = await _authorize_or_raise(request, "signing_keys")
        except _HttpProblem as problem:
            return problem.response
        plan = record_budget.plan_read(_budget_actor(principal), filters_digest(_SIGNING_KEYS))
        try:
            if plan.action == "refuse":
                return _over_cap(str(principal.actor_id))  # the actor's budget (#3085)
            if plan.action == "unwritable":
                return _unavailable()
            listed = None if signing_keys is None else await signing_keys.listing()
            if listed is None:
                return _unavailable("signing key store unavailable")
            items = [signing_key_view(key) for key in listed]
            if plan.action == "record":
                fields = _request_fields(principal) | {"object_kind": "audit_signing_key"}
                detail = {"filters": _SIGNING_KEYS, "returned_count": len(items)}
                try:
                    await record_budget.write_read(plan, service.writer, fields, detail)
                except BudgetWriteFailed:
                    return _unavailable()
            plan.commit()
            return JSONResponse(status_code=200, content={"items": items})
        finally:
            plan.release()  # a read that served nothing gives its reservation back

    @router.post("/export")
    @_no_store
    async def export_audit_log(request: Request) -> JSONResponse:
        """`exportAuditLog` (#889 S10, ADR-0039) in 22's **Order of the checks**: `401` and `403
        forbidden` before any body is read; validation (`422`, the `Idempotency-Key` too); the
        `audit` step-up (`HANDLER_GATED_ROUTES`, #2304 slice 3b: its challenge restates the
        validated window; no step-up service is `503`); the idempotency lookup (the stored `202`
        with `Idempotency-Replayed: true`, or `409 idempotency_key_reuse`); `503
        signing_unavailable`, recorded under the budget; the hourly
        `429` and single-flight's `409 conflict`, both counted; then the write-ahead
        `admin.audit_export` (`503 store_unavailable` when it cannot be written) and the `202`.
        The single-flight hold is taken before that record, so no rotation and no other export
        starts while it is written, and released just before the job is submitted, no `await`
        between them."""
        try:
            service, principal, _ = await _authorize_or_raise(request, "export")
        except _HttpProblem as problem:
            return problem.response
        checked = await _export_request(request)
        if isinstance(checked, JSONResponse):
            return checked
        raw, body, key = checked
        if step_up is None:  # a wiring fault: the export stays gated (C-2.21)
            return _problem(
                503, "Service unavailable", "step-up not wired", code="service_unavailable"
            )
        restated = export_audit_text(body.from_ts, body.to_ts, compress=body.compress)
        challenge = await require_session_elevation(
            step_up, principal.session_id, "audit", restated
        )
        if challenge is not None:
            return challenge
        actor, digest = _budget_actor(principal), request_fingerprint("POST", _EXPORT_PATH, raw)
        if exports is None:  # unwired: no job store and no signer
            return await _export_down(service, principal, "signing_unavailable")
        try:
            prior = exports.replayed(actor.key, key, digest)
        except IdempotencyKeyReuse:  # a `409`, counted as the other refusals are (22)
            record_budget.count_suppressed(actor)
            detail = "The key was first used with another request."
            return _problem(409, "Conflict", detail, code="idempotency_key_reuse")
        if prior is not None:
            return _scheduled(prior, replayed=True)
        if (why := await exports.unavailable()) is not None:
            return await _export_down(service, principal, why)
        if (wait := export_starts.retry_after(actor.key)) is not None:
            record_budget.count_suppressed(actor)
            detail = "audit export limit reached"
            return _problem(
                429, "Too many requests", detail, code="rate_limited", retry_after_s=wait
            )
        job_id, asked = uuid.uuid4(), ExportRequest(body.from_ts, body.to_ts, body.compress)
        fields, state = _export_fields(principal, str(job_id)), export_window(job_id, asked)
        try:
            release = exports.reserve()
        except JobConflict:
            record_budget.count_suppressed(actor)
            detail = "an audit export or a signing-key rotation is under way"
            return _problem(409, "Conflict", detail, code="conflict")
        try:  # from the hold on, nothing leaves without releasing it
            written = await write_verify_record(
                service.writer.emit, fields, outcome=_SUCCESS, severity=_INFO, reason="requested",
                after_state=state | {"compressed": body.compress}, action=EXPORT_ACTION,
            )  # fmt: skip
        finally:
            release()
        if not written:
            return _unavailable()
        export_starts.record_start(actor.key)  # only an export whose job is created counts
        exports.submit(
            service.query, service.writer.emit, fields, principal, asked, job_id=job_id, key=key,
            digest=digest,
        )  # fmt: skip
        return _scheduled(str(job_id))

    async def _export_request(
        request: Request,
    ) -> tuple[bytes, AuditExportRequest, uuid.UUID | None] | JSONResponse:
        """The body, read up to `_VERIFY_BODY_MAX_BYTES` and checked strictly, a window of at most
        `export_max_range_days`, and the `Idempotency-Key` as a UUID when sent; else the `422`,
        naming no value."""
        raw = await _read_capped(request, _VERIFY_BODY_MAX_BYTES)
        if raw is None:
            return _rule("", "max_body_bytes", f"the body is over {_VERIFY_BODY_MAX_BYTES} bytes")
        try:
            body = AuditExportRequest.model_validate_json(raw, strict=True)
        except ValidationError as exc:
            return _invalid(exc, AuditExportRequest)
        days = export_max_range_days
        if body.to_ts - body.from_ts > timedelta(days=days):
            detail = f"the window is longer than audit_export_max_range_days ({days})"
            return _rule("to", "max_export_range", detail)
        header = request.headers.get("idempotency-key")
        try:
            return raw, body, None if header is None else uuid.UUID(header)
        except ValueError:
            return _rule("Idempotency-Key", "uuid", "the Idempotency-Key is not a UUID")

    async def _export_down(
        service: AuditServiceLike, principal: AuditPrincipal, reason: str
    ) -> JSONResponse:
        """22: export alone is unavailable. `admin.audit_denied` naming why, under the audit
        budget (a slot of it, never the hourly export quota): over its cap the refusal carries
        `Retry-After`, and a record that cannot be written makes it `503 store_unavailable`."""
        actor = _budget_actor(principal)
        emitter = record_budget.emitter(service.writer, actor)
        denied = {"outcome": AuditOutcome.DENIED, "severity": _WARNING, "reason": reason}
        fields = _request_fields(principal) | {"object_kind": "audit_export"}
        try:
            await emitter.emit(DENIAL_ACTION, **fields, **denied)
        except BudgetWriteFailed:
            return _unavailable()
        retry = record_budget.retry_after(actor.key) if emitter.suppressed else None
        detail = f"{_EXPORT_DOWN[reason]} Export alone is unavailable."
        return _problem(
            503, "Service unavailable", detail, code="signing_unavailable", retry_after_s=retry
        )

    @router.get("/exports/{jobId}")
    @_no_store
    async def download_audit_export(
        request: Request, job_id: Annotated[str, Path(alias="jobId")]
    ) -> Response:
        """`downloadAuditExport` (#889 S9), in the order of 22 `exportAuditLog` **Download**:
        `401`, `403 forbidden`, the requester (`404`, as for an unknown or evicted job), the
        `audit` step-up, the hourly limit (`429`; the place is taken at the check, and a
        refusal frees it), expiry (`410`, the file deleted), the file (`503` when it cannot be
        served), then its write-ahead `admin.audit_export` (`downloaded`) before any byte. The
        `404`, `410` and that `503` are recorded as `admin.audit_denied` under the budget, and
        the `429` counted, as on `queryAuditLog`; a step-up refusal is a challenge, which the
        step-up service records (`auth.step_up_required`)."""
        try:
            service, principal, _ = await _authorize_or_raise(request, "export")
        except _HttpProblem as problem:
            return problem.response
        actor, fields = _budget_actor(principal), _export_fields(principal, job_id)
        emitter = record_budget.emitter(service.writer, actor)

        async def refused(
            reason: str, answer: JSONResponse, after: dict[str, Any] | None = None
        ) -> JSONResponse:
            """Recorded first, under the budget: over its cap answered with `Retry-After`."""
            denied = {"outcome": AuditOutcome.DENIED, "severity": _WARNING, "reason": reason}
            try:
                await emitter.emit(DENIAL_ACTION, **fields, **denied, after_state=after)
            except BudgetWriteFailed:
                return _unavailable()
            if emitter.suppressed:
                answer.headers["Retry-After"] = str(record_budget.retry_after(actor.key))
            return answer

        found = None if exports is None else exports.find(job_id, principal)
        if found is None or exports is None or step_up is None:  # unwired, nothing is served
            missing = _problem(404, "Not found", "No such export.", code="not_found")
            return await refused("export_not_found", missing)
        challenge = await require_session_elevation(step_up, principal.session_id, "audit")
        if challenge is not None:
            return challenge
        if (wait := downloads.retry_after(actor.key)) is not None:
            record_budget.count_suppressed(actor)
            detail = "audit download limit reached"
            return _problem(
                429, "Too many requests", detail, code="rate_limited", retry_after_s=wait
            )
        downloads.record_start(actor.key)  # taken at the check, so downloads in flight count
        response: Response | None = None
        try:
            if exports.expired(found):
                await exports.remove(found)
                gone = _problem(410, "Gone", "The export expired and was deleted.", code="gone")
                response = await refused("export_expired", gone)
            elif isinstance(file := await exports.open(found), str):
                detail = "the export file cannot be served"
                lost = _problem(503, "Service unavailable", detail, code="store_unavailable")
                if file == "store_unavailable":  # the reader's transient cause
                    lost.headers["Retry-After"] = "1"
                response = await refused("export_unservable", lost, {"artefact": file})
            else:
                response = await _serve(service, found, file, fields)
            return response
        finally:
            if not isinstance(response, ExportFileResponse):
                downloads.release(actor.key)  # a refusal frees its place

    async def _serve(
        service: AuditServiceLike, export: Export, file: ResolvedArtefact, fields: dict[str, Any]
    ) -> Response:
        """The file, once its write-ahead `admin.audit_export` (`downloaded`) is written (C-2.9),
        straight to the writer as verify's are; unwritten (`503`), or cancelled while pending, the
        file is closed here, never left to the collector."""
        served = False
        try:
            if await write_verify_record(
                service.writer.emit, fields, outcome=_SUCCESS, severity=_INFO,
                reason="downloaded", action="admin.audit_export",
                after_state={"sha256": export.manifest.sha256, "size_bytes": file.size},
            ):  # fmt: skip
                response = ExportFileResponse(export, file)
                served = True  # the response owns the file from here
                return response
            return _unavailable()
        finally:
            if not served:
                file.close()

    return router


def _jsonable(model: Any) -> dict[str, Any]:
    """`model_dump(mode="json")` renders `datetime`/`UUID`/enum fields as
    plain JSON-safe types (`JSONResponse` does not run pydantic's encoder)."""
    dumped: dict[str, Any] = model.model_dump(mode="json")
    return dumped


__all__ = ["PrincipalResolver", "make_audit_router"]
