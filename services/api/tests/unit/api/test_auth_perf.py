"""#2097: `GET /auth/_perf/argon2-params`, the perf switch at app build, and its wiring.

The route reports the Argon2id parameters new password hashes use, owner-only (`admin:read`,
resolved server-side), and exists only while `CV_AUTH_PERF_ENABLED` is on. `Settings` refuses
the switch outside a keyless testnet; `auth_perf_enabled()` checks again at app build (the
startup assertion), so even a `Settings` that skipped validation never mounts the route in
live or demo. No network, no database (C-13.5).
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable

import pytest
from argon2 import extract_parameters
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.api._generated.openapi_models import Argon2Params
from candleviewer.api.auth_perf import auth_perf_enabled, make_auth_perf_router
from candleviewer.app import create_app
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.settings import Environment, Settings
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_PATH = "/auth/_perf/argon2-params"
_PASSWORD = "correct horse battery staple"  # noqa: S105 -- throwaway fixture password
_LOOPBACK = ("127.0.0.1", 50000)  # MeshOnlyMiddleware admits loopback


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read the environment too; none of these may leak in from the caller's shell."""
    for name in (
        "CV_ENVIRONMENT",
        "CV_AUTH_PERF_ENABLED",
        "CV_BYBIT_API_KEY",
        "CV_BYBIT_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


class _Principal:
    def __init__(self, *permissions: str) -> None:
        self._permissions = frozenset(permissions)

    def has(self, permission: str) -> bool:
        return permission in self._permissions


class _Resolver:
    def __init__(self, principal: _Principal | None) -> None:
        self._principal = principal

    async def resolve(self, request: Request) -> _Principal | None:
        return self._principal


def _get(resolver: _Resolver | None) -> TestClient:
    app = FastAPI()
    app.include_router(make_auth_perf_router(resolver))
    return TestClient(app, raise_server_exceptions=False)


def _keyless_testnet() -> Settings:
    return Settings(environment=Environment.TESTNET, auth_perf_enabled=True)


# -- the route --------------------------------------------------------------------------------


def test_argon2_params_gives_the_owner_the_parameters_new_hashes_embed() -> None:
    resp = _get(_Resolver(_Principal("admin:read"))).get(_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"m": 65536, "t": 3, "p": 4}
    assert Argon2Params.model_validate(body).model_dump() == body
    fresh = extract_parameters(asyncio.run(Hasher().hash(_PASSWORD)))
    assert (fresh.memory_cost, fresh.time_cost, fresh.parallelism) == (
        body["m"],
        body["t"],
        body["p"],
    )


@pytest.mark.parametrize(
    "permissions",
    [(), ("audit:read", "accounts:read", "orders:write")],
    ids=["no_permissions", "manager_permissions"],
)
def test_argon2_params_without_admin_read_is_403(permissions: tuple[str, ...]) -> None:
    resp = _get(_Resolver(_Principal(*permissions))).get(_PATH)
    assert resp.status_code == 403
    assert resp.headers["content-type"] == "application/problem+json"
    assert "m" not in resp.json()


def test_argon2_params_without_a_verified_session_is_401() -> None:
    resp = _get(_Resolver(None)).get(_PATH)
    assert resp.status_code == 401
    assert "m" not in resp.json()


def test_argon2_params_without_a_principal_resolver_fails_closed_with_501() -> None:
    resp = _get(None).get(_PATH)
    assert resp.status_code == 501
    assert "m" not in resp.json()


# -- the switch at app build ------------------------------------------------------------------


def test_auth_perf_enabled_is_false_and_silent_by_default() -> None:
    with capture_logs() as logs:
        assert auth_perf_enabled(Settings()) is False
    assert logs == []


def test_auth_perf_enabled_on_a_keyless_testnet_logs_the_boot_line() -> None:
    with capture_logs() as logs:
        assert auth_perf_enabled(_keyless_testnet()) is True
    assert [(e["event"], e["log_level"], e["environment"]) for e in logs] == [
        ("auth.perf_instrumentation_enabled", "warning", "testnet")
    ]


@pytest.mark.parametrize(
    ("environment", "key"),
    [(Environment.LIVE, None), (Environment.DEMO, None), (Environment.TESTNET, "marker")],
    ids=["live", "demo", "testnet_with_key"],
)
def test_auth_perf_enabled_refuses_settings_that_skipped_validation(
    environment: Environment, key: str | None
) -> None:
    unvalidated = Settings.model_construct(
        environment=environment, auth_perf_enabled=True, bybit_api_key=key
    )
    with pytest.raises(ValueError, match="CV_AUTH_PERF_ENABLED is refused"):
        auth_perf_enabled(unvalidated)


def test_create_app_refuses_to_build_with_the_switch_on_in_live() -> None:
    """The startup assertion: the app never builds, so nothing is mounted."""
    unvalidated = Settings.model_construct(environment=Environment.LIVE, auth_perf_enabled=True)
    with pytest.raises(ValueError, match="CV_AUTH_PERF_ENABLED is refused"):
        create_app(unvalidated)


# -- the real app -----------------------------------------------------------------------------


def test_create_app_by_default_does_not_mount_the_params_route() -> None:
    client = TestClient(create_app(Settings()), client=_LOOPBACK, raise_server_exceptions=False)
    assert client.get(_PATH).status_code == 404


def test_create_app_with_the_switch_on_mounts_the_params_route() -> None:
    """Mounted and fail-closed: the fake backend wires no session resolver, so 501, never 200."""
    app = create_app(_keyless_testnet())
    client = TestClient(app, client=_LOOPBACK, raise_server_exceptions=False)
    assert client.get(_PATH).status_code == 501


def _app_login(settings: Settings, password_hash: str) -> TestClient:
    """The real app with a real `LoginService` behind `/auth/login` (fake user store only)."""
    app = create_app(settings)
    repo = FakeUserRepository()
    repo.add(make_user(password_hash=password_hash))
    ticks = itertools.cycle((1.0, 1.0875))
    app.state.app_context.auth._login = LoginService(
        repo, Hasher(perf_counter=lambda: next(ticks)), per_ip_throttle=PerIpLoginThrottle()
    )
    return TestClient(app, client=_LOOPBACK, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def password_hash() -> str:
    return asyncio.run(Hasher().hash(_PASSWORD))


@pytest.mark.parametrize(
    ("settings", "header"),
    [(_keyless_testnet, "argon2;dur=87.5"), (Settings, None)],
    ids=["switch_on", "switch_off"],
)
def test_create_app_wires_the_switch_to_the_login_server_timing_header(
    password_hash: str, settings: Callable[[], Settings], header: str | None
) -> None:
    client = _app_login(settings(), password_hash)
    resp = client.post("/auth/login", json={"identifier": "basiltt", "password": _PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["status"] == "mfa_required"
    assert resp.headers.get("server-timing") == header
