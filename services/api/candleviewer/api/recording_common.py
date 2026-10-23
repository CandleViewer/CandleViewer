"""Shared by the `/recording/*` routes (E16-T08, #492): the caller and RBAC (`auth.scopes.enforce`,
a denial audited as `rbac.denied`), problems that always carry `code`, and a bound cursor. Until
positions carry an account (E29-T06), everyone but the Owner reads the restricted view (R-I2,
ruling Q6), which `recorder.control` defines for the routes and the WS topic alike."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from candleviewer.api.recorder_admin import _Emitter, _PrincipalResolver
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

CURSOR_TTL_S: Final = 3600
Emitter = _Emitter  # the recorder routes' audit and session ports
Resolver = _PrincipalResolver
_SYMBOL: Final = re.compile(r"[A-Z0-9]{2,20}")  # what the server issues as a cursor key
_PERMISSIONS: Final = {p.value: p for p in Permission}


class Problem(Exception):
    """An RFC 9457 problem; its title is the `x-error-codes` catalogue's."""

    def __init__(self, status: int, code: ErrorCode, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra

    def response(self) -> JSONResponse:
        code = self.code.value
        body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code}", "code": code}
        body |= {"title": ERROR_META[self.code].title, "status": self.status, "detail": self.detail}
        return JSONResponse(body | self.extra, self.status, media_type="application/problem+json")


def iso_z(value: Any) -> Any:
    """A datetime as the contract's UTC `Z` string; anything else unchanged."""
    return value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value


def unavailable() -> Problem:
    return Problem(503, ErrorCode.STORE_UNAVAILABLE, "The recording store is unavailable.")


class ProblemRoute(APIRoute):
    """`Problem` -> its response; a store outage or a refused audit write -> 503, failing closed."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except Problem as problem:
                return problem.response()
            except Exception as exc:
                audit = isinstance(exc, AuditUnavailable | AuditWriterStopped)
                if not audit and not is_storage_outage(exc):
                    raise
                log = structlog.get_logger("candleviewer.api.recording")
                log.error("recording_store_unavailable", error=type(exc).__name__)
            return unavailable().response()

        return handler


async def caller(
    resolver: Resolver | None, audit: Emitter, request: Request, permission: Permission
) -> AuditPrincipal:
    """The session's principal: 401 without one (or no resolver), 403 without `permission`."""
    p = None if resolver is None else await resolver.resolve(request)
    if p is None:
        raise Problem(401, ErrorCode.UNAUTHENTICATED, "No verified session for this request.")
    granted = frozenset(_PERMISSIONS[c] for c in p.permissions if c in _PERMISSIONS)
    snapshot = PrincipalSnapshot(p.user_id, frozenset({"owner"} if p.is_owner else ()), granted)
    try:
        await enforce(snapshot, permission, emitter=audit, actor_ip=p.ip,
                      session_id=p.session_id, request_id=p.request_id)  # fmt: skip
    except ForbiddenError:
        raise Problem(403, ErrorCode.FORBIDDEN, f"Requires {permission.value}.",
                      required_permissions=[permission.value]) from None  # fmt: skip
    return p


def encode_cursor(scope: str, after: tuple[str, str], now: int) -> str:
    raw = json.dumps({"v": 1, "q": scope, "a": after, "iat": now})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, scope: str, now: int) -> tuple[str, str]:
    """The key of a cursor issued for this query (`scope`) in the last hour, else 400. The key
    must look like a symbol, so no other text reaches the text bind of the page query."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        key, after = data["a"]
        fresh = type(data["iat"]) is int and 0 <= now - data["iat"] <= CURSOR_TTL_S
        symbol = isinstance(key, str) and _SYMBOL.fullmatch(key) is not None
        if (data["v"], data["q"]) == (1, scope) and fresh and symbol:
            return key, str(UUID(after))
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    raise Problem(400, ErrorCode.INVALID_CURSOR, "The cursor is malformed, expired or foreign.")
