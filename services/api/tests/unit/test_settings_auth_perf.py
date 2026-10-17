"""#2097 Q1: the `CV_AUTH_PERF_ENABLED` gate, the same rule as the #2086 test clock.

The switch mounts `GET /auth/_perf/argon2-params` and adds `Server-Timing` to the login
challenge. `Settings` refuses it before any module starts unless the environment is testnet
with no exchange key configured: never live, never demo, never next to a key.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer import settings as settings_module
from candleviewer.settings import Environment, Settings

#: An inert marker standing in for an exchange key value; never a credential.
_MARKER = "cv-2097-marker-not-a-key"
_EXCHANGE_ENV = ("CV_BYBIT_API_KEY", "CV_BYBIT_API_SECRET")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_ENVIRONMENT", "CV_AUTH_PERF_ENABLED", "CV_FEED", *_EXCHANGE_ENV):
        monkeypatch.delenv(name, raising=False)


def test_settings_auth_perf_is_off_by_default() -> None:
    assert Settings().auth_perf_enabled is False


@pytest.mark.parametrize("environment", ["live", "demo", "testnet"])
def test_settings_auth_perf_off_is_accepted_in_every_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", environment)
    monkeypatch.setenv("CV_AUTH_PERF_ENABLED", "false")
    assert Settings().auth_perf_enabled is False


@pytest.mark.parametrize("environment", ["live", "demo"])
def test_settings_auth_perf_is_refused_outside_testnet(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", environment)
    monkeypatch.setenv("CV_AUTH_PERF_ENABLED", "true")
    with pytest.raises(ValidationError, match="unless CV_ENVIRONMENT=testnet"):
        Settings()


@pytest.mark.parametrize("variable", _EXCHANGE_ENV)
def test_settings_auth_perf_is_refused_on_testnet_with_an_exchange_key(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.setenv("CV_AUTH_PERF_ENABLED", "true")
    monkeypatch.setenv(variable, _MARKER)
    with pytest.raises(ValidationError, match="while an exchange key") as refused:
        Settings()
    # The refusal names the switch only; it never echoes the key's value (C-12.6).
    assert _MARKER not in str(refused.value)
    assert _MARKER not in repr(refused.value.errors())


def test_settings_auth_perf_on_a_keyless_testnet_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", "testnet")
    monkeypatch.setenv("CV_AUTH_PERF_ENABLED", "true")
    settings = Settings()
    assert settings.auth_perf_enabled is True
    assert settings.environment is Environment.TESTNET
    assert settings.auth_perf_refusal() is None


def test_settings_test_clock_and_auth_perf_refusals_share_one_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One function owns the #2086 rule, so tightening it reaches every test or perf switch."""
    monkeypatch.setattr(settings_module, "_keyless_testnet_refusal", lambda switch, *_: switch)
    unvalidated = Settings.model_construct()
    assert unvalidated.test_clock_refusal() == "CV_TEST_CLOCK"
    assert unvalidated.auth_perf_refusal() == "CV_AUTH_PERF_ENABLED"
