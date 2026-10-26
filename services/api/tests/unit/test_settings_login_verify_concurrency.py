"""#4663: `CV_AUTH_LOGIN_VERIFY_CONCURRENCY`, how many sign-in verifications run at a time.

An attempt beyond that many is refused at once with a retry-after. The setting defaults to
`AUTH_LOGIN_VERIFY_CONCURRENCY` (4), which `LoginService` also uses as its default, and a value
outside 1-32 refuses startup: zero included, so no setting refuses every sign-in. Production
wiring passes the setting through to `LoginService`.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from candleviewer.app import build_auth_service
from candleviewer.auth.login_service import LOGIN_VERIFY_CONCURRENCY
from candleviewer.auth.service import AuthService
from candleviewer.settings import (
    AUTH_LOGIN_VERIFY_CONCURRENCY,
    AUTH_LOGIN_VERIFY_CONCURRENCY_MAX,
    AUTH_LOGIN_VERIFY_CONCURRENCY_MIN,
    Settings,
)
from tests.unit.auth.auth_fakes import FakeUserRepository

_ENV = "CV_AUTH_LOGIN_VERIFY_CONCURRENCY"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)


def test_login_verify_concurrency_setting_unset_defaults_to_4() -> None:
    assert Settings().auth_login_verify_concurrency == 4 == AUTH_LOGIN_VERIFY_CONCURRENCY


def test_login_verify_concurrency_default_matches_login_service_default() -> None:
    assert Settings().auth_login_verify_concurrency == LOGIN_VERIFY_CONCURRENCY


def test_login_verify_concurrency_bounds_are_1_and_32() -> None:
    assert (AUTH_LOGIN_VERIFY_CONCURRENCY_MIN, AUTH_LOGIN_VERIFY_CONCURRENCY_MAX) == (1, 32)


@pytest.mark.parametrize("value", ["1", "4", "12", "32"])
def test_login_verify_concurrency_setting_within_bounds_is_accepted(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(_ENV, value)

    assert Settings().auth_login_verify_concurrency == int(value)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_login_verify_concurrency_setting_below_minimum_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(_ENV, value)

    with pytest.raises(ValidationError, match="auth_login_verify_concurrency"):
        Settings()


@pytest.mark.parametrize("value", ["33", "1000"])
def test_login_verify_concurrency_setting_above_maximum_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(_ENV, value)

    with pytest.raises(ValidationError, match="auth_login_verify_concurrency"):
        Settings()


def test_login_verify_concurrency_refusal_does_not_echo_other_settings() -> None:
    marker = "cv-4663-marker-not-a-secret"
    with pytest.raises(ValidationError) as caught:
        Settings(auth_login_verify_concurrency=0, auth_pepper=SecretStr(marker))

    assert marker not in str(caught.value)
    assert all(
        error["loc"] == ("auth_login_verify_concurrency",) for error in caught.value.errors()
    )


def test_build_auth_service_passes_the_bound_to_auth_service() -> None:
    settings = Settings(  # test-only values, not credentials
        storage_backend="real",
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("pepper"),
        auth_login_verify_concurrency=9,
    )

    service = build_auth_service(settings)

    assert service._login_verify_concurrency == 9


async def test_auth_service_start_passes_the_bound_to_login_service() -> None:
    service = AuthService(
        repository=FakeUserRepository(), pepper="pepper", login_verify_concurrency=9
    )

    await service.start(ctx=None)  # type: ignore[arg-type]  # no MFA store: ctx is not read

    assert service.login._admission.limit == 9


def test_auth_service_default_bound_is_the_login_service_default() -> None:
    assert AuthService()._login_verify_concurrency == LOGIN_VERIFY_CONCURRENCY


async def test_auth_service_gives_the_login_hasher_a_pool_as_large_as_the_bound() -> None:
    service = AuthService(
        repository=FakeUserRepository(), pepper="pepper", login_verify_concurrency=3
    )

    await service.start(ctx=None)  # type: ignore[arg-type]  # no MFA store: ctx is not read
    pool = service._login_hash_pool
    hasher_pool = service.login._hasher._executor

    assert pool is not None and hasher_pool is pool and pool._max_workers == 3
    await service.stop(1.0)
    assert service._login_hash_pool is None and pool._shutdown
