"""#4648: `CV_AUTH_LOGIN_FAILURE_FLOOR_MS`, the minimum time a failed sign-in takes.

A failed sign-in returns no sooner than this many milliseconds after the attempt started. The
setting defaults to `AUTH_LOGIN_FAILURE_FLOOR_MS` (500), which `LoginService` also uses as its
default, and a value outside 250-5000 refuses startup: zero included, so no setting turns the
minimum time off (C-4.14). Production wiring passes the setting through to `LoginService`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import SecretStr, ValidationError

from candleviewer.app import build_auth_service
from candleviewer.auth.login_service import LOGIN_FAILURE_FLOOR
from candleviewer.auth.service import AuthService
from candleviewer.settings import (
    AUTH_LOGIN_FAILURE_FLOOR_MAX_MS,
    AUTH_LOGIN_FAILURE_FLOOR_MIN_MS,
    AUTH_LOGIN_FAILURE_FLOOR_MS,
    Settings,
)
from tests.unit.auth.auth_fakes import FakeUserRepository

_ENV = "CV_AUTH_LOGIN_FAILURE_FLOOR_MS"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)


def test_login_failure_floor_setting_unset_defaults_to_500_ms() -> None:
    assert Settings().auth_login_failure_floor_ms == 500 == AUTH_LOGIN_FAILURE_FLOOR_MS


def test_login_failure_floor_default_matches_login_service_default() -> None:
    assert timedelta(milliseconds=Settings().auth_login_failure_floor_ms) == LOGIN_FAILURE_FLOOR


def test_login_failure_floor_bounds_are_250_and_5000_ms() -> None:
    assert (AUTH_LOGIN_FAILURE_FLOOR_MIN_MS, AUTH_LOGIN_FAILURE_FLOOR_MAX_MS) == (250, 5000)


@pytest.mark.parametrize("value", ["250", "500", "1200", "5000"])
def test_login_failure_floor_setting_within_bounds_is_accepted(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(_ENV, value)

    assert Settings().auth_login_failure_floor_ms == int(value)


@pytest.mark.parametrize("value", ["0", "-1", "1", "249"])
def test_login_failure_floor_setting_below_minimum_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(_ENV, value)

    with pytest.raises(ValidationError, match="auth_login_failure_floor_ms"):
        Settings()


@pytest.mark.parametrize("value", ["5001", "60000"])
def test_login_failure_floor_setting_above_maximum_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(_ENV, value)

    with pytest.raises(ValidationError, match="auth_login_failure_floor_ms"):
        Settings()


def test_login_failure_floor_setting_refusal_does_not_echo_other_settings() -> None:
    marker = "cv-4648-marker-not-a-secret"
    with pytest.raises(ValidationError) as caught:
        Settings(auth_login_failure_floor_ms=0, auth_pepper=SecretStr(marker))

    assert marker not in str(caught.value)
    assert all(error["loc"] == ("auth_login_failure_floor_ms",) for error in caught.value.errors())


def test_build_auth_service_passes_the_setting_to_auth_service() -> None:
    settings = Settings(  # test-only values, not credentials
        storage_backend="real",
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("pepper"),
        auth_login_failure_floor_ms=1234,
    )

    service = build_auth_service(settings)

    assert service._login_failure_floor == timedelta(milliseconds=1234)


async def test_auth_service_start_passes_the_floor_to_login_service() -> None:
    service = AuthService(
        repository=FakeUserRepository(),
        pepper="pepper",
        login_failure_floor=timedelta(milliseconds=1234),
    )

    await service.start(ctx=None)  # type: ignore[arg-type]  # no MFA store: ctx is not read

    assert service.login._failure_floor_s == pytest.approx(1.234)


def test_auth_service_default_floor_is_the_login_service_default() -> None:
    assert AuthService()._login_failure_floor == LOGIN_FAILURE_FLOOR
