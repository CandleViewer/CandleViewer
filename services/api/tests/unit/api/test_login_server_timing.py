"""#2097 Q2: `Server-Timing: argon2;dur=<ms>` rides only on the 200 `mfa_required` login
challenge, and only while the perf switch is on.

No refusal (401, 403, 423, 501, 503 and the throttled 401) ever carries it, so the header
cannot separate an unknown user from a wrong password (SR-014). The real `create_app()`,
`LoginService` and `Hasher` run; only the user store, the clocks and the perf counter are fakes.
"""

from __future__ import annotations

import asyncio
import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from candleviewer.app import create_app
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, MfaMethodKind, UserStatus
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.settings import Environment, Settings
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_PASSWORD = "correct horse battery staple"  # noqa: S105 -- throwaway fixture password
_T0 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_LOOPBACK = ("127.0.0.1", 50000)  # MeshOnlyMiddleware admits loopback; the throttle keys on it
_SWITCH_ENV = ("CV_ENVIRONMENT", "CV_AUTH_PERF_ENABLED", "CV_BYBIT_API_KEY", "CV_BYBIT_API_SECRET")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SWITCH_ENV:
        monkeypatch.delenv(name, raising=False)


class _Ticks:
    """Fake perf counter: every Argon2id verify reads 0.0 then 0.2125 s, so it measures
    exactly 212.5 ms. `reads` counts the clock reads, i.e. twice the verifies."""

    def __init__(self) -> None:
        self._values = itertools.cycle((0.0, 0.2125))
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return next(self._values)


class _ChallengeWithoutVerify(LoginService):
    """Issues the challenge without any Argon2id verify, so this request has no time to report."""

    async def login(self, request: LoginRequest, *, source_ip: str) -> MfaChallengeResult:
        token = "opaque-fixture-token"  # noqa: S105 -- inert fixture value, never a credential
        return MfaChallengeResult(mfa_token=token, methods=(MfaMethodKind.TOTP,))


@pytest.fixture(scope="module")
def password_hash() -> str:
    return asyncio.run(Hasher().hash(_PASSWORD))


def _service(
    password_hash: str, ticks: _Ticks, user: dict[str, Any] | None, *, throttled: bool = False
) -> LoginService:
    """*user* holds `make_user` overrides; None leaves the store empty (an unknown user)."""
    repo = FakeUserRepository()
    if user is not None:
        repo.add(make_user(password_hash=password_hash, **user))
    throttle = PerIpLoginThrottle(max_attempts=1, clock=lambda: 0.0)
    if throttled:
        throttle.record_failure(_LOOPBACK[0])
    return LoginService(
        repo, Hasher(perf_counter=ticks), per_ip_throttle=throttle, clock=lambda: _T0
    )


def _keyless_testnet() -> Settings:
    return Settings(environment=Environment.TESTNET, auth_perf_enabled=True)


def _login(service: LoginService | None, *, switch_on: bool, password: str = _PASSWORD) -> Response:
    """POST /auth/login on the real app: the switch on a keyless testnet, or default settings."""
    app = create_app(_keyless_testnet() if switch_on else Settings())
    app.state.app_context.auth._login = service  # the fake backend wires no login service
    client = TestClient(app, client=_LOOPBACK, raise_server_exceptions=False)
    resp: Response = client.post(
        "/auth/login", json={"identifier": "basiltt", "password": password}
    )
    return resp


@pytest.mark.parametrize(
    ("switch_on", "header"), [(True, "argon2;dur=212.5"), (False, None)], ids=["on", "off"]
)
def test_login_challenge_carries_the_measured_argon2_time_only_with_the_switch_on(
    password_hash: str, switch_on: bool, header: str | None
) -> None:
    ticks = _Ticks()
    resp = _login(_service(password_hash, ticks, {}), switch_on=switch_on)
    assert resp.status_code == 200
    assert resp.json()["status"] == "mfa_required"
    assert resp.headers.get("server-timing") == header
    assert ticks.reads == 2, "exactly one Argon2id verify is timed per login"


@pytest.mark.parametrize(
    ("user", "password", "throttled", "status"),
    [
        pytest.param(None, _PASSWORD, False, 401, id="unknown_user"),
        pytest.param({}, "wrong password", False, 401, id="wrong_password"),
        pytest.param({}, _PASSWORD, True, 401, id="throttled"),
        pytest.param({"status": UserStatus.DISABLED}, _PASSWORD, False, 403, id="disabled"),
        pytest.param(
            {"locked_until": _T0 + timedelta(minutes=10)}, _PASSWORD, False, 423, id="locked"
        ),
        pytest.param(
            {"mfa_required": False, "mfa_methods": ()}, _PASSWORD, False, 501, id="no_mfa"
        ),
    ],
)
def test_login_refusals_never_carry_server_timing_even_with_the_switch_on(
    password_hash: str, user: dict[str, Any] | None, password: str, throttled: bool, status: int
) -> None:
    service = _service(password_hash, _Ticks(), user, throttled=throttled)
    resp = _login(service, switch_on=True, password=password)
    assert resp.status_code == status
    assert "server-timing" not in resp.headers


def test_login_with_no_auth_backend_answers_503_without_server_timing() -> None:
    resp = _login(None, switch_on=True)
    assert resp.status_code == 503
    assert "server-timing" not in resp.headers


def test_login_challenge_without_an_argon2_verify_carries_no_server_timing() -> None:
    """No verify ran in this request, so there is no time to report: the challenge goes out
    without the header instead of failing to format a missing value."""
    resp = _login(_ChallengeWithoutVerify(FakeUserRepository(), Hasher()), switch_on=True)
    assert resp.status_code == 200
    assert resp.json()["status"] == "mfa_required"
    assert "server-timing" not in resp.headers
