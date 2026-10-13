"""MFA-step session-fixation signal in `make_auth_router` (E09-X02 AC2, #2144, U6/SR-013).

A session credential carried into `POST /auth/mfa/verify` is never adopted (a new session is
minted); one that is not the authenticating user's own is counted and audited. No network.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.api.auth import make_auth_router
from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.audit.actions import validate_action
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import InvalidCredentials
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaVerifiedResult
from candleviewer.auth.session_service import SessionService
from tests.unit.api.test_auth_router import _CSRF_CODEC, _FakeAuthService, _FakeIdentity
from tests.unit.auth.session_fakes import FakeSessionRepository

_VICTIM = uuid.uuid4()
_BODY = {"mfa_token": "challenge-1", "method": "totp", "code": "123456"}
_PLANTED = {"Cookie": f"{REFRESH_COOKIE}=planted-before-login"}


class _Auth(_FakeAuthService):
    sessions_is_active = True

    def __init__(self) -> None:
        verified = MfaVerifiedResult(user_id=_VICTIM)
        super().__init__(InvalidCredentials("n/a"), mfa_outcome=verified)
        self.store = SessionService(FakeSessionRepository(), Hasher(pepper=os.urandom(8).hex()))

    @property
    def sessions(self) -> Any:
        return self.store


class _Audit:
    def __init__(self, *, active: bool = True, failing: bool = False) -> None:
        self.is_active = active
        self.failing = failing
        self.writer = self
        self.rows: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)  # as the real writer: an unregistered action raises
        if action == "auth.session_fixation_attempt":
            if self.failing:
                raise AuditUnavailable("audit WAL unavailable: OSError")
            self.rows.append(kw)


def _client(audit: _Audit) -> tuple[TestClient, SessionService]:
    auth = _Auth()
    app = FastAPI()
    router = make_auth_router(auth, audit, identity=_FakeIdentity(), csrf=_CSRF_CODEC)
    app.include_router(router)
    return TestClient(app), auth.store


def _count(reason: str) -> float:
    sample = "auth_session_fixation_attempts_total"
    return float(REGISTRY.get_sample_value(sample, {"reason": reason}) or 0.0)


def test_never_issued_cookie_carried_into_mfa_is_audited_and_never_adopted() -> None:
    audit, before = _Audit(), _count("unknown_token")
    client, _ = _client(audit)
    r = client.post("/auth/mfa/verify", json=_BODY, headers=_PLANTED)
    assert r.status_code == 200
    assert r.cookies.get(REFRESH_COOKIE) not in (None, "planted-before-login")
    (row,) = audit.rows
    assert (row["reason"], row["actor_user_id"]) == ("unknown_token", _VICTIM)
    assert row["after_state"] == {"vector": "refresh_cookie", "stage": "mfa_verify"}
    assert _count("unknown_token") - before == 1


async def test_another_users_session_carried_into_mfa_is_audited_with_its_id() -> None:
    audit = _Audit()
    client, store = _client(audit)
    foreign = await store.mint(str(uuid.uuid4()))
    headers = {"Authorization": f"Bearer {foreign.access_token}"}
    assert client.post("/auth/mfa/verify", json=_BODY, headers=headers).status_code == 200
    (row,) = audit.rows
    assert row["reason"] == "foreign_session"
    assert row["after_state"] == {
        "vector": "bearer",
        "stage": "mfa_verify",
        "presented_session_id": str(foreign.session_id),
    }


async def test_own_session_carried_into_mfa_is_a_relogin_not_an_attempt() -> None:
    audit = _Audit()
    client, store = _client(audit)
    own = await store.mint(str(_VICTIM))
    headers = {
        "Cookie": f"{REFRESH_COOKIE}={own.refresh_token}",
        "Authorization": f"Bearer {own.access_token}",
    }
    assert client.post("/auth/mfa/verify", json=_BODY, headers=headers).status_code == 200
    assert audit.rows == []


def test_without_an_active_audit_sink_the_attempt_is_still_counted() -> None:
    audit, before = _Audit(active=False), _count("unknown_token")
    client, _ = _client(audit)
    assert client.post("/auth/mfa/verify", json=_BODY, headers=_PLANTED).status_code == 200
    assert audit.rows == [] and _count("unknown_token") - before == 1


async def test_failed_fixation_write_fails_the_mfa_step_closed_without_minting() -> None:
    audit, before = _Audit(failing=True), _count("audit_failed")
    client, store = _client(audit)
    r = client.post("/auth/mfa/verify", json=_BODY, headers=_PLANTED)
    assert (r.status_code, r.json()["detail"]) == (401, "audit sink not active")
    assert REFRESH_COOKIE not in r.cookies and "tokens" not in r.json()
    assert await store.list_sessions(str(_VICTIM)) == ()  # C-2.9 write-ahead: nothing minted
    assert _count("audit_failed") - before == 1
