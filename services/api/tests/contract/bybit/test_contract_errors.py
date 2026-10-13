"""E08-Q02 / E08-TC-F03, E08-TC-F06, E08-TC-A10: Bybit error payloads -> internal taxonomy."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
import respx

from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.errors import (
    ClockDriftError,
    DuplicateClientIdError,
    ExchangeError,
    InstrumentFilterError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._corpus import http_status, rest
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.contract.bybit._support import counter_value

BASE = "https://api-demo.bybit.com"
PATH = "/v5/market/kline"
HTML_503 = "<html><head><title>503 Service Temporarily Unavailable</title></head></html>"


async def _no_sleep(_s: float) -> None:
    return None


def _virtual_governor() -> TokenBucketGovernor:
    """Governor on a virtual clock whose sleep advances it: an IP hold (#1908)
    elapses instantly instead of really waiting."""
    now = [0.0]

    async def _sleep(seconds: float) -> None:
        now[0] += seconds

    return TokenBucketGovernor(
        default_capacity=1000.0, default_refill_per_s=1000.0, clock=lambda: now[0], sleep=_sleep
    )


def _client(max_retries: int = 0, **kw: Any) -> BybitRestClient:
    return BybitRestClient(
        RestClientConfig(base_url=BASE, max_retries=max_retries),
        governor=_virtual_governor(),
        sleep=_no_sleep,
        **kw,
    )


async def _get(client: BybitRestClient) -> dict[str, Any]:
    try:
        return await client.get_public(PATH)
    finally:
        await client.aclose()


@respx.mock
async def test_10018_surfaces_as_retryable_rate_limit_error_with_sanitised_message() -> None:
    body = rest("rest/error_10018.json")
    respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(200, json=body))
    before = counter_value(exchange_errors_total, **{"class": RateLimitError.code.value})
    with pytest.raises(RateLimitError) as info:
        await _get(_client())
    assert info.value.retryable is True and info.value.exchange_ret_code == 10018
    assert counter_value(exchange_errors_total, **{"class": RateLimitError.code.value}) > before


@respx.mock
async def test_10018_is_retried_with_backoff_then_succeeds() -> None:
    route = respx.get(f"{BASE}{PATH}")
    route.side_effect = [
        httpx.Response(200, json=rest("rest/error_10018.json")),
        httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}}),
    ]
    assert (await _get(_client(max_retries=2)))["retCode"] == 0
    assert route.call_count == 2


@respx.mock
async def test_10002_is_retried_exactly_once_then_raises_clock_drift() -> None:
    route = respx.get(f"{BASE}{PATH}").mock(
        return_value=httpx.Response(200, json=rest("rest/error_10002.json"))
    )
    with pytest.raises(ClockDriftError) as info:
        await _get(_client(max_retries=5, clock_offset_ms_provider=lambda: 0))
    assert info.value.retryable is False and route.call_count == 2


@respx.mock
async def test_5xx_is_retried_then_becomes_transport_error_without_leaking_the_body() -> None:
    err = "rest/error_503.json"
    route = respx.get(f"{BASE}{PATH}").mock(
        return_value=httpx.Response(http_status(err), text=HTML_503)
    )
    with pytest.raises(TransportError) as info:
        await _get(_client(max_retries=1))
    assert route.call_count == 2
    assert "Temporarily" not in str(info.value) and "<html" not in str(info.value)


@respx.mock
async def test_html_error_page_on_a_200_is_unknown_state_not_a_crash() -> None:
    respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(200, text=HTML_503))
    with pytest.raises(UnknownStateError) as info:
        await _get(_client())
    assert "<html" not in info.value.user_message


@respx.mock
async def test_truncated_json_is_unknown_state() -> None:
    respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(200, text='{"retCode":0,"res'))
    with pytest.raises(UnknownStateError):
        await _get(_client())


@respx.mock
async def test_missing_ret_code_and_wrong_type_never_pass_as_success() -> None:
    respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(200, json={"result": {}}))
    with pytest.raises(UnknownStateError):
        await _get(_client())


@respx.mock
async def test_unmapped_ret_code_is_unknown_state_with_raw_code_preserved_for_triage() -> None:
    body = {"retCode": 99999, "retMsg": "brand new error", "result": {}}
    respx.get(f"{BASE}{PATH}").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(UnknownStateError) as info:
        await _get(_client())
    assert info.value.exchange_ret_code == 99999


@pytest.mark.parametrize(
    ("msg", "expected"),
    [
        ("Order already exists: orderLinkId duplicate", DuplicateClientIdError),
        ("Invalid parameter qty", InstrumentFilterError),
    ],
)
def test_10001_is_disambiguated_by_message(msg: str, expected: type[ExchangeError]) -> None:
    err = map_ret_code(10001, msg)
    assert type(err) is expected and err.exchange_ret_code == 10001


@respx.mock
async def test_signed_request_error_path_never_logs_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(f"{BASE}/v5/account/wallet-balance").mock(
        return_value=httpx.Response(200, json=rest("rest/error_10018.json"))
    )
    signer = BybitSigner(fake_capability("CONTRACT-KEY-1234"), CREDENTIAL_ID)
    client = _client(max_retries=0, signer=signer)
    caplog.set_level(logging.DEBUG)
    try:
        with pytest.raises(RateLimitError):
            await client.signed_request("GET", "/v5/account/wallet-balance")
    finally:
        await client.aclose()
    assert "CONTRACT-SECRET-9" not in caplog.text and "CONTRACT-KEY-1234" not in caplog.text
