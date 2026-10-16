"""#2086 part (a): the `CV_TEST_CLOCK` gate (Q1; E16-FR-11, the strictest source).

The server test clock moves auth time. In live or demo, or next to an exchange key, it could
revive an expired step-up or release a lockout early, so `Settings` refuses it before any
module starts unless the environment is testnet with no exchange key configured.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.settings import Environment, Settings

_FILE = "/run/cv-test-clock/offset"
_CLOCK_ON = {"CV_TEST_CLOCK": "true", "CV_TEST_CLOCK_FILE": _FILE}
_TESTNET = "unless CV_ENVIRONMENT=testnet"
#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-2728-marker-not-a-secret"


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


@pytest.mark.parametrize(
    ("secret", "env"),
    [
        ("CV_BYBIT_API_KEY", {"CV_ENVIRONMENT": "live", **_CLOCK_ON}),
        ("CV_BYBIT_API_KEY", {"CV_ENVIRONMENT": "testnet", **_CLOCK_ON}),
        ("CV_AUTH_PEPPER", {"CV_ENVIRONMENT": "testnet", "CV_TEST_CLOCK": "true"}),
        (
            "CV_AUTH_PEPPER",
            {"CV_ENVIRONMENT": "testnet", "CV_TEST_CLOCK": "1", "CV_TEST_CLOCK_FILE": "x"},
        ),
    ],
    ids=["environment", "exchange-key", "set-together", "path"],
)
def test_settings_test_clock_refusal_never_echoes_another_setting(
    monkeypatch: pytest.MonkeyPatch, secret: str, env: dict[str, str]
) -> None:
    """#2728: `hide_input_in_errors` hides input from `str()` only, and a model validator's
    `errors()` and `json()` carry every setting. The gate is a field validator (C-12.6)."""
    with pytest.raises(ValidationError, match="CV_TEST_CLOCK") as refused:
        _settings(monkeypatch, **{secret: _MARKER}, **env)

    error = refused.value
    assert "input_value" not in str(error)
    assert _MARKER not in str(error)
    assert _MARKER not in repr(error.errors())
    assert _MARKER not in error.json()


@pytest.mark.parametrize(
    ("path", "reason"),
    [("offset", "must be an absolute path"), ("/run/cv-test-clock/../offset", "must not contain")],
    ids=["relative", "dot-dot"],
)
def test_settings_test_clock_file_must_be_absolute_without_dot_dot(
    monkeypatch: pytest.MonkeyPatch, path: str, reason: str
) -> None:
    """#2728: checked at load, before any module starts."""
    env = {"CV_ENVIRONMENT": "testnet", "CV_TEST_CLOCK": "true", "CV_TEST_CLOCK_FILE": path}

    with pytest.raises(ValidationError, match=reason):
        _settings(monkeypatch, **env)


def test_settings_test_clock_file_must_not_be_a_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    link = tmp_path / "offset"
    link.symlink_to(tmp_path / "target")
    env = {"CV_ENVIRONMENT": "testnet", "CV_TEST_CLOCK": "true", "CV_TEST_CLOCK_FILE": str(link)}

    with pytest.raises(ValidationError, match="must not be a symlink"):
        _settings(monkeypatch, **env)


def test_settings_test_clock_file_must_not_be_under_a_symlinked_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#2728: each read refuses only a last-component symlink (`O_NOFOLLOW`), so the load
    check covers the directories above it too."""
    (tmp_path / "real").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "real")
    path = str(tmp_path / "linked" / "offset")
    env = {"CV_ENVIRONMENT": "testnet", "CV_TEST_CLOCK": "true", "CV_TEST_CLOCK_FILE": path}

    with pytest.raises(ValidationError, match="must not be under a symlinked directory"):
        _settings(monkeypatch, **env)
