"""Unit tests for `candleviewer.api.auth.make_auth_router` (E09-S01)."""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.auth import AuditServiceLike, make_auth_router
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    MfaChallengeInvalid,
    MfaNotRequired,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
    UserDisabled,
)
from candleviewer.auth.login_service import EnrolmentOnlyLogin
from candleviewer.auth.models import (
    LoginRequest,
    MfaChallengeResult,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    MfaRecoveryCheck,
    MfaVerifiedResult,
    MfaVerifyRequest,
    MintedSession,
)
from tests.unit.api._fakes import WriterLane
from tests.unit.auth.totp_code_cases import NON_ASCII_DIGIT_CODES

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)  # SR-041 (#2090): routers require a codec


class _FakeLoginService:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    async def login(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        assert isinstance(self._outcome, MfaChallengeResult | EnrolmentOnlyLogin)
        return self._outcome


class _FakeMfaService:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.recovery_checks = 0
        self.completed: list[MfaRecoveryCheck] = []

    def _resolve(self) -> object:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    async def verify(self, request: MfaVerifyRequest) -> MfaVerifiedResult:
        result = self._resolve()
        assert isinstance(result, MfaVerifiedResult)
        return result

    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult:
        result = self._resolve()
        assert isinstance(result, MfaEnrollResult)
        return result

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[MfaMethodKind, tuple[str, ...]]:
        result = self._resolve()
        assert isinstance(result, tuple)
        return result

    async def check_recovery(self, mfa_token: str, recovery_code: str) -> MfaRecoveryCheck:
        self.recovery_checks += 1
        result = self._resolve()
        assert isinstance(result, MfaRecoveryCheck)
        return result

    async def complete_recovery(self, check: MfaRecoveryCheck) -> None:
        self.completed.append(check)


class _FakeAuthService:
    def __init__(
        self,
        outcome: object,
        *,
        active: bool = True,
        mfa_outcome: object = None,
        mfa_active: bool = True,
    ) -> None:
        self._active = active
        self._login = _FakeLoginService(outcome)
        self._mfa_active = mfa_active
        self._mfa = _FakeMfaService(mfa_outcome)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def login(self) -> _FakeLoginService:
        return self._login

    @property
    def mfa_is_active(self) -> bool:
        return self._mfa_active

    @property
    def mfa(self) -> _FakeMfaService:
        return self._mfa

    sessions_is_active = False

    @property
    def sessions(self) -> _FakeMinter:
        return _FakeMinter()


class _FakeMinter:
    def __init__(self) -> None:
        self.minted_for: list[str] = []
        self.session_ids: list[uuid.UUID | None] = []  # the id each mint was told to use

    async def mint(
        self,
        user_id: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> MintedSession:
        self.minted_for.append(user_id)
        self.session_ids.append(session_id)
        now = datetime(2026, 10, 1, tzinfo=UTC)
        return MintedSession(
            session_id=session_id or uuid.uuid4(),
            access_token_jti=uuid.uuid4(),
            access_token="acc",
            refresh_token="ref",
            issued_at=now,
            expires_at=now + timedelta(hours=12),
        )


class _MintingAuthService(_FakeAuthService):
    sessions_is_active = True

    def __init__(self, mfa_outcome: object) -> None:
        super().__init__(InvalidCredentials("n/a"), mfa_outcome=mfa_outcome)
        self.minter = _FakeMinter()

    @property
    def sessions(self) -> _FakeMinter:
        return self.minter


class _FakeIdentity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "roles": ["owner"]}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": [], "account_scope": []}


def _app(outcome: object, *, active: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(make_auth_router(_FakeAuthService(outcome, active=active), csrf=_CSRF_CODEC))
    return app


def _mfa_app(
    mfa_outcome: object, *, mfa_active: bool = True, audit_service: object = None
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_auth_router(
            _FakeAuthService(
                InvalidCredentials("n/a"), mfa_outcome=mfa_outcome, mfa_active=mfa_active
            ),
            audit_service=audit_service,  # type: ignore[arg-type]
            csrf=_CSRF_CODEC,
        )
    )
    return app


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_ip: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        **extra: object,
    ) -> None:
        self.calls.append(
            {
                "action": action,
                "actor_label": actor_label,
                "actor_ip": actor_ip,
                "outcome": outcome,
                "severity": severity,
                **extra,
            }
        )


class _RecordingAuditService:
    def __init__(self) -> None:
        self.writer = _RecordingAuditWriter()
        self.lane = WriterLane(self)  # ADR-0037's façade as its fallback: each record to the writer

    @property
    def is_active(self) -> bool:
        return True


def test_successful_login_returns_mfa_challenge() -> None:
    client = TestClient(
        _app(MfaChallengeResult(mfa_token="tok", methods=(MfaMethodKind.TOTP,), expires_in=300))
    )
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "mfa_required"
    assert body["mfa_token"] == "tok"
    assert body["methods"] == ["totp"]


def test_invalid_credentials_returns_401_problem_json() -> None:
    client = TestClient(_app(InvalidCredentials("Username or password is incorrect")))
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 401
    assert response.json() == {
        "type": "https://candleviewer.local/errors/unauthenticated",
        "title": "Invalid credentials",
        "status": 401,
        "code": "unauthenticated",
        "detail": "Username or password is incorrect",
    }


#: Every refusal the login service raises, its message deliberately unlike the others' (#4961).
_SIGN_IN_REFUSALS = [
    InvalidCredentials("any message at all"),
    AccountDisabled("Account disabled - contact the owner"),
    AccountLocked(),
    MfaNotRequired(),
]


@pytest.mark.parametrize("refusal", _SIGN_IN_REFUSALS, ids=lambda e: type(e).__name__)
def test_every_refused_sign_in_gets_the_one_401_answer(refusal: Exception) -> None:
    """SR-014: the same status, body bytes and headers whatever the cause; the router never
    echoes an error's own message."""
    body = {"identifier": "basiltt", "password": "x"}
    one = TestClient(_app(InvalidCredentials("Username or password is incorrect")))
    expected = one.post("/auth/login", json=body)
    response = TestClient(_app(refusal)).post("/auth/login", json=body)
    assert (response.status_code, response.content) == (401, expected.content)
    assert dict(response.headers) == dict(expected.headers)


def test_inactive_auth_service_returns_503() -> None:
    client = TestClient(_app(InvalidCredentials("n/a"), active=False))
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 503


def test_login_of_a_user_who_must_enrol_fails_closed_without_a_session_backend() -> None:
    """#2295: never a challenge, a 501 or a session nobody can audit."""
    client = TestClient(_app(EnrolmentOnlyLogin(user_id=uuid.uuid4())))
    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})
    assert response.status_code == 503


def test_account_locked_emits_auth_account_locked_audit_action_with_warning_severity() -> None:
    """Regression for QA bug #1604 defect 2: the ticket's Scope / Deliverables
    names `auth.account_locked` (severity warning) as the lockout audit
    action; the router must not reuse `auth.login_failed` for this path."""
    audit_service = _RecordingAuditService()
    app = FastAPI()
    app.include_router(
        make_auth_router(
            _FakeAuthService(AccountLocked()), audit_service=audit_service, csrf=_CSRF_CODEC
        )
    )
    client = TestClient(app)

    response = client.post("/auth/login", json={"identifier": "basiltt", "password": "x"})

    assert response.status_code == 401  # the one answer; the record keeps the cause
    assert len(audit_service.writer.calls) == 1
    call = audit_service.writer.calls[0]
    assert call["action"] == "auth.account_locked"
    assert call["outcome"] == AuditOutcome.DENIED
    assert call["severity"] == Severity.WARNING


# -- /auth/mfa/verify ------------------------------------------------------


def test_mfa_verify_success_returns_authenticated() -> None:
    client = TestClient(_mfa_app(MfaVerifiedResult(user_id=uuid.uuid4())))
    response = client.post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "authenticated"


def test_mfa_verify_invalid_code_returns_401_and_audits_failure() -> None:
    audit_service = _RecordingAuditService()
    client = TestClient(
        _mfa_app(MfaChallengeInvalid("no open challenge"), audit_service=audit_service)
    )
    response = client.post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )
    assert response.status_code == 401
    assert audit_service.writer.calls[0]["action"] == "auth.mfa_failed"


def test_mfa_verify_inactive_backend_returns_503() -> None:
    client = TestClient(_mfa_app(MfaVerifiedResult(user_id=uuid.uuid4()), mfa_active=False))
    response = client.post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )
    assert response.status_code == 503


# -- /auth/mfa/recovery ------------------------------------------------------


_RECOVERY_BODY = {"mfa_token": "tok", "recovery_code": "7F2A-91BC-4DE0"}


def _recovery_app(
    mfa_outcome: object, audit_service: AuditServiceLike | None
) -> tuple[FastAPI, _FakeMfaService]:
    """Every backend a recovery sign-in needs, wired; the MFA service answers *mfa_outcome*."""
    auth = _MintingAuthService(mfa_outcome)
    app = FastAPI()
    app.include_router(
        make_auth_router(
            auth,
            audit_service=audit_service,
            identity=_FakeIdentity(),
            csrf=_CSRF_CODEC,
        )
    )
    return app, auth.mfa


def test_mfa_recovery_fails_closed_until_every_backend_is_wired() -> None:
    """#2344: a recovery that could not mint the session checks and spends nothing (it used to
    answer 200 with no session while the code was spent). The refusal is the operation's
    documented 401 (the 503 `authMfaRecovery` declares is #2152's `AuthUnavailable`)."""
    check = MfaRecoveryCheck(user_id=uuid.uuid4(), challenge_id=uuid.uuid4(), code_id="c")
    unwired = _FakeAuthService(InvalidCredentials("n/a"), mfa_outcome=check)
    app = FastAPI()
    app.include_router(make_auth_router(unwired, csrf=_CSRF_CODEC))  # no session backend
    no_audit, no_audit_mfa = _recovery_app(check, None)
    cases = (
        (TestClient(app), unwired.mfa, "enrolment backend is not wired"),
        (TestClient(no_audit), no_audit_mfa, "audit sink not active"),
    )

    for client, mfa, detail in cases:
        response = client.post("/auth/mfa/recovery", json=_RECOVERY_BODY)
        assert (response.status_code, response.json()["detail"]) == (401, detail)
        assert response.json()["title"] == "Recovery failed"
        assert (mfa.recovery_checks, mfa.completed) == (0, [])


def test_mfa_recovery_exhausted_returns_401_and_audits_denied() -> None:
    audit_service = _RecordingAuditService()
    app, mfa = _recovery_app(RecoveryCodesExhausted("all used"), audit_service)
    response = TestClient(app).post("/auth/mfa/recovery", json=_RECOVERY_BODY)
    assert response.status_code == 401
    call = audit_service.writer.calls[0]
    assert call["action"] == "auth.recovery_codes_exhausted"
    assert call["outcome"] == AuditOutcome.DENIED
    assert mfa.completed == []


def test_mfa_recovery_wrong_code_returns_the_uniform_401_and_audits_failure() -> None:
    audit_service = _RecordingAuditService()
    app, mfa = _recovery_app(RecoveryCodeInvalid("invalid"), audit_service)
    response = TestClient(app).post("/auth/mfa/recovery", json=_RECOVERY_BODY)
    assert (response.status_code, response.json()["detail"]) == (401, "invalid or expired code")
    assert [c["action"] for c in audit_service.writer.calls] == ["auth.mfa_failed"]
    assert mfa.completed == []


# -- /auth/mfa/enroll and /auth/mfa/enroll/confirm (#2295) -----------------------------------
# PR #1618 review finding 1 still holds: `X-User-Id`/`X-Username` name nobody. Only the bearer
# session names the caller; the composed-app cases are in
# tests/security/auth/test_enrolment_only_endpoints.py.

_ENROL_CALLS = (
    ("/auth/mfa/enroll", {"method": "totp", "label": "phone"}),
    ("/auth/mfa/enroll/confirm", {"method_id": str(uuid.uuid4()), "code": "123456"}),
)
_FOREIGN = {"X-User-Id": str(uuid.uuid4()), "X-Username": "alice"}


def _enrol_app(*, audit: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_auth_router(
            _MintingAuthService(None),
            audit_service=_RecordingAuditService() if audit else None,
            identity=_FakeIdentity(),
            csrf=_CSRF_CODEC,
        )
    )
    return app


def test_mfa_enroll_and_confirm_fail_closed_until_every_backend_is_wired() -> None:
    """No session backend (the fake/CI default), or no audit sink: 503, nothing changes."""
    for app in (_mfa_app(None), _enrol_app(audit=False)):
        client = TestClient(app)
        for path, body in _ENROL_CALLS:
            assert client.post(path, json=body, headers=_FOREIGN).status_code == 503, path


def test_mfa_enroll_and_confirm_trust_no_header_only_a_bearer_session() -> None:
    client = TestClient(_enrol_app(audit=True))
    for path, body in _ENROL_CALLS:
        response = client.post(path, json=body, headers=_FOREIGN)
        assert (response.status_code, response.json()["code"]) == (401, "unauthenticated")


@pytest.mark.parametrize("code", NON_ASCII_DIGIT_CODES)
def test_mfa_enroll_confirm_refuses_a_non_ascii_digit_code_with_422(code: str) -> None:
    """#2605: the body is validated before the fail-closed stub answers, so a code that is not
    six ASCII digits never reaches `verify_code` once the route is wired."""
    client = TestClient(_mfa_app(None))
    response = client.post(
        "/auth/mfa/enroll/confirm", json={"method_id": str(uuid.uuid4()), "code": code}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("code", NON_ASCII_DIGIT_CODES)
def test_mfa_verify_refuses_a_non_ascii_digit_code_with_422(code: str) -> None:
    """`/auth/mfa/verify` was never exposed to #2605 (ASCII pattern); the service is not reached."""
    client = TestClient(_mfa_app(MfaVerifiedResult(user_id=uuid.uuid4())))
    response = client.post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": code}
    )
    assert response.status_code == 422


def test_mfa_verify_with_session_backend_mints_session_and_sets_cookie() -> None:
    uid = uuid.uuid4()
    auth = _MintingAuthService(MfaVerifiedResult(user_id=uid))
    audit_service = _RecordingAuditService()
    app = FastAPI()
    app.include_router(
        make_auth_router(
            auth,
            audit_service=audit_service,
            identity=_FakeIdentity(),
            csrf=_CSRF_CODEC,
        )
    )
    response = TestClient(app).post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tokens"]["access_token"] == "acc"
    assert body["tokens"]["refresh_token"] is None
    assert body["user"]["roles"] == ["owner"]
    cookie = response.headers["set-cookie"].lower()
    assert "cv_refresh=ref" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert auth.minter.minted_for == [str(uid)]
    assert [c["action"] for c in audit_service.writer.calls] == [
        "auth.mfa_verified",
        "auth.session_created",
    ]
    # The record written ahead names the session the mint then creates (#2914).
    assert auth.minter.session_ids == [audit_service.writer.calls[1]["session_id"]]


@pytest.mark.parametrize("identity", [_FakeIdentity(), None], ids=["minting", "no_session_backend"])
def test_mfa_verify_with_its_verified_record_refused_is_401_and_mints_nothing(
    identity: _FakeIdentity | None,
) -> None:
    """D1 (#2914): `auth.mfa_verified` is the mint's first write-ahead record, so the writer
    refusing it answers the operation's 401, never a 500, and nothing is minted (the TOTP step
    stays spent); with no session backend wired too."""
    auth = _MintingAuthService(MfaVerifiedResult(user_id=uuid.uuid4()))
    audit_service = _RecordingAuditService()
    audit_service.writer = _RefusingAuditWriter("auth.mfa_verified")
    app = FastAPI()
    app.include_router(
        make_auth_router(
            cast(Any, auth), audit_service=audit_service, identity=identity, csrf=_CSRF_CODEC
        )
    )

    response = TestClient(app).post(
        "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
    )

    assert (response.status_code, response.json()["detail"]) == (401, "audit sink not active")
    assert "set-cookie" not in response.headers
    assert auth.minter.minted_for == [] and audit_service.writer.calls == []


class _FailingMinter(_FakeMinter):
    """A store failure at the mint (a timeout, a lost connection): not a refusal."""

    async def mint(self, user_id: str, **_kw: Any) -> MintedSession:
        self.minted_for.append(user_id)
        raise OSError("session store unavailable")


def test_mfa_verify_whose_mint_fails_voids_the_session_it_announced_and_still_answers_500() -> None:
    """`auth.session_created` is written ahead of the mint, so a mint that then fails for another
    reason than a disabled user leaves an `auth.mfa_failed` row (reason `unminted`, through the
    lane) voiding that session, counted on the factor named, and an error log naming both ids and
    the error class (#2914); the 500 stands."""
    uid = uuid.uuid4()
    auth = _MintingAuthService(MfaVerifiedResult(user_id=uid))
    auth.minter = _FailingMinter()
    audit_service = _RecordingAuditService()
    app = FastAPI()
    app.include_router(
        make_auth_router(
            cast(Any, auth), audit_service=audit_service, identity=_FakeIdentity(), csrf=_CSRF_CODEC
        )
    )
    failures = _failures("totp")

    with capture_logs() as logs:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
        )

    assert response.status_code == 500 and "set-cookie" not in response.headers
    _verified, created, voiding = audit_service.writer.calls
    assert (voiding["action"], voiding["outcome"], voiding["reason"]) == (
        "auth.mfa_failed",
        AuditOutcome.FAILURE,
        "unminted",
    )
    assert voiding["session_id"] == created["session_id"]
    assert voiding["after_state"] == {"voids_session_created": str(created["session_id"])}
    assert audit_service.lane.actions == ["auth.mfa_failed"]
    assert _failures("totp") - failures == 1
    assert [e for e in logs if e["event"] == "auth.mfa_verify.unminted"] == [
        {
            "event": "auth.mfa_verify.unminted",
            "log_level": "error",
            "user_id": str(uid),
            "new_session_id": str(created["session_id"]),
            "error": "OSError",
        }
    ]


class _RefusingMinter(_FakeMinter):
    """#2911: the user was disabled after the password step, so the mint is refused."""

    async def mint(
        self,
        user_id: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> MintedSession:
        self.minted_for.append(user_id)
        raise UserDisabled("disabled")


class _RefusingAuditWriter(_RecordingAuditWriter):
    """The started writer refusing every record of *action* (`AuditUnavailable`: WAL full)."""

    def __init__(self, action: str) -> None:
        super().__init__()
        self.action = action

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action == self.action:
            raise AuditUnavailable("audit WAL unavailable: OSError")
        await super().emit(action, **kwargs)


class _InactiveAuditService(_RecordingAuditService):
    @property
    def is_active(self) -> bool:
        return False


def _lost(action: str) -> float:
    """`auth_audit_outcome_lost_total{action}` on the process-default registry."""
    return float(
        REGISTRY.get_sample_value("auth_audit_outcome_lost_total", {"action": action}) or 0
    )


def _failures(method: str) -> float:
    """`auth_login_failures_total{method}` (SR-125) on the process-default registry."""
    return float(REGISTRY.get_sample_value("auth_login_failures_total", {"method": method}) or 0)


def _verify_for_a_disabled_user(
    audit_service: _RecordingAuditService,
) -> tuple[httpx.Response, uuid.UUID, list[str], list[MutableMapping[str, Any]]]:
    """#2911: a correct second factor for a user disabled since the password step. Returns the
    response, the user, the mint attempts (each refused) and the captured log events."""
    uid = uuid.uuid4()
    auth = _MintingAuthService(MfaVerifiedResult(user_id=uid))
    auth.minter = _RefusingMinter()
    app = FastAPI()
    app.include_router(
        make_auth_router(
            auth,
            audit_service=audit_service,
            identity=_FakeIdentity(),
            csrf=_CSRF_CODEC,
        )
    )
    with capture_logs() as logs:
        response = TestClient(app).post(
            "/auth/mfa/verify", json={"mfa_token": "tok", "method": "totp", "code": "123456"}
        )
    return response, uid, auth.minter.minted_for, logs


def test_mfa_verify_for_a_disabled_user_mints_nothing_and_audits_the_refusal() -> None:
    """The operation's 401 and no session; the refusal is audited like login's disabled one, and
    voids the session `auth.session_created` announced ahead of the mint (C-2.9, #2914)."""
    audit_service = _RecordingAuditService()

    response, uid, attempts, _ = _verify_for_a_disabled_user(audit_service)

    assert (response.status_code, response.json()["detail"]) == (401, "account is disabled")
    assert "set-cookie" not in response.headers
    assert attempts == [str(uid)]
    verified, created, refused = audit_service.writer.calls
    assert [(c["action"], c["outcome"]) for c in (verified, created, refused)] == [
        ("auth.mfa_verified", AuditOutcome.SUCCESS),
        ("auth.session_created", AuditOutcome.SUCCESS),
        ("auth.login_failed", AuditOutcome.DENIED),
    ]
    assert (refused["reason"], refused["actor_user_id"]) == ("user_disabled", uid)
    assert refused["session_id"] == created["session_id"]
    assert refused["after_state"] == {"voids_session_created": str(created["session_id"])}


def test_mfa_verify_for_a_disabled_user_with_the_refusal_record_refused_is_still_401() -> None:
    """Error path: the writer refuses `auth.login_failed`, and so would the lane. Not write-ahead
    (nothing was minted), so the 401 stands, never a 500, and the lost record is counted and
    logged (#2914)."""
    audit_service = _RecordingAuditService()
    audit_service.writer = _RefusingAuditWriter("auth.login_failed")
    lost_before = _lost("auth.login_failed")

    response, uid, attempts, logs = _verify_for_a_disabled_user(audit_service)

    assert (response.status_code, response.json()["detail"]) == (401, "account is disabled")
    assert "set-cookie" not in response.headers
    assert attempts == [str(uid)]
    actions = [c["action"] for c in audit_service.writer.calls]
    assert actions == ["auth.mfa_verified", "auth.session_created"]
    assert _lost("auth.login_failed") - lost_before == 1
    (lost,) = [e for e in logs if e["event"] == "auth.login_audit.outcome_lost"]
    assert (lost["log_level"], lost["error"]) == ("error", "AuditUnavailable")


def test_mfa_verify_for_a_disabled_user_with_audit_inactive_is_still_401_and_logged() -> None:
    """Error path: no audit sink. The 401 stands, nothing is minted, and the unrecorded refusal
    is counted and logged."""
    audit_service = _InactiveAuditService()
    lost_before = _lost("auth.login_failed")

    response, uid, attempts, logs = _verify_for_a_disabled_user(audit_service)

    assert (response.status_code, response.json()["detail"]) == (401, "account is disabled")
    assert "set-cookie" not in response.headers
    assert attempts == [str(uid)]
    assert audit_service.writer.calls == []
    assert _lost("auth.login_failed") - lost_before == 1
    (lost,) = [e for e in logs if e["event"] == "auth.login_audit.outcome_lost"]
    assert (lost["log_level"], lost["error"]) == ("error", "inactive")
