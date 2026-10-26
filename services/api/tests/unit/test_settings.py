"""Settings tests (E02-T05 acceptance criterion 2 + redaction).

Given `CV_ENV=demo` and a `.env` file, when the settings object loads, then
the `Environment` enum resolves to `demo` and an invalid value raises a
pydantic `ValidationError` naming the allowed values.
"""

from __future__ import annotations

from decimal import Decimal
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


@pytest.mark.parametrize("value", [1, 7, 20])
def test_settings_ws_connect_rate_accepts_its_documented_bounds(
    monkeypatch: pytest.MonkeyPatch, value: int
) -> None:
    monkeypatch.setenv("CV_WS_MAX_AUTHS_PER_USER_PER_MIN", str(value))
    assert get_settings().ws_max_auths_per_user_per_min == value


@pytest.mark.parametrize("value", ["0", "-1", "21", "600", "1.5", "many"])
def test_settings_ws_connect_rate_rejects_values_outside_1_to_20(  # #415: lowered, never raised
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("CV_WS_MAX_AUTHS_PER_USER_PER_MIN", value)
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "ws_max_auths_per_user_per_min" in str(exc_info.value)


def test_settings_oms_runtime_defaults_are_the_20_7_2_rows() -> None:
    """#913 slice 3: `CV_OMS_SUBMIT_TIMEOUT_MS`, `_INFLIGHT_STUCK_S`, `_STARTUP_WAIT_S`, `_DRAIN_S`
    and `CV_TRADING_LIVE_ENABLED`, live trading off by default."""
    s = get_settings()
    assert (s.oms_submit_timeout_ms, s.oms_inflight_stuck_s, s.oms_startup_wait_s) == (
        5000,
        30.0,
        30.0,
    )
    assert (s.oms_drain_s, s.trading_live_enabled) == (10.0, False)
    assert s.oms_price_band_pct == Decimal("0.05")


_OMS_ACCEPTED = [
    ({"CV_OMS_SUBMIT_TIMEOUT_MS": "1000"}, "oms_submit_timeout_ms", 1000),
    (
        {"CV_OMS_SUBMIT_TIMEOUT_MS": "6000", "CV_OMS_INFLIGHT_STUCK_S": "19"},
        "oms_submit_timeout_ms",
        6000,
    ),
    ({"CV_OMS_INFLIGHT_STUCK_S": "17.5"}, "oms_inflight_stuck_s", 17.5),  # 5 s + 12 s, and above
    ({"CV_OMS_INFLIGHT_STUCK_S": "120"}, "oms_inflight_stuck_s", 120.0),
    ({"CV_OMS_STARTUP_WAIT_S": "5"}, "oms_startup_wait_s", 5.0),
    ({"CV_OMS_STARTUP_WAIT_S": "45"}, "oms_startup_wait_s", 45.0),
    ({"CV_OMS_DRAIN_S": "1"}, "oms_drain_s", 1.0),
    ({"CV_OMS_DRAIN_S": "10"}, "oms_drain_s", 10.0),
    ({"CV_TRADING_LIVE_ENABLED": "true"}, "trading_live_enabled", True),
    ({"CV_OMS_PRICE_BAND_PCT": "0.005"}, "oms_price_band_pct", Decimal("0.005")),
    ({"CV_OMS_PRICE_BAND_PCT": "0.20"}, "oms_price_band_pct", Decimal("0.20")),
]


@pytest.mark.parametrize(("env", "field", "value"), _OMS_ACCEPTED)
def test_settings_oms_runtime_bounds_take_each_value_in_range(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], field: str, value: object
) -> None:
    for name, text in env.items():
        monkeypatch.setenv(name, text)
    assert getattr(get_settings(), field) == value


@pytest.mark.parametrize(
    ("env", "field"),
    [
        ({"CV_OMS_SUBMIT_TIMEOUT_MS": "999"}, "oms_submit_timeout_ms"),
        ({"CV_OMS_SUBMIT_TIMEOUT_MS": "6001"}, "oms_submit_timeout_ms"),  # inside the 1 s margin
        ({"CV_OMS_INFLIGHT_STUCK_S": "17"}, "oms_inflight_stuck_s"),  # = 5 s + 12 s, not above
        (
            {"CV_OMS_SUBMIT_TIMEOUT_MS": "6000", "CV_OMS_INFLIGHT_STUCK_S": "18"},
            "oms_inflight_stuck_s",
        ),
        ({"CV_OMS_INFLIGHT_STUCK_S": "120.5"}, "oms_inflight_stuck_s"),  # SEC-S3D-02's ceiling
        ({"CV_OMS_INFLIGHT_STUCK_S": "nan"}, "oms_inflight_stuck_s"),
        ({"CV_OMS_STARTUP_WAIT_S": "4.9"}, "oms_startup_wait_s"),
        ({"CV_OMS_STARTUP_WAIT_S": "45.5"}, "oms_startup_wait_s"),  # past the 60 s smoke window
        ({"CV_OMS_DRAIN_S": "0.5"}, "oms_drain_s"),
        ({"CV_OMS_DRAIN_S": "10.5"}, "oms_drain_s"),  # leaves under 5 s of the module's grace
        ({"CV_OMS_PRICE_BAND_PCT": "0.0049"}, "oms_price_band_pct"),
        ({"CV_OMS_PRICE_BAND_PCT": "0.21"}, "oms_price_band_pct"),
        ({"CV_OMS_PRICE_BAND_PCT": "0"}, "oms_price_band_pct"),  # no off value (C-4.14)
    ],
)
def test_settings_oms_runtime_bounds_refuse_each_value_out_of_range(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], field: str
) -> None:
    for name, text in env.items():
        monkeypatch.setenv(name, text)
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert field in str(exc_info.value)
