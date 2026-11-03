"""`POST /settings/hotkey-audit`: server-side audit of destructive rebinds (E49-S07, C-2.9).

Actor, session and request id come from the verified session principal, never the body.
Requires `settings:write` (C-12.4). Fails closed: 501 unwired, 401 no session, 403 lacking
permission, 503 if the audit record cannot be made durable.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from candleviewer.api.problems import problem
from candleviewer.audit.errors import AuditError
from candleviewer.domain.text import refuse_unstorable_text
from candleviewer.ws._generated.error_codes import ErrorCode

ACTION = "hotkey.trading_binding_changed"
_ID = r"^[a-z0-9_]+([.][a-z0-9_]+){1,3}$"


class HotkeyBindingAuditInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    command_id: str = Field(pattern=_ID, max_length=64)
    before: str = Field(max_length=64)
    after: str = Field(max_length=64)
    acknowledged_unsafe: bool

    @field_validator("before", "after")
    @classmethod
    def _storable_binding(cls, value: str) -> str:
        return refuse_unstorable_text(value)


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _Resolver(Protocol):
    async def resolve(self, request: Request) -> Any: ...


def make_hotkey_audit_router(emitter: _Emitter | None, resolver: _Resolver | None) -> APIRouter:
    router = APIRouter(tags=["settings"])

    @router.post("/settings/hotkey-audit")
    async def record(request: Request) -> Response:
        if emitter is None or resolver is None:
            return problem(ErrorCode.NOT_IMPLEMENTED, 501, "hotkey audit not wired")
        principal = await resolver.resolve(request)
        if principal is None:
            return problem(ErrorCode.UNAUTHENTICATED, 401, "no verified session for this request")
        if "settings:write" not in principal.permissions:
            return problem(ErrorCode.FORBIDDEN, 403, "settings:write required")
        try:
            body = HotkeyBindingAuditInput.model_validate_json(await request.body())
        except ValidationError:
            return problem(ErrorCode.VALIDATION_FAILED, 422, "invalid hotkey audit payload")
        try:
            await emitter.emit(
                ACTION,
                actor_label=principal.username,
                actor_user_id=principal.user_id,
                actor_ip=principal.ip,
                session_id=principal.session_id,
                request_id=principal.request_id,
                object_kind="hotkey_binding",
                object_id=body.command_id,
                before_state={"binding": body.before},
                after_state={
                    "binding": body.after,
                    "acknowledged_unsafe": body.acknowledged_unsafe,
                },
            )
        except AuditError:
            return problem(ErrorCode.AUDIT_UNAVAILABLE, 503, "the action could not be audited")
        return Response(status_code=204)

    return router
