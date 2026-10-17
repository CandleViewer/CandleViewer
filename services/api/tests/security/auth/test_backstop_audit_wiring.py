"""#3120 through the real `create_app()` wiring (C-2.9): the `require_active` backstop's revocation
reaches the audit writer. `auth` may not import `audit`, so the composition root hands the
`SessionService` a port (`AuthService.attach_backstop_audit`) over the app's audit emitter and its
shared refusal-audit tracker; the stack's writer stand-in refuses an unregistered action as the
real one does. Sink behaviour is in `tests/unit/auth/test_backstop_audit_port.py`."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, cast

from structlog.testing import capture_logs

from candleviewer.api.csrf import MAX_INFLIGHT_AUDITS, RefusalAuditTracker
from candleviewer.audit.models import Severity
from candleviewer.auth.models import UserStatus
from tests.unit.auth.session_fakes import FakeSessionRepository

if TYPE_CHECKING:
    from ._stack import Stack

_FAILED = "auth.disabled_user_session_audit_failed"


def _stray(stack: Stack) -> tuple[uuid.UUID, uuid.UUID, dict[str, str], FakeSessionRepository]:
    """(user id, session id, bearer header, repository) of a live session whose user was disabled
    without a sweep, as an out-of-band status edit leaves it."""
    uid, _seed = stack.add_user("stray")
    minted = stack.call(stack.auth.sessions.mint, str(uid))
    repo = cast(FakeSessionRepository, stack.auth._session_repository)
    repo.user_statuses[str(uid)] = UserStatus.DISABLED
    return uid, minted.session_id, {"Authorization": f"Bearer {minted.access_token}"}, repo


def test_create_app_audits_the_backstop_revocation_once(stack: Stack) -> None:
    uid, sid, bearer, _repo = _stray(stack)

    first = stack.client.get("/auth/session", headers=bearer)
    again = stack.client.get("/auth/session", headers=bearer)

    assert (first.status_code, again.status_code) == (401, 401)
    (record,) = stack.audit.of("auth.disabled_user_session_revoked")
    assert (record["actor_user_id"], record["session_id"]) == (uid, sid)
    assert (record["severity"], record["reason"]) == (Severity.WARNING, "user_disabled")


def test_the_port_counts_against_the_apps_shared_refusal_audit_cap(stack: Stack) -> None:
    """One in-flight cap for every refusal and session audit, drained once at shutdown: with the
    cap full of stuck writes, the record is dropped and logged, and the refusal is unchanged."""
    tracker: RefusalAuditTracker = stack.state.csrf_refusal_audits
    release = asyncio.Event()

    async def hold() -> None:
        await release.wait()

    async def fill() -> None:
        for _ in range(MAX_INFLIGHT_AUDITS):
            tracker.track(hold())

    stack.call(fill)
    uid, sid, bearer, repo = _stray(stack)

    with capture_logs() as logs:
        response = stack.client.get("/auth/session", headers=bearer)
    stack.call(release.set)

    assert response.status_code == 401 and repo.sessions[str(sid)].revoked_reason == "user_disabled"
    assert stack.audit.of("auth.disabled_user_session_revoked") == []
    (failed,) = [e for e in logs if e["event"] == _FAILED]
    assert (failed["error"], failed["user_id"]) == ("BackstopAuditSaturated", str(uid))
