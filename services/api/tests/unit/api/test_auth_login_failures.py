"""SR-125 `auth_login_failures_total{method}` through the real login routes (#2319 item 4).

One increment per audited failed login, on the factor that failed: `password` for an
`auth.login_failed` row, the requested MFA method for an `auth.mfa_failed` row, `recovery_code` for
`auth.recovery_codes_exhausted`. The one `auth.login_failed` row the MFA step writes, for a user
disabled since the password step (#2911), counts on the requested method too (#3054). An attempt
refused while the account is locked (`auth.account_locked`) and a success never count. Deltas on the
process-default registry, where the module-level counter lives; the scraped view is
`test_security_metrics_export.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY

from candleviewer.api.auth import make_auth_router
from candleviewer.audit.errors import AuditError
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
from tests.unit.api._fakes import (
    CSRF_CODEC,
    AuditService,
    Identity,
    MfaAuth,
    RecordingWriter,
    sessions,
)
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.session_fakes import FakeSessionRepository

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


_LOGIN_FAILED = "auth.login_failed"


class _RefusingWriter(RecordingWriter):
    """The started writer refusing every `auth.login_failed` record (WAL full or unwritable)."""

    async def emit(self, action: str, **kw: Any) -> None:
        if action == _LOGIN_FAILED:
            raise AuditError("wal unavailable")
        await super().emit(action, **kw)


def _minting_client(
    user: uuid.UUID, repo: FakeSessionRepository, audit: AuditService | None
) -> httpx.AsyncClient:
    """The real router over a real `SessionService`: every code verifies as *user*, then the mint
    reads the status *repo* holds for it, as `users.status` is read in the insert's transaction."""
    app = FastAPI()
    auth = MfaAuth(user, sessions(repo))
    app.include_router(make_auth_router(auth, audit, identity=Identity(), csrf=CSRF_CODEC))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.parametrize("method", ["totp", "webauthn"])
async def test_a_correct_second_factor_for_a_user_disabled_since_the_password_step_counts_once(
    method: str,
) -> None:
    # #3054 (1): the refusal writes an `auth.login_failed` row (reason `user_disabled`), so it
    # counts like the password step's own refusal of a disabled account, on the requested factor.
    # The shipped `MfaService.verify` accepts `totp` only; this fake verifies any method, so the
    # `webauthn` case pins that the label follows the request, not a constant.
    user, repo, audit = uuid.uuid4(), FakeSessionRepository(), AuditService()
    repo.user_statuses[str(user)] = UserStatus.DISABLED  # disabled after the password step
    before = _failures()
    async with _minting_client(user, repo, audit) as client:
        reply = await client.post(_V, json={**_VERIFY, "method": method})
    assert (reply.status_code, reply.json()["detail"]) == (401, "account is disabled")
    assert repo.sessions == {}  # nothing was minted
    assert _moved(before) == {method: 1}
    (row,) = audit.writer.of(_LOGIN_FAILED)  # the one row the count matches
    assert (row["reason"], row["actor_user_id"]) == ("user_disabled", user)


def _no_audit_service() -> AuditService | None:
    return None


def _inactive_audit_service() -> AuditService | None:
    return AuditService(active=False)


def _refusing_audit_service() -> AuditService | None:
    audit = AuditService()
    audit.writer = _RefusingWriter()
    return audit


@pytest.mark.parametrize(
    "make_sink",
    [_no_audit_service, _inactive_audit_service, _refusing_audit_service],
    ids=["no_service", "inactive", "refused"],
)
async def test_the_refusal_of_a_disabled_user_counts_without_a_usable_audit_sink(
    make_sink: Callable[[], AuditService | None],
) -> None:
    # As the password step counts before it writes (`test_a_failed_login_counts_without_an_audit_
    # writer`): a sink that is missing, inactive or refuses the record never hides the failure.
    user, repo, before = uuid.uuid4(), FakeSessionRepository(), _failures()
    repo.user_statuses[str(user)] = UserStatus.DISABLED
    async with _minting_client(user, repo, make_sink()) as client:
        assert (await client.post(_V, json=_VERIFY)).status_code == 401
    assert _moved(before) == {"totp": 1}


@pytest.mark.parametrize("status", [UserStatus.ACTIVE, UserStatus.LOCKED, UserStatus.INVITED])
async def test_a_correct_second_factor_that_mints_a_session_does_not_count(
    status: UserStatus,
) -> None:
    # The count belongs to the refusal, not to the mint: `locked` and `invited` users are not
    # refused by the mint (login refuses `disabled` only).
    user, repo, audit, before = uuid.uuid4(), FakeSessionRepository(), AuditService(), _failures()
    repo.user_statuses[str(user)] = status
    async with _minting_client(user, repo, audit) as client:
        assert (await client.post(_V, json=_VERIFY)).status_code == 200
    assert _moved(before) == {} and audit.writer.of(_LOGIN_FAILED) == []
