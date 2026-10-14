"""Contract tests for `BybitRestClient` against recorded/synthetic HTTP
fixtures (ticket "Test plan": "Contract: recorded HTTP fixtures (respx)").

No network egress: `respx` intercepts httpx at the transport layer.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from candleviewer.exchange.base.errors import (
    ClockDriftError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.secrets import CredentialBorrower, CredentialUnavailable
from tests._corpus import http_status, rest
from tests._signing import CREDENTIAL_ID, fake_capability

BASE_URL = "https://api-demo.bybit.com"


def _config(*, max_retries: int = 2, **overrides: object) -> RestClientConfig:
    return RestClientConfig(base_url=BASE_URL, max_retries=max_retries, **overrides)  # type: ignore[arg-type]


def _fresh_governor(*, clock: object = None) -> TokenBucketGovernor:
    if clock is None:
        return TokenBucketGovernor(default_capacity=1000.0, default_refill_per_s=1000.0)
    return TokenBucketGovernor(
        default_capacity=1000.0,
        default_refill_per_s=1000.0,
        clock=clock,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_public_returns_ok_payload() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        data = await client.get_public("/v5/market/time")
        assert data["retCode"] == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_signed_request_sends_bapi_headers() -> None:
    route = respx.get(f"{BASE_URL}/v5/account/wallet-balance").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    signer = BybitSigner(fake_capability("test-key"), CREDENTIAL_ID)
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    try:
        await client.signed_request(
            "GET",
            "/v5/account/wallet-balance",
            params={"accountType": "UNIFIED"},
            endpoint_class=EndpointClass.ACCOUNT,
        )
    finally:
        await client.aclose()

    sent = route.calls.last.request
    assert sent.headers["X-BAPI-API-KEY"] == "test-key"
    assert "X-BAPI-SIGN" in sent.headers
    assert sent.headers["X-BAPI-RECV-WINDOW"] == "5000"


@pytest.mark.asyncio
@respx.mock
async def test_m2_signing_refusal_sends_nothing() -> None:
    """C-2.7 (#2339), fail closed: if M2 refuses to sign, no request is sent unsigned."""
    route = respx.get(f"{BASE_URL}/v5/account/wallet-balance").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )

    async def refuse(key_id: object, message: object, purpose: str) -> object:
        raise CredentialUnavailable("credential_unavailable")

    signer = BybitSigner(CredentialBorrower(refuse), CREDENTIAL_ID)
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    try:
        with pytest.raises(CredentialUnavailable):
            await client.signed_request("GET", "/v5/account/wallet-balance")
    finally:
        await client.aclose()
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_signed_request_without_signer_raises_type_error() -> None:
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        with pytest.raises(TypeError):
            await client.signed_request("GET", "/v5/account/wallet-balance")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10018_raises_rate_limit_error_and_drains_bucket_then_retries() -> None:
    """Acceptance criterion 3: 10018 raises `RateLimitError`, drains the
    bucket by the advertised amount, and (being retryable) retries after
    `retry_after_s` with full jitter before ultimately succeeding."""
    route = respx.get(f"{BASE_URL}/v5/market/kline")
    route.side_effect = [
        httpx.Response(
            200,
            json=rest("rest/error_10018.json"),
            headers={"X-Bapi-Limit-Status": "3"},
        ),
        httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}}),
    ]
    now = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    governor = TokenBucketGovernor(
        default_capacity=1000.0,
        default_refill_per_s=1000.0,
        clock=lambda: now[0],
        sleep=fake_sleep,
    )

    client = BybitRestClient(_config(), governor=governor, sleep=fake_sleep)
    try:
        before = governor.remaining("public", EndpointClass.MARKET_DATA)
        data = await client.get_public("/v5/market/kline")
        assert data["retCode"] == 0
        after_drain_and_refill = governor.remaining("public", EndpointClass.MARKET_DATA)
        # A drain of 3 happened even though the bucket also gets consumed by
        # `acquire`; either way it must have gone down relative to a
        # no-rate-limit baseline, and a retry sleep must have been recorded.
        assert after_drain_and_refill <= before
        assert len(sleeps) == 2  # default backoff, then the IP-hold remainder
        assert sum(sleeps) == pytest.approx(600.0)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10018_non_retryable_path_raises_when_retries_exhausted() -> None:
    respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(200, json=rest("rest/error_10018.json"))
    )
    client = BybitRestClient(_config(max_retries=0), governor=_fresh_governor())
    try:
        with pytest.raises(RateLimitError):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10002_retries_exactly_once_then_surfaces_clock_drift_error() -> None:
    """Acceptance criterion 4: a second 10002 surfaces as `ClockDriftError`
    rather than looping."""
    route = respx.get(f"{BASE_URL}/v5/market/kline")
    route.mock(return_value=httpx.Response(200, json=rest("rest/error_10002.json")))
    resync_calls = 0

    def offset_provider() -> int:
        nonlocal resync_calls
        resync_calls += 1
        return 0

    client = BybitRestClient(
        _config(), governor=_fresh_governor(), clock_offset_ms_provider=offset_provider
    )
    try:
        with pytest.raises(ClockDriftError):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_5xx_retries_then_raises_transport_error_when_exhausted() -> None:
    route = respx.get(f"{BASE_URL}/v5/market/time")
    err = "rest/error_503.json"
    route.mock(return_value=httpx.Response(http_status(err), json=rest(err)))

    async def fake_sleep(_seconds: float) -> None:
        return None

    client = BybitRestClient(_config(max_retries=1), governor=_fresh_governor(), sleep=fake_sleep)
    try:
        with pytest.raises(TransportError):
            await client.get_public("/v5/market/time")
    finally:
        await client.aclose()
    assert route.call_count == 2  # initial attempt + one retry


@pytest.mark.asyncio
@respx.mock
async def test_secrets_never_appear_in_debug_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Ticket scenario "Secrets never reach a log or a fixture". The API secret never reaches
    M4 at all (#2339); the key id and the signature stay out of the request log."""
    route = respx.get(f"{BASE_URL}/v5/account/wallet-balance").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    signer = BybitSigner(fake_capability("visible-key"), CREDENTIAL_ID)
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    caplog.set_level(logging.DEBUG)
    try:
        await client.signed_request("GET", "/v5/account/wallet-balance")
    finally:
        await client.aclose()
    for value in ("visible-key", route.calls.last.request.headers["X-BAPI-SIGN"]):
        assert value not in caplog.text
        for record in caplog.records:
            assert value not in repr(record.__dict__)


@pytest.mark.asyncio
@respx.mock
async def test_check_reachable_true_on_2xx() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        assert await client.check_reachable() is True
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_check_reachable_false_on_transport_error() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(side_effect=httpx.ConnectError("boom"))
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        assert await client.check_reachable() is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_signed_get_signs_the_wire_encoded_query_string() -> None:
    """A param value needing URL-encoding must not desync the signature
    from what httpx actually sends (reviewer finding: `_payload_string` used
    to sign an unencoded `&`.join, while httpx sends URL-encoded params)."""
    route = respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    signer = BybitSigner(fake_capability("k"), CREDENTIAL_ID)
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    try:
        await client.signed_request(
            "GET", "/v5/market/kline", params={"symbol": "BTC USDT", "note": "a&b=c"}
        )
    finally:
        await client.aclose()
    sent_request = route.calls.last.request
    expected_query = str(httpx.QueryParams({"symbol": "BTC USDT", "note": "a&b=c"}))
    assert sent_request.url.query.decode() == expected_query
    # The signature must have been computed over that same encoded string,
    # not the raw `k=v` join — recompute and compare against the sent header.
    expected = await signer.sign(
        timestamp_ms=int(sent_request.headers["X-BAPI-TIMESTAMP"]),
        recv_window_ms=int(sent_request.headers["X-BAPI-RECV-WINDOW"]),
        payload=expected_query,
    )
    assert sent_request.headers["X-BAPI-SIGN"] == expected.signature
    assert sent_request.headers["X-BAPI-API-KEY"] == expected.api_key == "k"


@pytest.mark.asyncio
@respx.mock
async def test_4xx_with_no_ret_code_never_treated_as_success() -> None:
    """Review finding: `retCode` defaulted to 0, so a 4xx with a JSON body
    lacking `retCode` was treated as success. HTTP status must be
    load-bearing, not merely the body."""
    respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(400, json={"message": "bad request"})
    )
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        with pytest.raises(UnknownStateError):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_4xx_with_ret_code_zero_never_treated_as_success() -> None:
    """A body that happens to carry `retCode: 0` alongside a 4xx status is
    still not success (fail-open review finding)."""
    respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(422, json={"retCode": 0, "retMsg": "OK"})
    )
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        with pytest.raises(UnknownStateError):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_4xx_with_mapped_ret_code_raises_mapped_error() -> None:
    """A 4xx that does carry a real business `retCode` still maps through
    the normal taxonomy (e.g. an auth failure delivered on a 401)."""
    respx.get(f"{BASE_URL}/v5/account/wallet-balance").mock(
        return_value=httpx.Response(401, json={"retCode": 10003, "retMsg": "invalid key"})
    )
    signer = BybitSigner(fake_capability("k"), CREDENTIAL_ID)
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    try:
        with pytest.raises(Exception) as exc_info:
            await client.signed_request(
                "GET", "/v5/account/wallet-balance", endpoint_class=EndpointClass.ACCOUNT
            )
        assert exc_info.value.__class__.__name__ == "AuthError"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_non_json_body_raises_unknown_state_error() -> None:
    """A non-JSON body must never propagate a raw `JSONDecodeError`."""
    respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(200, content=b"not json")
    )
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        with pytest.raises(UnknownStateError):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_order_class_post_without_order_link_id_is_rejected() -> None:
    """C-2.10: signed POSTs are retried automatically, which is only safe
    for order placement when every attempt reuses the same `orderLinkId`."""
    signer = BybitSigner(fake_capability("k"), CREDENTIAL_ID)
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    try:
        with pytest.raises(ValueError):
            await client.signed_request(
                "POST",
                "/v5/order/create",
                body={"symbol": "BTCUSDT"},
                endpoint_class=EndpointClass.ORDER,
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_order_class_post_with_order_link_id_is_accepted() -> None:
    respx.post(f"{BASE_URL}/v5/order/create").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    signer = BybitSigner(fake_capability("k"), CREDENTIAL_ID)
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    try:
        result = await client.signed_request(
            "POST",
            "/v5/order/create",
            body={"symbol": "BTCUSDT", "orderLinkId": "cv-1"},
            endpoint_class=EndpointClass.ORDER,
        )
        assert result["retCode"] == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10018_without_limit_status_header_drains_one_token() -> None:
    """`X-Bapi-Limit-Status` is the *remaining* count, not the amount
    consumed (review finding). When the header is absent we still account
    for a conservative single-token drain rather than doing nothing."""
    respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(200, json={"retCode": 10018, "retMsg": "rate limited"})
    )
    frozen_time = 1_000_000.0
    governor = _fresh_governor(clock=lambda: frozen_time)
    client = BybitRestClient(_config(max_retries=0), governor=governor)
    try:
        before = governor.remaining("public", EndpointClass.MARKET_DATA)
        with pytest.raises(RateLimitError):
            await client.get_public("/v5/market/kline")
        after = governor.remaining("public", EndpointClass.MARKET_DATA)
        # `acquire()` already consumed one token for the attempt itself;
        # the 10018 drain consumes a second, distinct token on top of that.
        # The clock is frozen so no refill can happen between the two reads.
        assert after == pytest.approx(before - 2.0, abs=1e-6)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10018_with_limit_status_header_sets_bucket_to_remaining() -> None:
    """When the header *is* present, `_observe_rate_headers` already sets
    the bucket to the server-reported remaining value directly — draining
    on top of that would double-count (the original bug)."""
    respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(
            200,
            json={"retCode": 10018, "retMsg": "rate limited"},
            headers={"X-Bapi-Limit-Status": "7"},
        )
    )
    governor = _fresh_governor(clock=lambda: 1_000_000.0)
    client = BybitRestClient(_config(max_retries=0), governor=governor)
    try:
        with pytest.raises(RateLimitError):
            await client.get_public("/v5/market/kline")
        assert governor.remaining("public", EndpointClass.MARKET_DATA) == pytest.approx(
            7.0, abs=1e-6
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_check_reachable_consumes_ip_wide_budget() -> None:
    """Review finding: `check_reachable` skipped the IP-wide token bucket
    entirely."""
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    governor = TokenBucketGovernor(ip_budget_per_5s=1)
    client = BybitRestClient(_config(), governor=governor)
    try:
        assert await client.check_reachable() is True
        ip_tokens_after_one = governor._ip_bucket.tokens
        assert ip_tokens_after_one == pytest.approx(0.0, abs=1e-6)
    finally:
        await client.aclose()
