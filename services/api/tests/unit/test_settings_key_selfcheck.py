"""E27-T03 (#836): `CV_EGRESS_IP`, `CV_KEY_SELFCHECK_INTERVAL_S` and `CV_RECV_WINDOW_MS` are
checked at startup.

The interval is at most hourly (C-12.2): no value may weaken the stored-key check (C-4.14); at
least a minute, so a typo cannot flood the audit log and the venue. The egress IP is one address
and the receive window one the REST client takes; anything else would fail or blind every key's
check, so it fails startup instead.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.accounts.selfcheck import MAX_INTERVAL_S, MIN_INTERVAL_S
from candleviewer.exchange.bybit.config import SIGNED_REST_BASES, RestClientConfig
from candleviewer.settings import Settings


def test_the_defaults_check_hourly_with_no_egress_ip() -> None:
    settings = Settings()
    assert (settings.key_selfcheck_interval_s, settings.egress_ip) == (3600.0, None)


@pytest.mark.parametrize("interval_s", [0.0, -1.0, 0.001, 59.9, 3600.5, 21600.0])
def test_an_interval_longer_than_an_hour_or_shorter_than_a_minute_is_refused(
    interval_s: float,
) -> None:
    with pytest.raises(ValidationError, match="key_selfcheck_interval_s"):
        Settings(key_selfcheck_interval_s=interval_s)


@pytest.mark.parametrize("interval_s", [MIN_INTERVAL_S, MAX_INTERVAL_S])
def test_the_interval_bounds_are_the_jobs_own(interval_s: float) -> None:
    assert Settings(key_selfcheck_interval_s=interval_s).key_selfcheck_interval_s == interval_s


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
