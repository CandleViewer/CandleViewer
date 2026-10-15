"""#2086 part (a): the `CV_TEST_CLOCK` gate (Q1; E16-FR-11, the strictest source).

The server test clock moves auth time. In live or demo, or next to an exchange key, it could
revive an expired step-up or release a lockout early, so `Settings` refuses it before any
module starts unless the environment is testnet with no exchange key configured.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.settings import Environment, Settings

_FILE = "/run/cv-test-clock/offset"
_CLOCK_ON = {"CV_TEST_CLOCK": "true", "CV_TEST_CLOCK_FILE": _FILE}
_TESTNET = "unless CV_ENVIRONMENT=testnet"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_ENVIRONMENT", "CV_BYBIT_API_KEY", "CV_BYBIT_API_SECRET", *_CLOCK_ON):
        monkeypatch.delenv(name, raising=False)


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings()


def test_settings_test_clock_defaults_off_and_unset() -> None:
    settings = Settings()

    assert (settings.test_clock, settings.test_clock_file) == (False, None)


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({"CV_ENVIRONMENT": "live", **_CLOCK_ON}, _TESTNET),
        ({"CV_ENVIRONMENT": "demo", **_CLOCK_ON}, _TESTNET),
        ({"CV_ENVIRONMENT": "testnet", "CV_BYBIT_API_KEY": "k", **_CLOCK_ON}, "exchange key"),
        ({"CV_ENVIRONMENT": "testnet", "CV_BYBIT_API_SECRET": "s", **_CLOCK_ON}, "exchange key"),
        ({"CV_ENVIRONMENT": "live", "CV_TEST_CLOCK_FILE": _FILE}, _TESTNET),
        ({"CV_ENVIRONMENT": "testnet", "CV_TEST_CLOCK": "true"}, "must be set together"),
        ({"CV_ENVIRONMENT": "testnet", "CV_TEST_CLOCK_FILE": _FILE}, "must be set together"),
    ],
    ids=["live", "demo", "api-key", "api-secret", "live-file-only", "flag-only", "file-only"],
)
def test_settings_test_clock_is_refused_unless_fully_set_on_a_keyless_testnet(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        _settings(monkeypatch, **env)


def test_settings_test_clock_on_a_keyless_testnet_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch, CV_ENVIRONMENT="testnet", **_CLOCK_ON)

    assert settings.environment is Environment.TESTNET
    assert (settings.test_clock, settings.test_clock_file) == (True, _FILE)
    assert settings.test_clock_refusal() is None


def test_settings_test_clock_refusal_never_echoes_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "canary-exchange-key-must-never-be-echoed"

    with pytest.raises(ValidationError) as exc_info:
        _settings(monkeypatch, CV_ENVIRONMENT="testnet", CV_BYBIT_API_KEY=canary, **_CLOCK_ON)

    message = str(exc_info.value)
    assert "exchange key" in message
    assert "input_value" not in message
    assert canary[-12:] not in message
