"""E27-T03 (#836): `CV_EGRESS_IP`, `CV_KEY_SELFCHECK_INTERVAL_S` and `CV_RECV_WINDOW_MS` are
checked at startup.

The interval is at most hourly (C-12.2): no value may weaken the stored-key check (C-4.14); at
least a minute, so a typo cannot flood the audit log and the venue. The egress IP is one address
and the receive window one the REST client takes; anything else would fail or blind every key's
check, so it fails startup instead. The interval is no secret: its field name stays clear of the
redaction pattern, which names only `SecretStr` fields (C-12.6).
"""

from __future__ import annotations

import types
from typing import get_args

import pytest
from pydantic import SecretStr, ValidationError

from candleviewer.accounts.selfcheck import MAX_INTERVAL_S, MIN_INTERVAL_S
from candleviewer.exchange.bybit.config import SIGNED_REST_BASES, RestClientConfig
from candleviewer.settings import _REDACT_NAME_RE, Settings

INTERVAL = "CV_KEY_SELFCHECK_INTERVAL_S"


def test_the_defaults_check_hourly_with_no_egress_ip() -> None:
    settings = Settings()
    assert (settings.selfcheck_interval_s, settings.egress_ip) == (3600.0, None)


@pytest.mark.parametrize("interval_s", [0.0, -1.0, 0.001, 59.9, 3600.5, 21600.0])
def test_an_interval_longer_than_an_hour_or_shorter_than_a_minute_is_refused(
    interval_s: float,
) -> None:
    with pytest.raises(ValidationError, match=INTERVAL):
        Settings(CV_KEY_SELFCHECK_INTERVAL_S=interval_s)


@pytest.mark.parametrize("interval_s", [MIN_INTERVAL_S, MAX_INTERVAL_S])
def test_the_interval_bounds_are_the_jobs_own(interval_s: float) -> None:
    assert Settings(CV_KEY_SELFCHECK_INTERVAL_S=interval_s).selfcheck_interval_s == interval_s


def test_the_interval_is_read_from_its_documented_variable_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_SELFCHECK_INTERVAL_S", "120")  # the field's own name: not a variable
    monkeypatch.setenv(INTERVAL, "600")
    assert Settings().selfcheck_interval_s == 600.0


def test_the_interval_is_shown_by_the_redacting_repr() -> None:
    rendered = repr(Settings(CV_KEY_SELFCHECK_INTERVAL_S=600.0))
    assert "selfcheck_interval_s=600.0" in rendered


def test_every_setting_named_like_a_secret_is_a_secret_str() -> None:
    """The redaction pattern is name-based: a field it matches must hold a `SecretStr`, so the
    pattern hides only secrets and every secret stays hidden past `repr()` too."""
    named = {
        name: field.annotation
        for name, field in Settings.model_fields.items()
        if _REDACT_NAME_RE.search(name)
    }
    plain = [
        name
        for name, annotation in named.items()
        if annotation is not SecretStr
        and not (isinstance(annotation, types.UnionType) and SecretStr in get_args(annotation))
    ]
    assert named and plain == []


@pytest.mark.parametrize("window_ms", [0, -1, 10_001, 20_000])
def test_a_receive_window_the_rest_client_refuses_fails_startup(window_ms: int) -> None:
    with pytest.raises(ValidationError, match="recv_window_ms"):
        RestClientConfig(base_url=SIGNED_REST_BASES["demo"], recv_window_ms=window_ms)
    with pytest.raises(ValidationError, match="recv_window_ms"):
        Settings(recv_window_ms=window_ms)


@pytest.mark.parametrize("window_ms", [1, 10_000])
def test_a_receive_window_the_rest_client_takes_is_accepted(window_ms: int) -> None:
    RestClientConfig(base_url=SIGNED_REST_BASES["demo"], recv_window_ms=window_ms)
    assert Settings(recv_window_ms=window_ms).recv_window_ms == window_ms


@pytest.mark.parametrize(
    ("raw", "address"),
    [(" 203.0.113.7 ", "203.0.113.7"), ("2001:DB8::7", "2001:db8::7"), ("", None)],
)
def test_the_egress_ip_is_one_normalised_address_or_unset(raw: str, address: str | None) -> None:
    assert Settings(egress_ip=raw).egress_ip == address


@pytest.mark.parametrize("raw", ["203.0.113.0/24", "egress.example", "203.0.113.7:443", "*"])
def test_an_egress_ip_that_is_not_one_address_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError, match=r"CV_EGRESS_IP .* not an IP address"):
        Settings(egress_ip=raw)
