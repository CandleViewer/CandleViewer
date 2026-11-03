"""Secret-safe error responses (E43-T06, SR-006/SR-069).

FastAPI's default 422 body echoes the offending ``input``; an unhandled
exception otherwise surfaces its message. Both handlers pass everything through
the single observability redaction rule set so a secret-shaped value in a
request payload can never leave through the error path.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from candleviewer.api.storage_outage import is_storage_outage, sqlstate_of
from candleviewer.observability.redaction import redact_structure, redact_text
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Seconds a client waits before retrying a store outage; as the routers' own 503 (`Retry-After`).
_RETRY_AFTER_S = 5
_PROBLEM = "application/problem+json"
_BASE = "https://candleviewer.local/errors/"
#: Constant validation messages (C-12.6), keyed by pydantic error type: the types whose `msg`
#: quotes the input itself. Closed list, pinned by `tests/unit/api/test_validation_constants.py`,
#: which proves the path, query and body scalar types and the discriminated union it probes.
#: `value_error`, `assertion_error`, `json_invalid` and `url_parsing` carry author-controlled
#: text; no mounted FastAPI-parsed body model interpolates the input today, and the raw-body
#: routes (drawings, workspaces) answer through their own `format_errors`.
CONSTANT_MESSAGES: dict[str, str] = {
    "uuid_parsing": "Input should be a valid UUID.",
    "union_tag_invalid": "Input tag does not match any of the expected tags.",
}


def _problem(status: int, code: str, title: str, **extra: Any) -> JSONResponse:
    """RFC 9457 body matching components.schemas.Problem (22-api-openapi.yaml)."""
    body: dict[str, Any] = {
        "type": f"{_BASE}{code}",
        "title": title,
        "status": status,
        "code": code,
        **extra,
    }
    return JSONResponse(status_code=status, content=body, media_type=_PROBLEM)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return await unhandled_error_handler(request, exc)
    errors = [
        {
            "field": ".".join(str(p) for p in err.get("loc", ())),
            "rule": str(err.get("type", "value_error")),
            # `msg` can interpolate the input; `input`/`ctx` are dropped entirely.
            "message": CONSTANT_MESSAGES.get(
                str(err.get("type")), redact_text(str(err.get("msg", "")))
            ),
        }
        for err in exc.errors()
    ]
    return _problem(
        422,
        "validation_failed",
        "Request validation failed",
        errors=redact_structure(errors),
    )


def _bare_os_error(exc: Exception) -> bool:
    """An `OSError` the routers map knowing a store call raised it; here, with no such context,
    it may be a file, venue or timeout fault (every `asyncio.timeout` expiry is one): a 500."""
    return isinstance(exc, OSError) and not isinstance(exc, StorageTierUnavailable)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if is_storage_outage(exc) and not _bare_os_error(exc):
        # A store outage that no router mapped: 503, not 500. Driver text embeds bound
        # parameters, so this line carries only the class name and SQLSTATE. Starlette still
        # re-raises after the response, so the server's own traceback line is not covered here.
        _log().error(
            "store_unavailable_unhandled", error=type(exc).__name__, sqlstate=sqlstate_of(exc)
        )
        response = _problem(
            503,
            "store_unavailable",
            ERROR_META[ErrorCode.STORE_UNAVAILABLE].title,
            detail="The store is unavailable.",
            retry_after_seconds=_RETRY_AFTER_S,
        )
        response.headers["Retry-After"] = str(_RETRY_AFTER_S)
        return response
    # Never echo str(exc) to the client. The traceback is logged through the
    # RedactionFilter-wired logger so 500s stay visible without leaking.
    _log().error("unhandled_exception", exc_info=exc)
    return _problem(500, "internal_error", "Internal server error")


def install_error_redaction(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
