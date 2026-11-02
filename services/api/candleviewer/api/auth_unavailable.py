"""`503 auth_unavailable` (#2152; `22-api-openapi.yaml` `AuthUnavailable`, ADR-0009 Amendment 4).

The answer the eight MFA operations give while M2's auth keyring cannot serve the user
(`auth.errors.MfaKeyringUnavailable`): a problem with `code: auth_unavailable`, the registry's
title and a fixed detail that names no cause, key, key reference or KEK version (the cause is the
`secrets` health reason), with `Retry-After: 30` (BQ-17). Its record, `auth.mfa_unavailable`,
names the operation, the user when known and the bounded reason (BQ-8). It is written after the
decision, best effort: one that cannot be written is counted on `auth_audit_outcome_lost_total`
and logged with the error class alone, and the answer is still the `503`.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

import structlog
from fastapi.responses import JSONResponse

from candleviewer.api.csrf import AUDIT_TIMEOUT_S
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import MfaKeyringUnavailable
from candleviewer.auth.metrics import auth_audit_outcome_lost_total, normalise_outcome_action
from candleviewer.auth.mfa_keyring import KEYRING_UNAVAILABLE
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

ACTION: Final = "auth.mfa_unavailable"
#: The contract example's value (BQ-17): long enough for a restart, short enough for a sign-in.
RETRY_AFTER_S: Final = 30
_CODE = "auth_unavailable"
_DETAIL = "Two-factor authentication is temporarily unavailable; try again later."
#: A keyring reason is recorded only if it looks like one (C-12.6), else the generic one.
_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def auth_unavailable() -> JSONResponse:
    """The `503`, built from constants alone: the same body whatever the cause."""
    title = ERROR_META[ErrorCode(_CODE)].title
    content = {
        "type": f"https://candleviewer.local/errors/{_CODE}",
        "title": title,
        "status": 503,
        "code": _CODE,
        "detail": _DETAIL,
        "retry_after_seconds": RETRY_AFTER_S,
    }
    response = JSONResponse(status_code=503, content=content, media_type="application/problem+json")
    response.headers["Retry-After"] = str(RETRY_AFTER_S)
    return response


def unavailable_row(
    operation: str,
    exc: MfaKeyringUnavailable,
    *,
    user_id: uuid.UUID | None = None,
    actor_ip: str | None = None,
) -> dict[str, object]:
    """The audit columns of one `auth.mfa_unavailable` (BQ-8): the operation, the user (the
    error's own, else `user_id`), the address and the bounded reason; never a code or a key."""
    user = exc.user_id or user_id
    reason = exc.reason if _REASON.fullmatch(exc.reason) else KEYRING_UNAVAILABLE
    return {
        "actor_label": str(user) if user is not None else "(unknown user)",
        "actor_user_id": user,
        "actor_ip": actor_ip,
        "outcome": AuditOutcome.FAILURE,
        "severity": Severity.WARNING,
        "reason": reason,
        "after_state": {"operation": operation, "reason": reason},
    }


async def record_unavailable(
    emit: Callable[..., Awaitable[None]], row: Mapping[str, object]
) -> None:
    """Write `row` as `auth.mfa_unavailable` through `emit`, bounded by the audit timeout; a
    record that fails is counted and logged, never raised (the answer is decided). A cancellation
    is counted too and propagates."""
    try:
        async with asyncio.timeout(AUDIT_TIMEOUT_S):
            await emit(ACTION, **row)
    except (AuditError, RuntimeError, TimeoutError) as exc:  # RuntimeError: audit not started
        _lost(type(exc).__name__)
    except asyncio.CancelledError:
        _lost("cancelled")
        raise


def _lost(error: str) -> None:
    auth_audit_outcome_lost_total.labels(action=normalise_outcome_action(ACTION)).inc()
    _log().error("auth.mfa_unavailable.record_lost", error=error)
