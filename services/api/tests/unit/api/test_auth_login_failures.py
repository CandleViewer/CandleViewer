"""SR-125 `auth_login_failures_total{method}` through the real login routes (#2319 item 4).

One increment per audited failed login, on the factor that failed: `password` for an
`auth.login_failed` row, the requested MFA method for an `auth.mfa_failed` row, `recovery_code` for
`auth.recovery_codes_exhausted`. An attempt refused while the account is locked
(`auth.account_locked`) and a success never count. Deltas on the process-default registry, where
the module-level counter lives; the scraped view is `test_security_metrics_export.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY

from candleviewer.api.auth import make_auth_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    MfaChallengeLocked,
    MfaCodeInvalid,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.metrics import LOGIN_FAILURE_METHODS
from candleviewer.auth.models import MfaVerifiedResult, UserStatus
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.api._fakes import AuditService
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_RIGHT_PW = "correct-horse-battery-staple"
_VERIFY = {"mfa_token": "t" * 20, "method": "totp", "code": "000000"}
_RECOVER = {"mfa_token": "t" * 20, "recovery_code": "zzzz-zzzz-zzzz"}


def _failures() -> dict[str, float]:
    sample = REGISTRY.get_sample_value
    return {
        m: float(sample("auth_login_failures_total", {"method": m}) or 0)
        for m in LOGIN_FAILURE_METHODS
    }


def _moved(before: dict[str, float]) -> dict[str, float]:
    return {m: v - before[m] for m, v in _failures().items() if v != before[m]}


class _Mfa:
    """Raises *error* from verify/recover, or verifies when there is none."""

    def __init__(self, error: Exception | None) -> None:
        self._error = error

    async def _result(self, *_args: object) -> MfaVerifiedResult:
        if self._error is not None:
            raise self._error
        return MfaVerifiedResult(user_id=uuid.uuid4())

    verify = recover = _result


class _Auth:
    is_active = mfa_is_active = True
    sessions_is_active = False

    def __init__(self, login: LoginService | None, mfa: _Mfa) -> None:
        self.login, self.mfa = login, mfa


def _client(login: LoginService | None, mfa: _Mfa, audit: AuditService | None) -> httpx.AsyncClient:
    app, auth = FastAPI(), _Auth(login, mfa)
    router = make_auth_router(cast(Any, auth), audit, csrf=CsrfCodec(b"\x05" * 32))
    app.include_router(router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _login_service(*, per_address: int = 10_000) -> LoginService:
    repo, hasher = FakeUserRepository(), Hasher(pepper="p")
    pw = await hasher.hash(_RIGHT_PW)
    states: dict[str, dict[str, Any]] = {
        "basiltt": {},
        "gone": {"status": UserStatus.DISABLED},
        "locked": {"locked_until": _NOW + timedelta(hours=1)},
    }
    for name, extra in states.items():
        repo.add(make_user(username=name, email=f"{name}@x.test", password_hash=pw, **extra))
    throttle = PerIpLoginThrottle(max_attempts=per_address)
    return LoginService(repo, hasher, per_ip_throttle=throttle, clock=lambda: _NOW)


async def _login(client: httpx.AsyncClient, identifier: str, password: str) -> int:
    body = {"identifier": identifier, "password": password}
    return (await client.post("/auth/login", json=body)).status_code


async def test_each_refused_password_login_counts_once_and_matches_its_audit_row() -> None:
    audit, before = AuditService(), _failures()
    async with _client(await _login_service(), _Mfa(None), audit) as client:
        codes = [
            await _login(client, "basiltt", "wrong-password"),  # wrong password
            await _login(client, "nobody", "wrong-password"),  # unknown identifier
            await _login(client, "gone", _RIGHT_PW),  # disabled, after a correct password
        ]
    assert codes == [401, 401, 403]
    assert _moved(before) == {"password": 3} and len(audit.writer.of("auth.login_failed")) == 3


async def test_a_login_refused_by_the_per_address_throttle_counts_as_a_password_failure() -> None:
    audit, before = AuditService(), _failures()
    async with _client(await _login_service(per_address=2), _Mfa(None), audit) as client:
        codes = [await _login(client, "basiltt", "wrong-password") for _ in range(2)]
        codes.append(await _login(client, "basiltt", _RIGHT_PW))  # right, but address blocked
    assert codes == [401, 401, 401]
    assert _moved(before) == {"password": 3} and len(audit.writer.of("auth.login_failed")) == 3


async def test_attempts_refused_while_locked_and_successful_logins_do_not_count() -> None:
    audit, before = AuditService(), _failures()
    async with _client(await _login_service(), _Mfa(None), audit) as client:
        assert await _login(client, "locked", _RIGHT_PW) == 423
        assert await _login(client, "locked", "wrong-password") == 423
        assert await _login(client, "basiltt", _RIGHT_PW) == 200  # correct: the MFA challenge
    assert _moved(before) == {} and len(audit.writer.of("auth.account_locked")) == 2


async def test_a_failed_login_counts_without_an_audit_writer() -> None:
    before = _failures()
    async with _client(await _login_service(), _Mfa(None), None) as client:
        assert await _login(client, "basiltt", "wrong-password") == 401
    assert _moved(before) == {"password": 1}


_V, _R = "/auth/mfa/verify", "/auth/mfa/recovery"
_FAILED, _EXHAUSTED = "auth.mfa_failed", "auth.recovery_codes_exhausted"


@pytest.mark.parametrize(
    ("path", "body", "error", "method", "row"),
    [
        (_V, _VERIFY, MfaCodeInvalid("x"), "totp", _FAILED),
        (_V, _VERIFY, MfaChallengeLocked("x"), "totp", _FAILED),
        (_V, {**_VERIFY, "method": "webauthn"}, MfaCodeInvalid("x"), "webauthn", _FAILED),
        (_R, _RECOVER, RecoveryCodeInvalid("x"), "recovery_code", _FAILED),
        (_R, _RECOVER, RecoveryCodesExhausted("x"), "recovery_code", _EXHAUSTED),
    ],
)
async def test_each_failed_second_factor_counts_its_method_and_matches_its_audit_row(
    path: str, body: dict[str, str], error: Exception, method: str, row: str
) -> None:
    audit, before = AuditService(), _failures()
    async with _client(None, _Mfa(error), audit) as client:
        assert (await client.post(path, json=body)).status_code == 401
    assert _moved(before) == {method: 1} and len(audit.writer.of(row)) == 1


@pytest.mark.parametrize(
    ("path", "body"), [("/auth/mfa/verify", _VERIFY), ("/auth/mfa/recovery", _RECOVER)]
)
async def test_a_second_factor_that_succeeds_does_not_count(
    path: str, body: dict[str, str]
) -> None:
    before = _failures()
    async with _client(None, _Mfa(None), AuditService()) as client:
        assert (await client.post(path, json=body)).status_code == 200
    assert _moved(before) == {}
