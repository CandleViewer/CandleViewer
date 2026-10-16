"""The idle lock at the HTTP edge (#2300; E09-D06 ruling on PR #2290).

Contract: `docs/plan/22-api-openapi.yaml` info "Idle lock", `x-error-codes`
`session_idle_locked`, `SessionState`.

A session past its `idle_deadline` is idle-locked, not revoked: WS frames keep
flowing (ADR-0020 section 4) and the session can still read itself
(`GET /auth/session`) and be signed out. An operation refused to a locked session
answers `401 session_idle_locked` (problem field `idle_locked_at`) and changes
nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from starlette.responses import JSONResponse

from candleviewer.auth.models import SessionRecord

_ERRORS = "https://candleviewer.local/errors/"


def problem(status: int, code: str, title: str, detail: str, **extra: Any) -> JSONResponse:
    """An RFC 7807 problem for a registered `x-error-codes` entry."""
    return JSONResponse(
        status_code=status,
        content={
            "type": _ERRORS + code,
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            **extra,
        },
        media_type="application/problem+json",
    )


def idle_locked_problem(idle_locked_at: datetime | None) -> JSONResponse:
    """`401 session_idle_locked`; `idle_locked_at` is the moment the session locked."""
    extra = {} if idle_locked_at is None else {"idle_locked_at": idle_locked_at.isoformat()}
    return problem(
        401,
        "session_idle_locked",
        "Session is idle-locked; unlock it with the password (POST /auth/unlock)",
        "Unlock with your password to continue.",
        **extra,
    )


def session_state(record: SessionRecord, *, now: datetime) -> dict[str, Any]:
    """`SessionState`: the server truth CMP-098 and SCR-005 time against."""
    return {
        "id": str(record.id),
        "issued_at": record.issued_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "idle_deadline": record.idle_deadline().isoformat(),
        "idle_timeout_s": record.idle_timeout_s,
        "locked": record.is_idle_locked(now=now),
    }


__all__ = ["idle_locked_problem", "problem", "session_state"]
