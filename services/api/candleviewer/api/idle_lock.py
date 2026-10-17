"""The idle lock at the HTTP edge (#2300; E09-D06 ruling on PR #2290).

Contract: `docs/plan/22-api-openapi.yaml` info "Idle lock", `SessionState`.

A session past its `idle_deadline` is idle-locked, not revoked: WS frames keep
flowing (ADR-0020 section 4) and the session can still read itself
(`GET /auth/session`) and be signed out. `session_state` is the server truth a
client times the lock against.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from candleviewer.auth.models import SessionRecord


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


__all__ = ["session_state"]
