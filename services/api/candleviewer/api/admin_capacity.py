"""`PUT /admin/capacity/subaccount-tier` (E42-T01; contract `setSubaccountTier`, `x-rbac:
admin:write`, scope none, `x-idempotency: ignored`): the one way to record the exchange's
sub-account tier, a fact that is never inferred (US-ADMIN-014).

The audited admin router (`candleviewer.admin.http`) has already refused an anonymous caller (401)
and one without `admin:write` (403, the denial's own audit row), so the body is read and the store
touched only for the owner. Then:

1. the body is read (capped) and checked against the closed schema, or 422;
2. no store wired or an unreachable one: 503 `store_unavailable`, a fixed detail;
3. one store transaction writes the row and, before its commit, the `settings.change` record with
   the tier before and after (write-ahead, C-2.9). A record that cannot be written refuses the
   change: 503 `audit_unavailable`, the tier unchanged. A COMMIT that fails after the append can
   leave a record for an unchanged tier: the trail over-reports, never under-reports;
4. whatever the outcome, the cached `subaccounts` slice is dropped (read-after-write);
5. the answer is the `SubaccountCapacity` block from the committed row and a fresh `used`.

`Idempotency-Key` is never read: a repeat with the same tier is a new write, audited with
before == after. No step-up (the contract says why).
"""

from __future__ import annotations

from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from candleviewer.admin.http import PrincipalResolver, admin_router
from candleviewer.admin.overview.capacity import AdminCapacityService, Tier
from candleviewer.admin.overview.ports import SUBACCOUNT_TIER_KEY
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.admin_overview import subaccounts_payload
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.observability.redaction import redact_structure, redact_text
from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories.system_settings import StoredSetting, SystemSettings
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

#: The body is `{"tier": "<one of two words>"}`: far below this, so anything over it is no request.
MAX_BODY_BYTES: Final = 1024
_RETRY_AFTER_S: Final = 5
#: The registered problem codes this route emits (`x-error-codes`: title and retryability come
#: from the generated registry) and the status each carries here.
_STATUS: Final = {
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.STORE_UNAVAILABLE: 503,
    ErrorCode.AUDIT_UNAVAILABLE: 503,
}


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


# The closed request body of the contract: `additionalProperties: false`, `tier` required.
# (No docstring: pydantic would publish it as the schema's `description`.)
class TierRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tier: Tier


class _Problem(Exception):
    """An RFC 9457 problem for a registered code; a retryable one says when to retry."""

    def __init__(self, code: ErrorCode, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.code, self.detail, self.extra = code, detail, extra

    def response(self) -> JSONResponse:
        status, meta = _STATUS[self.code], ERROR_META[self.code]
        body: dict[str, Any] = {
            "type": f"https://candleviewer.local/errors/{self.code.value}",
            "title": meta.title,
            "status": status,
            "code": self.code.value,
            "detail": self.detail,
            **self.extra,
        }
        headers: dict[str, str] = {}
        if meta.retryable:
            body["retry_after_seconds"] = _RETRY_AFTER_S
            headers["Retry-After"] = str(_RETRY_AFTER_S)
        return JSONResponse(body, status, headers, "application/problem+json")


class _AuditRefused(Exception):
    """The write-ahead record could not be written; the store rolled the change back."""


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _invalid(*errors: dict[str, str]) -> _Problem:
    return _Problem(ErrorCode.VALIDATION_FAILED, "The request is invalid.", errors=list(errors))


async def _body(request: Request) -> TierRequest:
    """The request body, read only up to the cap. A wrong one is never echoed back: no value, and
    no key name either (an unknown key is reported on the body as a whole, `field` empty)."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            msg = f"The body exceeds {MAX_BODY_BYTES} bytes."
            raise _invalid({"field": "", "rule": "body_too_large", "message": msg})
    try:
        return TierRequest.model_validate_json(bytes(raw))
    except ValidationError as exc:
        found = [
            {
                "field": "" if e["type"] == "extra_forbidden" else ".".join(map(str, e["loc"])),
                "rule": e["type"],
                "message": redact_text(e["msg"]),
            }
            for e in exc.errors()
        ]
        raise _invalid(*redact_structure(found[:20])) from None


def make_admin_capacity_router(
    capacity: AdminCapacityService,
    store: SystemSettings | None,
    *,
    resolver: PrincipalResolver | None,
    audit: _Emitter,
) -> APIRouter:
    router = admin_router(Permission.ADMIN_WRITE, resolver=resolver, audit=audit)

    @router.put("/capacity/subaccount-tier")
    async def set_subaccount_tier(request: Request) -> JSONResponse:
        # The handler itself writes the audit record (write-ahead, below): C-2.9.
        try:
            principal: AuditPrincipal = request.state.admin_principal  # left there by the guard
            wanted = await _body(request)
            if store is None:
                raise _Problem(ErrorCode.STORE_UNAVAILABLE, "The settings store is unavailable.")

            async def write_ahead(before: StoredSetting | None) -> None:
                try:
                    await audit.emit(
                        "settings.change",
                        actor_label=principal.username,
                        actor_user_id=principal.user_id,
                        actor_ip=principal.ip,
                        session_id=principal.session_id,
                        object_kind="setting",
                        object_id=SUBACCOUNT_TIER_KEY,
                        outcome=AuditOutcome.SUCCESS,
                        severity=Severity.INFO,
                        reason=None,
                        before_state={"tier": None if before is None else before.value},
                        after_state={"tier": wanted.tier},
                        request_id=principal.request_id,
                    )
                except Exception as exc:
                    # any failure to make the record durable refuses the change
                    raise _AuditRefused from exc

            try:
                stored = await store.put_string(
                    SUBACCOUNT_TIER_KEY,
                    wanted.tier,
                    updated_by=principal.user_id,
                    write_ahead=write_ahead,
                )
            except (_AuditRefused, WriteAheadTimeout) as exc:
                # listed before `OSError` below: a write-ahead timeout is also a `TimeoutError`
                cause = exc.__cause__ if isinstance(exc, _AuditRefused) else exc
                _log().error(
                    "admin_tier_audit_failed",
                    error=type(cause).__name__,
                    actor_user_id=principal.user_id,
                    request_id=principal.request_id,
                )
                detail = "The audit record could not be written; the tier is unchanged."
                raise _Problem(ErrorCode.AUDIT_UNAVAILABLE, detail) from None
            except (OSError, StorageTierUnavailable) as exc:
                _log().error("admin_tier_store_unavailable", error=type(exc).__name__)
                msg = "The settings store is unavailable."
                raise _Problem(ErrorCode.STORE_UNAVAILABLE, msg) from None
            finally:
                # also after a failure: the outcome may be unknown
                capacity.invalidate_subaccounts()
            result = await capacity.subaccounts_recorded(wanted.tier, stored.updated_at)
            shown = api.SubaccountCapacity.model_validate(subaccounts_payload(result))
            return JSONResponse(shown.model_dump(mode="json", exclude_unset=True))
        except _Problem as problem:
            return problem.response()

    return router
