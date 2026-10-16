"""Session-fixation signal in `make_auth_router` (E09-X02 AC2, #2144, U6/SR-013).

A session credential carried into `POST /auth/mfa/verify`, or into the password sign-in that
mints an enrolment-only session (#2295), is never adopted (a new session is minted); one that
is not the authenticating user's own is counted and audited, and when that record cannot be
written the step fails closed. Fixed values, no network.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.auth import make_auth_router
from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.login_service import EnrolmentOnlyLogin
from candleviewer.auth.models import LoginRequest
from candleviewer.auth.session_service import SessionService
from tests.unit.api._fakes import (
    CSRF_CODEC,
    FIXATION,
    AuditService,
    Identity,
    MfaAuth,
    fixation_count,
    sessions,
)

_VICTIM = uuid.UUID("00000000-0000-4000-8000-0000000000b1")
_OTHER = "00000000-0000-4000-8000-0000000000b2"
_BODY = {"mfa_token": "challenge-1", "method": "totp", "code": "123456"}
_PLANTED = {"Cookie": f"{REFRESH_COOKIE}=planted-before-login"}
_LOGIN = {"identifier": "victim", "password": "pw-unit-only"}  # never a credential


class _MustEnrol:
    """The login service of a user who must enrol TOTP: the password always verifies."""

    async def login(self, request: LoginRequest, *, source_ip: str) -> EnrolmentOnlyLogin:
        return EnrolmentOnlyLogin(user_id=_VICTIM)


def _sign_in_client(audit: AuditService) -> tuple[TestClient, SessionService]:
    """`POST /auth/login` for a user with `mfa_required` and no confirmed method (#2295)."""
    store = sessions()
    auth = MfaAuth(_VICTIM, store)
    auth.login = _MustEnrol()
    app = FastAPI()
    app.include_router(make_auth_router(auth, audit, identity=Identity(), csrf=CSRF_CODEC))
    return TestClient(app), store


def _client(audit: AuditService) -> tuple[TestClient, SessionService]:
    store = sessions()
    app = FastAPI()
    auth = MfaAuth(_VICTIM, store)
    app.include_router(make_auth_router(auth, audit, identity=Identity(), csrf=CSRF_CODEC))
    return TestClient(app), store


def test_never_issued_cookie_carried_into_mfa_is_audited_and_never_adopted() -> None:
    audit, before = AuditService(), fixation_count("unknown_token")
    client, _ = _client(audit)
    r = client.post("/auth/mfa/verify", json=_BODY, headers=_PLANTED)
    assert r.status_code == 200
    assert r.cookies.get(REFRESH_COOKIE) not in (None, "planted-before-login")
    (row,) = audit.writer.of(FIXATION)
    assert (row["reason"], row["actor_user_id"]) == ("unknown_token", _VICTIM)
    assert row["after_state"] == {"vector": "refresh_cookie", "stage": "mfa_verify"}
    assert fixation_count("unknown_token") - before == 1


async def test_another_users_session_carried_into_mfa_is_audited_with_its_id() -> None:
    audit = AuditService()
    client, store = _client(audit)
    foreign = await store.mint(_OTHER)
    headers = {"Authorization": f"Bearer {foreign.access_token}"}
    assert client.post("/auth/mfa/verify", json=_BODY, headers=headers).status_code == 200
    (row,) = audit.writer.of(FIXATION)
    assert row["reason"] == "foreign_session"
    assert row["after_state"] == {
        "vector": "bearer",
        "stage": "mfa_verify",
        "presented_session_id": str(foreign.session_id),
    }


async def test_own_session_carried_into_mfa_is_a_relogin_not_an_attempt() -> None:
    audit = AuditService()
    client, store = _client(audit)
    own = await store.mint(str(_VICTIM))
    headers = {
        "Cookie": f"{REFRESH_COOKIE}={own.refresh_token}",
        "Authorization": f"Bearer {own.access_token}",
    }
    assert client.post("/auth/mfa/verify", json=_BODY, headers=headers).status_code == 200
    assert audit.writer.of(FIXATION) == []


def test_without_an_active_audit_sink_the_attempt_is_still_counted() -> None:
    audit, before = AuditService(active=False), fixation_count("unknown_token")
    client, _ = _client(audit)
    assert client.post("/auth/mfa/verify", json=_BODY, headers=_PLANTED).status_code == 200
    assert audit.writer.of(FIXATION) == [] and fixation_count("unknown_token") - before == 1


async def test_failed_fixation_write_fails_the_mfa_step_closed_without_minting() -> None:
    audit, before = AuditService(), fixation_count("audit_failed")
    audit.writer.fail_with = AuditUnavailable("audit WAL unavailable: OSError")
    client, store = _client(audit)
    r = client.post("/auth/mfa/verify", json=_BODY, headers=_PLANTED)
    assert (r.status_code, r.json()["detail"]) == (401, "audit sink not active")
    assert REFRESH_COOKIE not in r.cookies and "tokens" not in r.json()
    assert await store.list_sessions(str(_VICTIM)) == ()  # C-2.9 write-ahead: nothing minted
    assert fixation_count("audit_failed") - before == 1


async def test_never_issued_cookie_carried_into_an_enrolment_only_sign_in_is_audited() -> None:
    """#2295: the password sign-in mints a session too, so it gets the MFA step's check, and the
    attempt is recorded before `auth.login` and the new session."""
    audit, before = AuditService(), fixation_count("unknown_token")
    client, store = _sign_in_client(audit)

    r = client.post("/auth/login", json=_LOGIN, headers=_PLANTED)

    assert r.status_code == 200
    assert r.cookies.get(REFRESH_COOKIE) not in (None, "planted-before-login")
    (row,) = audit.writer.of(FIXATION)
    assert (row["reason"], row["actor_user_id"]) == ("unknown_token", _VICTIM)
    assert row["after_state"] == {"vector": "refresh_cookie", "stage": "login"}
    actions = [event["action"] for event in audit.writer.events]
    assert actions == [FIXATION, "auth.login", "auth.session_created"]
    assert fixation_count("unknown_token") - before == 1
    assert len(await store.list_sessions(str(_VICTIM))) == 1


async def test_failed_fixation_write_fails_the_enrolment_only_sign_in_closed() -> None:
    """Write-ahead (C-2.9): the attempt cannot be recorded, so nothing is minted or audited as a
    sign-in, and the answer is the operation's documented 503."""
    audit, before = AuditService(), fixation_count("audit_failed")
    audit.writer.fail_with = AuditUnavailable("audit WAL unavailable: OSError")
    client, store = _sign_in_client(audit)

    r = client.post("/auth/login", json=_LOGIN, headers=_PLANTED)

    assert (r.status_code, r.json()["detail"]) == (503, "audit sink not active")
    assert REFRESH_COOKIE not in r.cookies and "tokens" not in r.json()
    assert audit.writer.events == []  # no auth.login, no auth.session_created
    assert await store.list_sessions(str(_VICTIM)) == ()
    assert fixation_count("audit_failed") - before == 1
