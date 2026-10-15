"""#2097 Q2: `Server-Timing: argon2;dur=<ms>` rides only on the 200 `mfa_required` login
challenge, and only while the perf switch is on.

No refusal (401, 403, 423, 501, 503 and the throttled 401) ever carries it, so the header
cannot separate an unknown user from a wrong password (SR-014). The real `LoginService` and
`Hasher` run here; only the user store, the clocks and the perf counter are fakes.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from candleviewer.api.auth import MfaServiceLike, SessionMinterLike, make_auth_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.models import UserRecord, UserStatus
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_CSRF_CODEC = CsrfCodec(b"\x05" * 32)
_PASSWORD = "correct horse battery staple"  # noqa: S105 -- throwaway fixture password
_T0 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
#: TestClient's peer address, which the route hands to the per-IP throttle.
_CLIENT_IP = "testclient"


class _Auth:
    """`AuthServiceLike` for the login route only; no other auth surface is reachable."""

    def __init__(self, login: LoginService | None) -> None:
        self._login = login

    @property
    def is_active(self) -> bool:
        return self._login is not None

    @property
    def login(self) -> LoginService:
        assert self._login is not None
        return self._login

    @property
    def sessions_is_active(self) -> bool:
        return False

    @property
    def sessions(self) -> SessionMinterLike:
        raise AssertionError("POST /auth/login never mints a session")

    @property
    def mfa_is_active(self) -> bool:
        return False

    @property
    def mfa(self) -> MfaServiceLike:
        raise AssertionError("POST /auth/login never runs the MFA step")


class _Ticks:
    """Fake perf counter: every Argon2id verify reads 0.0 then 0.2125 s, so it measures
    exactly 212.5 ms. `reads` counts the clock reads, i.e. twice the verifies."""

    def __init__(self) -> None:
        self._values = itertools.cycle((0.0, 0.2125))
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return next(self._values)


@pytest.fixture(scope="module")
def password_hash() -> str:
    return asyncio.run(Hasher().hash(_PASSWORD))


def _service(
    user: UserRecord | None, ticks: _Ticks, throttle: PerIpLoginThrottle | None = None
) -> LoginService:
    repo = FakeUserRepository()
    if user is not None:
        repo.add(user)
    return LoginService(
        repo,
        Hasher(perf_counter=ticks),
        per_ip_throttle=throttle or PerIpLoginThrottle(clock=lambda: 0.0),
        clock=lambda: _T0,
    )


def _post_login(
    login: LoginService | None,
    *,
    server_timing: bool,
    identifier: str = "basiltt",
    password: str = _PASSWORD,
) -> Response:
    app = FastAPI()
    app.include_router(
        make_auth_router(_Auth(login), csrf=_CSRF_CODEC, server_timing=server_timing)
    )
    client = TestClient(app, raise_server_exceptions=False)
    resp: Response = client.post(
        "/auth/login", json={"identifier": identifier, "password": password}
    )
    return resp


def test_login_challenge_carries_the_measured_argon2_time_when_the_switch_is_on(
    password_hash: str,
) -> None:
    ticks = _Ticks()
    resp = _post_login(_service(make_user(password_hash=password_hash), ticks), server_timing=True)
    assert resp.status_code == 200
    assert resp.json()["status"] == "mfa_required"
    assert resp.headers["server-timing"] == "argon2;dur=212.5"
    assert ticks.reads == 2, "exactly one Argon2id verify is timed per login"


def test_login_challenge_carries_no_server_timing_when_the_switch_is_off(
    password_hash: str,
) -> None:
    resp = _post_login(
        _service(make_user(password_hash=password_hash), _Ticks()), server_timing=False
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "mfa_required"
    assert "server-timing" not in resp.headers


def _blocked_throttle() -> PerIpLoginThrottle:
    throttle = PerIpLoginThrottle(max_attempts=1, clock=lambda: 0.0)
    throttle.record_failure(_CLIENT_IP)
    return throttle


#: (case, user builder, identifier, password, throttle, expected status). Every case runs
#: with the switch ON; none may carry the header.
_REFUSALS: list[tuple[str, Callable[[str], UserRecord | None], str, str, bool, int]] = [
    ("unknown_user", lambda h: make_user(password_hash=h), "nobody", _PASSWORD, False, 401),
    ("wrong_password", lambda h: make_user(password_hash=h), "basiltt", "wrong pw", False, 401),
    ("throttled", lambda h: make_user(password_hash=h), "basiltt", _PASSWORD, True, 401),
    (
        "disabled",
        lambda h: make_user(password_hash=h, status=UserStatus.DISABLED),
        "basiltt",
        _PASSWORD,
        False,
        403,
    ),
    (
        "locked",
        lambda h: make_user(password_hash=h, locked_until=_T0 + timedelta(minutes=10)),
        "basiltt",
        _PASSWORD,
        False,
        423,
    ),
    (
        "no_mfa_method",
        lambda h: make_user(password_hash=h, mfa_required=False, mfa_methods=()),
        "basiltt",
        _PASSWORD,
        False,
        501,
    ),
]


@pytest.mark.parametrize(
    ("build_user", "identifier", "password", "throttled", "status"),
    [pytest.param(*case[1:], id=case[0]) for case in _REFUSALS],
)
def test_login_refusals_never_carry_server_timing_even_with_the_switch_on(
    password_hash: str,
    build_user: Callable[[str], UserRecord | None],
    identifier: str,
    password: str,
    throttled: bool,
    status: int,
) -> None:
    throttle = _blocked_throttle() if throttled else None
    service = _service(build_user(password_hash), _Ticks(), throttle)
    resp = _post_login(service, server_timing=True, identifier=identifier, password=password)
    assert resp.status_code == status
    assert "server-timing" not in resp.headers


def test_login_with_no_auth_backend_answers_503_without_server_timing() -> None:
    resp = _post_login(None, server_timing=True)
    assert resp.status_code == 503
    assert "server-timing" not in resp.headers
