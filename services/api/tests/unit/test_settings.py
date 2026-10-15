"""Settings tests (E02-T05 acceptance criterion 2 + redaction).

Given `CV_ENV=demo` and a `.env` file, when the settings object loads, then
the `Environment` enum resolves to `demo` and an invalid value raises a
pydantic `ValidationError` naming the allowed values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.settings import Environment, FeedMode, Settings, get_settings


def test_settings_environment_resolves_from_cv_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", "demo")
    settings = get_settings()
    assert settings.environment == Environment.DEMO


def test_settings_invalid_environment_raises_validation_error_naming_allowed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", "sandbox")
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    message = str(exc_info.value)
    for allowed in ("live", "demo", "testnet"):
        assert allowed in message


def test_settings_env_file_layering_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CV_ENVIRONMENT=testnet\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # Env var wins over .env file (layering precedence, 20-architecture.md Sec.7.2).
    monkeypatch.setenv("CV_ENVIRONMENT", "live")
    settings = Settings()
    assert settings.environment == Environment.LIVE


def test_settings_env_file_used_when_no_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CV_ENVIRONMENT=testnet\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CV_ENVIRONMENT", raising=False)
    settings = Settings()
    assert settings.environment == Environment.TESTNET


def test_settings_missing_required_dsn_uses_documented_default() -> None:
    # M1 ships a safe local default (never a required-but-unset secret) so
    # `create_app()` can construct without a real Postgres reachable.
    settings = get_settings()
    assert settings.pg_dsn.get_secret_value().startswith("postgresql+asyncpg://")


def test_settings_feed_mode_defaults_to_synthetic() -> None:
    assert get_settings().feed == FeedMode.SYNTHETIC


def test_settings_bind_host_rejects_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_BIND_HOST", "0.0.0.0")  # noqa: S104 - asserting the guard rejects it
    with pytest.raises(ValidationError):
        get_settings()


def test_settings_repr_redacts_dsn_and_secret_fields() -> None:
    settings = get_settings()
    rendered = repr(settings)
    assert "postgresql" not in rendered
    assert "**redacted**" in rendered


def test_settings_repr_does_not_redact_non_secret_fields() -> None:
    settings = get_settings()
    rendered = repr(settings)
    assert "environment=" in rendered


def test_settings_feed_live_without_credentials_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_FEED", "live")
    monkeypatch.delenv("CV_BYBIT_API_KEY", raising=False)
    monkeypatch.delenv("CV_BYBIT_API_SECRET", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    message = str(exc_info.value)
    assert "CV_FEED=live" in message
    assert "CV_BYBIT_API_KEY" in message


def test_settings_feed_live_error_never_echoes_credential_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_FEED", "live")
    monkeypatch.setenv("CV_BYBIT_API_KEY", "super-secret-value-should-not-leak")
    monkeypatch.delenv("CV_BYBIT_API_SECRET", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "super-secret-value-should-not-leak" not in str(exc_info.value)


def test_settings_feed_live_with_credentials_constructs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_FEED", "live")
    monkeypatch.setenv("CV_BYBIT_API_KEY", "k")
    monkeypatch.setenv("CV_BYBIT_API_SECRET", "s")
    settings = get_settings()
    assert settings.feed == FeedMode.LIVE


def test_settings_feed_rate_hz_defaults_positive() -> None:
    assert get_settings().feed_rate_hz > 0


def test_settings_feed_rate_hz_rejects_non_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_FEED_RATE_HZ", "0")
    with pytest.raises(ValidationError):
        get_settings()


def test_settings_ws_connect_rate_defaults_to_20_per_minute() -> None:
    assert get_settings().ws_max_auths_per_user_per_min == 20


@pytest.mark.parametrize("value", [1, 20, 600])
def test_settings_ws_connect_rate_accepts_its_documented_bounds(
    monkeypatch: pytest.MonkeyPatch, value: int
) -> None:
    monkeypatch.setenv("CV_WS_MAX_AUTHS_PER_USER_PER_MIN", str(value))
    assert get_settings().ws_max_auths_per_user_per_min == value


@pytest.mark.parametrize("value", ["0", "-1", "601", "1.5", "many"])
def test_settings_ws_connect_rate_rejects_values_outside_1_to_600(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("CV_WS_MAX_AUTHS_PER_USER_PER_MIN", value)
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "ws_max_auths_per_user_per_min" in str(exc_info.value)
