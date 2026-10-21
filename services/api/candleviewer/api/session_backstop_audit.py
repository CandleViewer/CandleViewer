"""`auth.disabled_user_session_revoked`: the audit record of the backstop (#3120), whether
`require_active` or a refused `refresh()` (#3331) revoked the session.

`SessionService` hands this port each session it revoked as `user_disabled`, after the revoke, the
count, the log and the publish, from a unit a cancelled request cannot cut short (#3332). `auth`
may not import `audit` (`forbidden-M18`), so the composition root attaches it
(`AuthService.attach_backstop_audit`). The record names the session, its user as the actor and the
status read; no IP (the service has no request), token or hash. The revocation never depends on
it: C-2.9 asks for one transaction where possible, `auth` cannot reach the audit store, and
refusing to revoke because the sink is down would leave the session alive.

The composition root hands it the audit lane's façade (`AuditService.lane`, ADR-0037), the one the
session routes use for their lane rows: the record is a `reserved` row of the lane's registry and
the writer is the façade's fallback; with no façade (`LaneNotWired`) the writer takes it.

The write is bounded as the CSRF refusal audits are (`api/csrf.py`, C-2.18): a tracked task under
`asyncio.shield` in the app's shared `RefusalAuditTracker` (capped in flight, drained at shutdown),
so a caller that stops waiting never cancels it mid-append. One that cannot start or fails raises
to the caller, which logs it and refuses all the same (the façade fails only once the writer
refuses too); if the caller left, the tracker logs it.

A record that is lost adds one to `auth_audit_outcome_lost_total{action}` (04-security-program.md
section 8.3 rule 2), which `AuthAuditOutcomeLost` alerts on, once however many of these paths it
meets: the lane and the writer both refused it, it was dropped at the in-flight cap, it failed after
its caller stopped waiting, or it was still running when the shutdown drain gave up."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Final

from candleviewer.api.csrf import AuditEmitterLike, RefusalAuditTracker
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.metrics import auth_audit_outcome_lost_total
from candleviewer.auth.session_service import BackstopRevocation
from candleviewer.observability.context import current_request_uuid

#: The record's action: a member of `auth_audit_outcome_lost_total`'s closed `action` set.
ACTION: Final = "auth.disabled_user_session_revoked"

#: Logged when a write fails after its caller stopped waiting.
LATE_FAILURE_EVENT: Final = "auth.disabled_user_session_audit_failed_late"


class BackstopAuditSaturated(Exception):
    """The shared refusal-audit tracker is full of in-flight writes: the record is dropped."""


def _count_lost_once() -> Callable[[], None]:
    """The record's `on_lost`: one count however many paths report it (the awaiting caller's
    failure, the tracker's late report, its shutdown drain)."""
    counted = False

    def lost() -> None:
        nonlocal counted
        if not counted:
            counted = True
            auth_audit_outcome_lost_total.labels(action=ACTION).inc()

    return lost


class SessionBackstopAudit:
    """The port `SessionService` calls once per session it revoked as `user_disabled`."""

    def __init__(self, audit: AuditEmitterLike, *, tracker: RefusalAuditTracker) -> None:
        self._audit = audit
        self._tracker = tracker

    async def __call__(self, revocation: BackstopRevocation) -> None:
        lost = _count_lost_once()
        if self._tracker.full:
            lost()  # dropped before any write: lost all the same
            raise BackstopAuditSaturated
        status = revocation.user_status
        task = self._tracker.track(
            self._audit.emit(
                ACTION,
                actor_label=str(revocation.user_id),
                actor_user_id=revocation.user_id,
                session_id=revocation.session_id,
                object_kind="session",
                object_id=str(revocation.session_id),
                outcome=AuditOutcome.SUCCESS,
                severity=Severity.WARNING,
                reason="user_disabled",
                after_state={"user_status": "gone" if status is None else status.value},
                request_id=current_request_uuid(),
            ),
            on_lost=lost,
            late_failure_event=LATE_FAILURE_EVENT,
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            self._tracker.mark_timed_out(task)  # the caller is gone; the tracker reports a failure
            raise
        except Exception:
            # The caller still waits, so the tracker reports nothing: the lane and the writer both
            # refused the record.
            lost()
            raise
