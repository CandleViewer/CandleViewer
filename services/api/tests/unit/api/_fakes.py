"""Shared fakes for the session-fixation router unit tests (E09-X02, #2144).

In-memory and deterministic: fixed pepper, ids and clock, no network. Test modules import
from here, never from each other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from prometheus_client import REGISTRY

from candleviewer.audit.actions import validate_action
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import (
    MfaVerifiedResult,
    MfaVerifyRequest,
    SessionRecord,
    UserRecord,
)
from candleviewer.auth.session_service import SessionClass, SessionService
from tests.unit.auth.session_fakes import FakeSessionRepository

BASE = "https://testserver"
NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
CSRF_CODEC = CsrfCodec(b"\x05" * 32)  # SR-041: the routers require a codec
HASHER = Hasher(pepper="x02-fixation-unit-pepper")
FIXATION = "auth.session_fixation_attempt"


def fixation_count(reason: str) -> float:
    """`auth_session_fixation_attempts_total{reason}` on the process-default registry."""
    sample = "auth_session_fixation_attempts_total"
    return float(REGISTRY.get_sample_value(sample, {"reason": reason}) or 0.0)


def sessions(repo: FakeSessionRepository | None = None, *, now: datetime = NOW) -> SessionService:
    return SessionService(repo or FakeSessionRepository(), HASHER, clock=lambda: now)


class RecordingWriter:
    """Stand-in for the started `AuditWriter`: records each emission and, like the real one,
    raises for an unregistered action. `fail_with` makes the fixation write raise."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)
        if self.fail_with is not None and action == FIXATION:
            raise self.fail_with
        self.events.append({"action": action, **kw})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["action"] == action]


class AuditService:
    def __init__(self, *, active: bool = True) -> None:
        self.is_active = active
        self.writer = RecordingWriter()


class Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "u", "roles": ["viewer"]}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": [], "account_scope": []}


class SessionsAuth:
    """The session router's auth service: a real `SessionService` over the fake repo."""

    sessions_is_active = True
    enrolment_gate_is_active = False  # no user store here (#2295)

    def __init__(self, service: SessionService) -> None:
        self.sessions = service

    async def classify(self, session: SessionRecord) -> SessionClass:
        raise AssertionError("the enrolment-only gate is inert without a user store")


class _VerifyingMfa:
    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id

    async def verify(self, request: MfaVerifyRequest) -> MfaVerifiedResult:
        return MfaVerifiedResult(user_id=self.user_id)


class MfaAuth:
    """The auth router's auth service: every MFA code verifies as *user_id*; sessions are a
    real `SessionService`. Login is never called by these tests."""

    is_active = True
    mfa_is_active = True
    sessions_is_active = True
    login: Any = None

    def __init__(self, user_id: uuid.UUID, service: SessionService) -> None:
        self.mfa: Any = _VerifyingMfa(user_id)
        self.sessions: Any = service

    async def find_user(self, user_id: str) -> UserRecord | None:
        raise AssertionError("the enrolment routes are not under test here")
