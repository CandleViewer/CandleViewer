"""#2097: the auth perf switch at app build, and the `GET /auth/_perf/argon2-params` mount.

`Settings` refuses `CV_AUTH_PERF_ENABLED` outside a keyless testnet; `auth_perf_enabled()`
checks the same rule again when the app is built (the startup assertion), so even a `Settings`
that skipped validation never builds with the switch on in live, demo or next to a key. The
route's RBAC cells are in `tests/contract/rbac/test_auth_perf_matrix.py`, the login
`Server-Timing` header in `test_login_server_timing.py`. No network, no database (C-13.5).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer.api._generated.openapi_models import Problem
from candleviewer.api.auth_perf import auth_perf_enabled
from candleviewer.app import create_app
from candleviewer.settings import Environment, Settings

_PATH = "/auth/_perf/argon2-params"
_LOOPBACK = ("127.0.0.1", 50000)  # MeshOnlyMiddleware admits loopback
_SWITCH_ENV = ("CV_ENVIRONMENT", "CV_AUTH_PERF_ENABLED", "CV_BYBIT_API_KEY", "CV_BYBIT_API_SECRET")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read the environment too; none of these may leak in from the caller's shell."""
    for name in _SWITCH_ENV:
        monkeypatch.delenv(name, raising=False)


def _keyless_testnet() -> Settings:
    return Settings(environment=Environment.TESTNET, auth_perf_enabled=True)


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
    [(Environment.LIVE, None), (Environment.DEMO, None), (Environment.TESTNET, SecretStr("m"))],
    ids=["live", "demo", "testnet_with_key"],
)
def test_create_app_refuses_to_build_with_the_switch_on_where_the_gate_refuses_it(
    environment: Environment, key: SecretStr | None
) -> None:
    """`model_construct` skips validation; the app still never builds, so nothing is mounted."""
    unvalidated = Settings.model_construct(
        environment=environment, auth_perf_enabled=True, bybit_api_key=key
    )
    with pytest.raises(ValueError, match="CV_AUTH_PERF_ENABLED is refused"):
        create_app(unvalidated)


@pytest.mark.parametrize(
    ("settings", "status"),
    [(Settings, 404), (_keyless_testnet, 501)],
    ids=["default_not_mounted", "switch_on_mounted"],
)
def test_create_app_mounts_the_params_route_only_with_the_switch_on(
    settings: Callable[[], Settings], status: int
) -> None:
    """Mounted, the route still fails closed: the fake backend wires no session resolver, so
    it answers 501, never 200."""
    client = TestClient(create_app(settings()), client=_LOOPBACK, raise_server_exceptions=False)
    assert client.get(_PATH).status_code == status


def test_params_route_without_a_session_resolver_answers_a_501_not_implemented_problem() -> None:
    app = create_app(_keyless_testnet())
    response = TestClient(app, client=_LOOPBACK, raise_server_exceptions=False).get(_PATH)
    problem = Problem.model_validate(response.json(), strict=True)
    assert response.headers["content-type"] == "application/problem+json"
    assert (response.status_code, problem.status, problem.code) == (501, 501, "not_implemented")
