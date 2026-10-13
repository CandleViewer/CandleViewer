"""Automated dry-run driver for the E09-Q01 black-box plan, Group A subset.

QA bug #1623 (parent #227): `qa/plans/e09-auth-rbac-test-plan.md` §10 shipped
with an **empty** dry-run table and §11 sign-off checkboxes deferred
indefinitely to a staging build that does not exist yet (no `E09-S02..S06`
story ticket has merged; `docker` is unavailable in this environment per the
fixer brief). Leaving §10 permanently empty is itself the defect: the plan
can and must record a *real*, evidence-backed dry run for every case whose
dependency (`E09-S01`, merged in #1599/#1609) already exists in `main`, and
must say so honestly for every case it cannot yet execute — not defer the
whole table.

This module is that dry run for the only story currently mergeable against:
`E09-S01` (`POST /auth/login`, US-ONB-001). It drives the *real* router
(`candleviewer.api.auth.make_auth_router`) exactly as
`tests/unit/api/test_auth_router.py` does (black-box: HTTP in, HTTP out, no
internal helper reached from the test body), and doubles as the executable
evidence cited by `qa/plans/e09-auth-rbac-test-plan-dryrun-20260930.md`.

Cases from Group A that are **not** exercised here (A02, A04-A06, A09-A11)
depend on `POST /auth/mfa/verify` (`E09-S02`, not yet merged) and are
recorded as `blocked-pending-dependency` in the dry-run record, not as a
fabricated pass.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.auth import make_auth_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import AccountDisabled, AccountLocked
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, MfaMethodKind
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)  # SR-041 (#2090): routers require a codec


class _FakeLoginService:
    """Same fake shape as `test_auth_router.py`'s: this dry run is black-box
    against the router's HTTP contract, not against `LoginService`'s
    internals — the plan cases (§1 Group A) are themselves phrased against
    `POST /auth/login` only."""

    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    async def login(self, request: LoginRequest, *, source_ip: str) -> MfaChallengeResult:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        assert isinstance(self._outcome, MfaChallengeResult)
        return self._outcome


class _FakeAuthService:
    def __init__(self, outcome: object, *, active: bool = True) -> None:
        self._active = active
        self._login = _FakeLoginService(outcome)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def login(self) -> _FakeLoginService:
        return self._login


def _client(outcome: object, *, active: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(make_auth_router(_FakeAuthService(outcome, active=active), csrf=_CSRF_CODEC))
    return TestClient(app)


def test_e09_tc_a01_correct_credentials_return_mfa_required_no_session() -> None:
    """E09-TC-A01: `200`, `{"status": "mfa_required", "challenge_id": ...}`,
    no session cookie set yet."""
    challenge = MfaChallengeResult(
        mfa_token="tok-a01", methods=(MfaMethodKind.TOTP,), expires_in=300
    )
    client = _client(challenge)
    response = client.post("/auth/login", json={"identifier": "owner-enrolled", "password": "x"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "mfa_required"
    assert "set-cookie" not in {k.lower() for k in response.headers}


def test_e09_tc_a03_disabled_account_rejected_after_password_check() -> None:
    """E09-TC-A03: disabled-user response, no session issued."""
    client = _client(AccountDisabled("Account disabled - contact the owner"))
    response = client.post("/auth/login", json={"identifier": "viewer-disabled", "password": "x"})
    assert response.status_code == 403
    assert "set-cookie" not in {k.lower() for k in response.headers}


def test_e09_tc_a07_unknown_user_and_wrong_password_are_indistinguishable() -> None:
    """E09-TC-A07: status and body shape must be identical for an unknown
    identifier and a known identifier with the wrong password (SR-014).

    Unlike the other Group A cases in this module (which double the router's
    own black-box contract test and legitimately inject a canned outcome),
    this case's entire point is that *the real `LoginService`* produces the
    same `InvalidCredentials` for two genuinely different code paths
    (unknown-identifier vs. known-identifier-wrong-password). Injecting the
    same fake exception into two fakes would prove only that the router
    forwards whatever it is given — it would not exercise SR-014 at all. So
    this case wires the router to the real `LoginService` over an in-memory
    `FakeUserRepository` (same fake `UserRepository` used by
    `tests/unit/auth/test_login_service.py`), with one real enrolled user
    and one identifier that does not exist."""

    class _RealAuthService:
        def __init__(self, login: LoginService) -> None:
            self._login = login

        @property
        def is_active(self) -> bool:
            return True

        @property
        def login(self) -> LoginService:
            return self._login

    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    password_hash = asyncio.run(hasher.hash("correct-horse-battery-staple"))
    repo.add(make_user(username="manager-with-grants", password_hash=password_hash))
    login_service = LoginService(
        repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000)
    )

    app = FastAPI()
    app.include_router(make_auth_router(_RealAuthService(login_service), csrf=_CSRF_CODEC))
    client = TestClient(app)

    unknown_response = client.post(
        "/auth/login",
        json={"identifier": "unknown@example.test", "password": "x"},
    )
    wrong_password_response = client.post(
        "/auth/login",
        json={"identifier": "manager-with-grants", "password": "wrong"},
    )

    assert unknown_response.status_code == wrong_password_response.status_code == 401
    assert unknown_response.json() == wrong_password_response.json()


def test_e09_tc_a08_lockout_returns_423_with_retry_after() -> None:
    """E09-TC-A08 (smoke slice): the 11th attempt after 5 consecutive
    failures is rejected with `423` and a `Retry-After` header even given the
    correct password — the full 10-attempt sequence and the Owner-alert
    assertion are `manual-only` per the plan (§1 Automation column) and
    tracked under `E09-Q02-lockout-automation`; this dry-run row covers only
    the router-level contract already provable against `E09-S01`."""
    client = _client(AccountLocked(900))
    response = client.post(
        "/auth/login", json={"identifier": "manager-with-grants", "password": "correct"}
    )
    assert response.status_code == 423
    assert response.headers["Retry-After"] == "900"
