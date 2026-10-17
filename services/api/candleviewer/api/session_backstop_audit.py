"""`auth.disabled_user_session_revoked`: the audit record of the `require_active` backstop (#3120).

`SessionService` hands this port each session it revoked as `user_disabled`, after the revoke, the
count, the log and the publish. `auth` may not import `audit` (`forbidden-M18`), so the composition
root attaches it (`AuthService.attach_backstop_audit`). The record names the session, its user as
the actor and the status read; no IP (the service has no request), token or hash. The revocation
never depends on it: C-2.9 asks for one transaction where possible, `auth` cannot reach the audit
store, and refusing to revoke because the sink is down would leave the session alive.

The write is bounded as the CSRF refusal audits are (`api/csrf.py`, C-2.18): the app's shared
`RefusalAuditTracker` caps writes in flight and drains them at shutdown, and the write is a tracked
task under `asyncio.shield`, so a caller that stops waiting (the service's time bound, a cancelled
request) never cancels the writer mid-append. A write that cannot start or fails raises to the
caller, which logs it and refuses all the same; one that fails after its caller left is logged here.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

import structlog

from candleviewer.api.csrf import AuditEmitterLike, RefusalAuditTracker
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.session_service import BackstopRevocation

#: Logged when a write fails after its caller stopped waiting.
LATE_FAILURE_EVENT: Final = "auth.disabled_user_session_audit_failed_late"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BackstopAuditSaturated(Exception):
    """The shared refusal-audit tracker is full of in-flight writes: the record is dropped."""


class SessionBackstopAudit:
    """The port `SessionService` calls once per session it revoked as `user_disabled`."""

    def __init__(self, audit: AuditEmitterLike, *, tracker: RefusalAuditTracker) -> None:
        self._audit = audit
        self._tracker = tracker

    async def __call__(self, revocation: BackstopRevocation) -> None:
        if self._tracker.full:
            raise BackstopAuditSaturated
        status = revocation.user_status
        task = self._tracker.track(
            self._audit.emit(
                "auth.disabled_user_session_revoked",
                actor_label=str(revocation.user_id),
                actor_user_id=revocation.user_id,
                session_id=revocation.session_id,
                object_kind="session",
                object_id=str(revocation.session_id),
                outcome=AuditOutcome.SUCCESS,
                severity=Severity.WARNING,
                reason="user_disabled",
                after_state={"user_status": "gone" if status is None else status.value},
            ),
            late_failure_event=LATE_FAILURE_EVENT,
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # The caller is gone but the write goes on. One that already failed, in the cancel's
            # own loop iteration, was never handed to the tracker: report it here.
            failure = task.exception() if task.done() and not task.cancelled() else None
            if failure is None:
                self._tracker.mark_timed_out(task)
            else:
                _log().error(LATE_FAILURE_EVENT, error=type(failure).__name__)
            raise
