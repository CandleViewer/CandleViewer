"""`GET /admin/audit`, `POST /admin/audit/verify`, `POST /admin/audit/export`
(E09-T02 acceptance criteria: "Endpoints ... `GET /admin/audit` ... `POST
/admin/audit/verify` ... `POST /admin/audit/export`").

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

import hashlib
import time
from datetime import datetime
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
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
from candleviewer.api.audit_limiter import AuditQueryLimiter, AuditQueryRefused
from candleviewer.api.audit_verify import (
    observe_stop,
    observe_verify,
    result_record,
    write_verify_record,
)
from candleviewer.audit.access import (
    AuditAccessDenied,
    AuditPrincipal,
    AuditView,
    authorize,
    redact_entry_for_view,
)
from candleviewer.audit.cursor import AuditCursor, InvalidAuditCursor, decode_cursor
from candleviewer.audit.hashing import ChainHasherBusy
from candleviewer.audit.models import (
    AUDIT_QUERY_DEFAULT_LIMIT,
    AuditOutcome,
    AuditQueryRequest,
    AuditVerifyRequest,
    Severity,
)
from candleviewer.audit.query import VERIFY_MAX_SPAN, VerifyPlan, VerifyRangeBeyondHead
from candleviewer.observability.audit_query_metrics import cv_audit_query_duration_seconds
from candleviewer.storage.errors import StorageTierUnavailable


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
    ) -> Any: ...

    async def plan_verify(
        self, *, from_id: int | None, to_id: int | None, max_span: int = ...
    ) -> VerifyPlan: ...

    async def run_verify(self, plan: VerifyPlan, *, batch_size: int = ...) -> Any: ...


class AuditWriterLike(_Emitter, Protocol):
    """Only the `emit()` subset `authorize()` needs to record a denial."""


class AuditServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def query(self) -> AuditQueryServiceLike: ...

    @property
    def writer(self) -> AuditWriterLike: ...


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
#: Contract (`queryAuditLog`): a `200` page is never cached; it carries IPs and payloads.
_NO_STORE: Final = {"Cache-Control": "no-store"}


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


#: The verify body holds two ids at most; a longer one is refused without reading the rest.
_VERIFY_BODY_MAX_BYTES = 1024


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


#: Why a verify stopped early: the record's reason and the 503 detail. A store error carries
#: only its SQLSTATE and is logged where it is raised.
_VERIFY_STOPS: tuple[tuple[type[Exception], str, str], ...] = (
    (TimeoutError, "timeout", "audit verify exceeded its time budget"),
    (ChainHasherBusy, "hasher_busy", "audit read capacity reached"),
    (StorageTierUnavailable, "store_unavailable", "audit store unavailable"),
)
_VERIFY_STOP_ERRORS = tuple(kind for kind, _, _ in _VERIFY_STOPS)
_SUCCESS, _FAILURE = AuditOutcome.SUCCESS, AuditOutcome.FAILURE
_INFO, _WARNING = Severity.INFO, Severity.WARNING


def _verify_stop(exc: Exception) -> tuple[str, str]:
    return next((reason, detail) for kind, reason, detail in _VERIFY_STOPS if isinstance(exc, kind))


def _budget_actor(principal: AuditPrincipal) -> BudgetActor:
    # The Owner's cap and tracked entry follow the resolved `is_owner` only
    # (`PrincipalSnapshot.is_owner`, SR-017), never a role name or a grant.
    owner = principal.is_owner
    return BudgetActor(str(principal.user_id), principal.username, principal.user_id, owner)


def _request_fields(principal: AuditPrincipal) -> dict[str, Any]:
    return {
        "actor_label": principal.username,
        "actor_user_id": principal.user_id,
        "actor_ip": principal.ip,
        "session_id": principal.session_id,
        "object_kind": "audit_log",
        "request_id": principal.request_id,
    }


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
) -> APIRouter:
    """Bind `/admin/audit*` to a concrete `AuditService` instance.

    `audit_service=None` (fake/CI-default backend, mirrors `AuthService`'s
    own optionality) and `principal_resolver=None` (no session module wired
    yet) both degrade to `503`/`501` responses rather than raising at import
    time, so `create_app()` stays constructible with fakes only (C-2.16-
    adjacent: the router itself never touches a datastore or the network).

    Read and refusal records go through `budget` (contract "Audit budget"): a record
    over the user's cap is counted instead, which makes a read `429` and leaves a
    refusal unchanged but for `Retry-After`; a due record that cannot be written makes
    the call `503` with nothing returned (C-2.9).

    A Viewer holds no `audit:read` and gets `403` on every route here, as decided on
    #2083. Whether C-12.4's "Viewer (read-only, including audit)" should change that is
    the owner's decision on #2428 (design D7); nothing in this router grants it.
    """
    router = APIRouter(prefix="/admin/audit", tags=["admin"])
    query_limiter = limiter if limiter is not None else AuditQueryLimiter()
    record_budget = budget if budget is not None else AuditRecordBudget()

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
            raise _HttpProblem(_forbidden(str(principal.user_id), emitter, str(exc))) from exc
        return audit_service, principal, view

    @router.get("")
    async def query_audit_log(
        request: Request,
        actor_user_id: str | None = None,
        # Without `Query()` a list parameter is read from a JSON body, even on a GET.
        action: Annotated[list[str] | None, Query()] = None,
        subject_type: str | None = None,
        outcome: str | None = None,
        severity: str | None = None,
        # `from` is a Python keyword; the OpenAPI contract (22-api-openapi.yaml) names
        # the query parameter `from`, so alias it — without the alias `?from=` was
        # silently ignored and the lower time bound dropped.
        from_: Annotated[datetime | None, Query(alias="from")] = None,
        to: datetime | None = None,
        cursor: str | None = None,
        limit: int = AUDIT_QUERY_DEFAULT_LIMIT,
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
                    "limit": limit,
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
                if req.actor_user_id not in (None, actor.key):
                    refused = await _record_cross_actor(emitter, principal, req.actor_user_id)
                    if refused is not None:
                        return refused
                # SR-067: a non-owner reads only its own events. The repository applies
                # the scope in the SQL of every page, whatever `actor_user_id` was sent.
                filters["actor_user_id"] = actor.key
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
        return _forbidden(str(principal.user_id), emitter, "filter not permitted for this caller")

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
        return _over_cap(str(principal.user_id)) if emitter.suppressed else None

    async def _run_query(
        service: AuditServiceLike,
        principal: AuditPrincipal,
        view: AuditView,
        filters: dict[str, Any],
        after: AuditCursor | None,
        plan: ReadReservation,
        recorded: dict[str, Any],
    ) -> JSONResponse:
        key = str(principal.user_id)
        if plan.action == "refuse":
            return _over_cap(key)
        if plan.action == "unwritable":
            return _unavailable()
        # Fail closed: any view but the Owner's raw one is scoped to the caller's own entries.
        restrict = None if view is AuditView.RAW else key
        started = time.perf_counter()
        try:
            page = await service.query.query(
                **filters,
                restrict_to_actor=restrict,
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
        return JSONResponse(status_code=200, content=_jsonable(page), headers=_NO_STORE)

    @router.post("/verify")
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
        except _VERIFY_STOP_ERRORS as exc:
            return _unavailable(_verify_stop(exc)[1])
        return await _run_verify(service, principal, plan)

    async def _run_verify(
        service: AuditServiceLike, principal: AuditPrincipal, plan: VerifyPlan
    ) -> JSONResponse:
        """Write-ahead `started` record, the run, then its result record (#2392). The
        records go straight to the writer, never through the budget; one that cannot be
        written makes the call 503 and serves nothing. A run that stops early is recorded
        as failure/warning with the reason it stopped (`internal_error` for anything
        unexpected, also 503), and a full-range stop turns a chain gauge of 1 into NaN (0
        stays until a full-range run passes); a cancellation propagates."""
        emit, fields = service.writer.emit, _request_fields(principal)
        span = {"from_id": plan.from_id, "to_id": plan.to_id}
        if not await write_verify_record(
            emit, fields, outcome=_SUCCESS, severity=_INFO, reason="started", after_state=span
        ):
            return _unavailable()
        try:
            result = await service.query.run_verify(plan)
        except _VERIFY_STOP_ERRORS as exc:
            observe_stop(full_chain=plan.full_chain)
            reason, detail = _verify_stop(exc)
            await write_verify_record(
                emit, fields, outcome=_FAILURE, severity=_WARNING, reason=reason, after_state=span
            )
            return _unavailable(detail)
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
        observe_verify(result)  # the chain series follow the run, recorded or not
        outcome, severity, reason, after = result_record(result)
        if not await write_verify_record(
            emit, fields, outcome=outcome, severity=severity, reason=reason, after_state=after
        ):
            return _unavailable()
        return JSONResponse(status_code=200, content=_jsonable(result))

    @router.post("/export")
    async def export_audit_log(request: Request) -> JSONResponse:
        """Deliberate stub until owner decision D1 (export signing-key custody,
        E42-T02 design §6.3, #889). Authorisation runs first (401/403), then
        `501 not_implemented`. No body is parsed (no pre-auth 422), no job or
        artefact is created and no `admin.audit_export` record is written, since
        nothing is exported. The `202` job flow arrives with the export slice."""
        try:
            await _authorize_or_raise(request, "export")
        except _HttpProblem as problem:
            return problem.response
        return _problem(
            501, "Not implemented", "Audit export is not available yet.", code="not_implemented"
        )

    return router


def _jsonable(model: Any) -> dict[str, Any]:
    """`model_dump(mode="json")` renders `datetime`/`UUID`/enum fields as
    plain JSON-safe types (`JSONResponse` does not run pydantic's encoder)."""
    dumped: dict[str, Any] = model.model_dump(mode="json")
    return dumped


__all__ = ["PrincipalResolver", "make_audit_router"]
