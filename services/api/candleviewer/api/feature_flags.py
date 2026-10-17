"""`GET /admin/feature-flags` and `PUT /admin/feature-flags/{flagKey}` (E42-T03; contract
`listFeatureFlags` and `setFeatureFlag`, `flags:read` and `flags:write`, scope none).

Both sit on the audited admin router (`candleviewer.admin.http`), which refuses an anonymous caller
(401) and one without the permission (403, the denial's own audit row) before a handler runs. A
flag resolves for the caller's role: `owner`, or none, as `AuditPrincipal` carries no role names.

The list is `FlagService.visible()`, each flag through the generated `FeatureFlag` model. A write
reads its body only up to `MAX_BODY_BYTES` (`422 body_too_large`: the contract declares no 413),
refuses, as input hygiene, a body nested deeper than any write or holding NaN, an infinity, a
control, zero-width or bidi character or a lone surrogate, checks it against the generated
`SetFeatureFlagRequest`, then hands it to `FlagWriter`, which takes the row lock, validates against
the flag, demands the step-up and writes. A key the caller cannot see is a 404. Every refusal past
the guard is audited as `flags.change`: the writer records its own, the route a body it refused,
with the key and the rule only, never the body; a refusal that cannot be recorded is
`503 audit_unavailable`. A store outage under the lock, the users' or the step-up's included, is
`503 store_unavailable`.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Final, Protocol, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from candleviewer.admin.flags import (
    FlagConflictError,
    FlagService,
    FlagsWriteDenied,
    FlagValidationError,
    FlagWriter,
    ResolvedFlag,
    StoreUnavailableError,
)
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.step_up import StepUpRefused
from candleviewer.api.step_up_challenge import raw_request_target, request_fingerprint
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

#: An overrides list of about 200 users fits; anything longer is no flag write.
MAX_BODY_BYTES: Final = 16 * 1024
#: A write nests three deep (the body, `overrides`, an override); deeper is `json_invalid`.
_MAX_DEPTH: Final = 8
#: Control characters, zero-width and bidi formatting ones, and the lone surrogates
#: `.encode("utf-8")` refuses, in any string or key (a record must not render as other text).
_REFUSED: Final = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
_RETRY_AFTER_S: Final = 5
#: `flagKey` as the contract's path parameter declares it.
_KEY: Final = re.compile(r"[a-z0-9]+(\.[a-z0-9_]+)+")
#: `flagKey` for the OpenAPI document only: the handler reads the raw segment, so a malformed key
#: gets its audited 404, never FastAPI's own 422.
_KEY_DOC: Final = {"name": "flagKey", "in": "path", "required": True, "schema": {"type": "string"}}
_NOT_AUDITED: Final = "The audit record could not be written; nothing was changed."
_STATUS: Final = {
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.STORE_UNAVAILABLE: 503,
    ErrorCode.AUDIT_UNAVAILABLE: 503,
}


class FlagsRuntime(Protocol):
    """What the routes use of the composition root's flag runtime."""

    service: FlagService
    writer: FlagWriter


class _Problem(Exception):
    def __init__(self, code: ErrorCode, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.code, self.detail, self.extra = code, detail, extra

    def response(self) -> JSONResponse:
        status, meta = _STATUS[self.code], ERROR_META[self.code]
        body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{self.code.value}"}
        body |= {"title": meta.title, "status": status, "code": self.code.value}
        body |= {"detail": self.detail, **self.extra}
        headers: dict[str, str] = {}
        if meta.retryable:
            body["retry_after_seconds"] = _RETRY_AFTER_S
            headers["Retry-After"] = str(_RETRY_AFTER_S)
        return JSONResponse(body, status, headers, "application/problem+json")


def _invalid(field: str, rule: str) -> _Problem:
    errors = [{"field": field, "rule": rule}]
    return _Problem(ErrorCode.VALIDATION_FAILED, "The request is invalid.", errors=errors)


def _roles(principal: AuditPrincipal) -> frozenset[str]:
    return frozenset({"owner"}) if principal.is_owner else frozenset()


def _shown(item: ResolvedFlag) -> dict[str, Any]:
    flag = api.FeatureFlag.model_validate(item.members())
    return flag.model_dump(mode="json", exclude_unset=True)


def _rule(doc: object) -> str | None:
    """The input-hygiene rule a parsed body breaks, if any, walked with an explicit stack so no
    nesting recurses: deeper than `_MAX_DEPTH`, a refused character in a string or a key, or a float
    that is not finite."""
    stack: list[tuple[object, int]] = [(doc, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_DEPTH:
            return "json_invalid"
        if isinstance(node, str) and _REFUSED.search(node):
            return "invalid_character"
        if isinstance(node, float) and not math.isfinite(node):  # `1e999` parses to infinity
            return "json_invalid"
        if isinstance(node, dict):
            stack += [(part, depth + 1) for item in node.items() for part in item]
        elif isinstance(node, list):
            stack += [(part, depth + 1) for part in node]
    return None


def _no_constant(name: str) -> object:
    raise ValueError(name)  # NaN, Infinity and -Infinity are not JSON (RFC 8259)


async def _body(request: Request) -> tuple[api.SetFeatureFlagRequest, dict[str, Any]]:
    """The request body read up to the cap, checked against the contract; never echoed back."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            raise _invalid("", "body_too_large")
    try:
        doc: Any = json.loads(raw, parse_constant=_no_constant)
    except (ValueError, RecursionError):  # the parser's own nesting limit included
        raise _invalid("", "json_invalid") from None
    if (rule := _rule(doc)) is not None:
        raise _invalid("", rule)
    try:
        body = api.SetFeatureFlagRequest.model_validate(doc)
    except ValidationError as exc:
        first = exc.errors()[0]  # an unknown member's name is echoed, cut to 128 characters
        raise _invalid(".".join(map(str, first["loc"]))[:128], first["type"]) from None
    users = [o.user_id for o in body.overrides or ()]
    if len(set(users)) != len(users):
        raise _invalid("overrides", "duplicate_user")
    return body, cast(dict[str, Any], doc)


def make_feature_flags_routers(
    flags: FlagsRuntime, *, resolver: PrincipalResolver | None, audit: AuditEmitter
) -> tuple[APIRouter, APIRouter]:
    read = admin_router(Permission.FLAGS_READ, resolver=resolver, audit=audit)
    write = admin_router(Permission.FLAGS_WRITE, resolver=resolver, audit=audit)

    @read.get("/feature-flags")
    async def list_feature_flags(request: Request) -> JSONResponse:
        who: AuditPrincipal = request.state.admin_principal
        listed = await flags.service.visible(who.user_id, _roles(who))
        items = [_shown(item) for item in listed.items]
        return JSONResponse({"resolution": listed.resolution.value, "items": items})

    async def refused(who: AuditPrincipal, key: str, rule: str, action: str) -> None:
        try:
            await audit.emit(
                action,
                actor_label=who.username,
                actor_user_id=who.user_id,
                actor_ip=who.ip,
                session_id=who.session_id,
                object_kind="feature_flag",
                object_id=key,
                outcome=AuditOutcome.DENIED if action == "rbac.denied" else AuditOutcome.FAILURE,
                severity=Severity.WARNING,
                reason=rule,
                after_state={"result": rule},
                request_id=who.request_id,
            )
        except AuditError:  # a refusal that cannot be recorded is not answered (C-2.9)
            raise _Problem(ErrorCode.AUDIT_UNAVAILABLE, _NOT_AUDITED) from None

    async def audit_write(request: Request, key: str) -> JSONResponse:
        who: AuditPrincipal = request.state.admin_principal
        known = _KEY.fullmatch(key) is not None and len(key) <= 80
        spec, roles = flags.service.registry.get(key) if known else None, _roles(who)
        if spec is None or not spec.visible_to(roles):  # a key the caller cannot see is none
            await refused(who, key if known else "<invalid>", "not_found", "flags.change")
            raise _Problem(ErrorCode.NOT_FOUND, "No such feature flag.")
        try:
            body, doc = await _body(request)
        except _Problem as problem:
            rule = problem.extra["errors"][0]["rule"]
            await refused(who, key, rule, "flags.change")
            raise
        target = raw_request_target(request)  # a no-grace grant binds to this very request
        try:
            fingerprint: str | None = request_fingerprint(request.method, target, doc)
        except (ValueError, TypeError):  # not I-JSON: only a body the writer refuses is not
            fingerprint = None
        overrides = None if body.overrides is None else {o.user_id: o.value for o in body.overrides}
        try:
            after = await flags.writer.set(
                key,
                who,
                value=body.value,
                reason=body.reason,
                expected_updated_at=body.expected_updated_at,
                evidence_url=doc.get("evidence_url"),  # as sent: the model normalises a URL
                user_overrides=overrides,
                fingerprint=fingerprint,
            )
        except FlagsWriteDenied:
            await refused(who, key, "missing_permission:flags:write", "rbac.denied")
            raise _Problem(ErrorCode.FORBIDDEN, "requires flags:write") from None
        except FlagValidationError as exc:
            raise _invalid(exc.field, exc.rule) from None
        except FlagConflictError as exc:
            row = flags.service.resolved(spec, exc.current, who.user_id, roles)
            detail = f"{key} changed after it was read."
            raise _Problem(ErrorCode.CONFLICT, detail, current=_shown(row)) from None
        except AuditError:
            raise _Problem(ErrorCode.AUDIT_UNAVAILABLE, _NOT_AUDITED) from None
        except Exception as exc:  # the flag store, or the users' or step-up's under the lock
            if not isinstance(exc, StoreUnavailableError) and not is_storage_outage(exc):
                raise
            raise _Problem(ErrorCode.STORE_UNAVAILABLE, "The flag store is unavailable.") from None
        shown = flags.service.resolved(spec, after, who.user_id, roles)
        return JSONResponse(_shown(shown))

    @write.put("/feature-flags/{flagKey}", openapi_extra={"parameters": [_KEY_DOC]})
    async def set_feature_flag(request: Request) -> JSONResponse:
        try:
            return await audit_write(request, request.path_params["flagKey"])
        except _Problem as problem:
            return problem.response()
        except StepUpRefused as refusal:  # the step-up port's own problem
            return refusal.response

    return read, write


__all__ = ["MAX_BODY_BYTES", "FlagsRuntime", "make_feature_flags_routers"]
