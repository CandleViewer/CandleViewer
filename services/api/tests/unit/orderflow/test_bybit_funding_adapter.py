from __future__ import annotations

from typing import Any

import httpx
import pytest

from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.funding import (
    BybitFundingFetcher,
    FundingRowRejected,
    fetch_funding_page,
    parse_funding_page,
)
from candleviewer.exchange.bybit.rest import BybitRestClient
from tests._corpus import rest


def _page(**row: Any) -> dict[str, Any]:
    base = {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": "1700006400000"}
    return {"retCode": 0, "result": {"list": [{**base, **row}]}}


def test_parse_recorded_8h_and_4h_fixtures() -> None:
    btc = parse_funding_page(rest("rest/funding_history_BTCUSDT_8h.json"), symbol="BTCUSDT")
    eth = parse_funding_page(rest("rest/funding_history_ETHUSDT_4h.json"), symbol="ETHUSDT")
    assert len(btc) == len(eth) == 4
    assert btc[0].ts_us - btc[1].ts_us == 8 * 3_600 * 1_000_000
    assert eth[0].ts_us - eth[1].ts_us == 4 * 3_600 * 1_000_000


@pytest.mark.parametrize("payload", [{}, {"result": {}}, {"result": {"list": "x"}}, {"result": []}])
def test_parse_rejects_malformed_envelope(payload: dict[str, Any]) -> None:
    with pytest.raises(FundingRowRejected):
        parse_funding_page(payload, symbol="BTCUSDT")


NOW_MS = 1_800_000_000_000


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"result": {"list": ["x"]}}, "not_object"),
        (_page(symbol="ETHUSDT"), "symbol_mismatch"),
        (_page(fundingRate=1), "type"),
        (_page(fundingRate="abc"), "unparseable"),
        (_page(fundingRate="NaN"), "rate_implausible"),
        (_page(fundingRate="0.031"), "rate_implausible"),
        (_page(fundingRateTimestamp="0"), "time_nonpositive"),
        (_page(fundingRateTimestamp="x"), "unparseable"),
        (_page(fundingRateTimestamp=str(NOW_MS + 600_000)), "time_future"),
    ],
)
def test_parse_skips_bad_row_and_records_reason(payload: dict[str, Any], reason: str) -> None:
    page = parse_funding_page(payload, symbol="BTCUSDT", now_ms=NOW_MS)
    assert list(page) == [] and page.rejected_reasons == [reason]


def test_parse_keeps_good_rows_and_flags_non_monotonic() -> None:
    def row(ts: int) -> dict[str, str]:
        return {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": str(ts)}

    payload = {"result": {"list": [row(3000), row(2000), row(2500), row(2000), row(1000)]}}
    page = parse_funding_page(payload, symbol="BTCUSDT", now_ms=NOW_MS)
    assert [s.ts_us for s in page] == [3_000_000, 2_000_000, 1_000_000]
    assert page.rejected_reasons == ["non_monotonic", "non_monotonic"]


def test_rate_at_ceiling_is_accepted() -> None:
    page = parse_funding_page(_page(fundingRate="-0.03"), symbol="BTCUSDT", now_ms=NOW_MS)
    assert len(page) == 1


async def test_fetch_is_public_market_data_and_bounds_params() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=rest("rest/funding_history_BTCUSDT_8h.json"))

    cfg = RestClientConfig(base_url="https://api-demo.bybit.com")
    async with BybitRestClient(cfg, transport=httpx.MockTransport(handler)) as client:
        rows = await BybitFundingFetcher(client)("BTCUSDT", 1_000_000, 2_000_000, 200)
        assert len(rows) == 4
        with pytest.raises(ValueError):
            await fetch_funding_page(client, "BTCUSDT", start_us=0, end_us=1, limit=201)
        with pytest.raises(FundingRowRejected):
            await fetch_funding_page(client, "btc/usdt", start_us=0, end_us=1)
    q = dict(seen[0].url.params)
    assert q["limit"] == "200" and q["category"] == "linear"
    assert seen[0].url.path == "/v5/market/funding/history"
    assert "X-BAPI-API-KEY" not in seen[0].headers


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
async def test_fetch_refuses_a_symbol_ending_in_a_newline_before_any_request(tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` let such a symbol through."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=rest("rest/funding_history_BTCUSDT_8h.json"))

    cfg = RestClientConfig(base_url="https://api-demo.bybit.com")
    async with BybitRestClient(cfg, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FundingRowRejected, match="invalid symbol"):
            await fetch_funding_page(client, "BTCUSDT" + tail, start_us=0, end_us=1)
        assert seen == []
        assert len(await fetch_funding_page(client, "BTCUSDT", start_us=0, end_us=1)) == 4
    assert [dict(r.url.params)["symbol"] for r in seen] == ["BTCUSDT"]
