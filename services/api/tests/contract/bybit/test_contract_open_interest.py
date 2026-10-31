"""E24-T01 (#665): the Bybit open-interest page parser and fetcher, over the corpus only
(the docs transcription and the two generated cursor pages)."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import httpx
import pytest

from candleviewer.domain.open_interest import OiFetchFailed, OiRowRejected
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.open_interest import BybitOpenInterestFetcher, parse_oi_page
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from tests._corpus import http_status, rest

NOW_MS = 1_800_000_000_000
PAGES = [
    rest("rest/open_interest_BTCUSDT_5min_page0.json"),
    rest("rest/open_interest_BTCUSDT_5min_page1.json"),
]
DOCS = rest("rest/docs-open-interest.json")


def _page(*rows: object, **result: Any) -> dict[str, Any]:
    body = {"symbol": "BTCUSDT", "category": "linear", "list": list(rows), "nextPageCursor": ""}
    return {"retCode": 0, "result": {**body, **result}}


def _row(ts: int = 1_700_000_000_000, **kw: Any) -> dict[str, Any]:
    return {"openInterest": "100.5", "singleOpenInterest": "50.25", "timestamp": str(ts), **kw}


def test_oi_parse_corpus_pages_are_rest_points_without_usd_value() -> None:
    first = parse_oi_page(PAGES[0], symbol="BTCUSDT", interval="5min", now_ms=NOW_MS)
    last = parse_oi_page(PAGES[1], symbol="BTCUSDT", interval="5min", now_ms=NOW_MS)
    assert (len(first), len(last)) == (200, 60)
    assert first.next_cursor is not None and last.next_cursor is None
    assert not first.rejected_reasons and not last.rejected_reasons
    points = [*first, *last]
    assert all(p.source == "rest" and p.interval == "5min" for p in points)
    assert all(p.open_interest_value is None for p in points)
    assert {a.ts_us - b.ts_us for a, b in pairwise(points)} == {300_000_000}


def test_oi_parse_docs_rows_fit_the_row_model_and_the_inverse_envelope_is_refused() -> None:
    linear = {**DOCS, "result": {**DOCS["result"], "symbol": "BTCUSDT", "category": "linear"}}
    page = parse_oi_page(linear, symbol="BTCUSDT", interval="1d", now_ms=NOW_MS)
    assert len(page) == len(DOCS["result"]["list"]) and not page.rejected_reasons
    with pytest.raises(OiRowRejected):
        parse_oi_page(DOCS, symbol="BTCUSDT", interval="1d", now_ms=NOW_MS)


@pytest.mark.parametrize(
    "payload",
    [{}, {"result": {}}, {"result": {"list": "x"}}, _page(symbol="ETHUSDT"),
     _page(category="inverse"), _page(nextPageCursor=7), _page(nextPageCursor="c" * 257)],
)  # fmt: skip
def test_oi_parse_envelope_fault_raises(payload: dict[str, Any]) -> None:
    with pytest.raises(OiRowRejected):
        parse_oi_page(payload, symbol="BTCUSDT", interval="5min", now_ms=NOW_MS)


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ("x", "schema"),
        (_row(extra="1"), "schema"),
        (_row(openInterest=1), "schema"),
        (_row(openInterest="abc"), "unparseable"),
        (_row(timestamp="x"), "unparseable"),
        (_row(openInterest="-1"), "value_implausible"),
        (_row(openInterest="NaN"), "value_implausible"),
        (_row(ts=0), "time_range"),
        (_row(ts=NOW_MS + 600_000), "time_range"),
    ],
)
def test_oi_parse_bad_row_is_skipped_with_reason(row: object, reason: str) -> None:
    page = parse_oi_page(_page(row), symbol="BTCUSDT", interval="5min", now_ms=NOW_MS)
    assert list(page) == [] and page.rejected_reasons == [reason]


def test_oi_parse_keeps_newest_first_rows_and_flags_non_monotonic() -> None:
    payload = _page(_row(3000), _row(2000), _row(2500), _row(1000))
    page = parse_oi_page(payload, symbol="BTCUSDT", interval="5min", now_ms=NOW_MS)
    assert [p.ts_us for p in page] == [3_000_000, 2_000_000, 1_000_000]
    assert page.rejected_reasons == ["non_monotonic"]


def _client(handler: Any) -> BybitRestClient:
    cfg = RestClientConfig(base_url="https://api.bybit.com", max_retries=0)
    return BybitRestClient(
        cfg, governor=TokenBucketGovernor(), transport=httpx.MockTransport(handler)
    )


async def test_oi_fetcher_pages_with_the_venue_cursor_over_the_260_row_fixture() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=PAGES[1 if "cursor" in req.url.params else 0])

    async with _client(handler) as client:
        fetch, cursor, rows = BybitOpenInterestFetcher(client), None, 0
        for _ in range(5):
            page = await fetch("BTCUSDT", "5min", 1_000_000, 2_000_000_000_000_000, cursor)
            rows, cursor = rows + len(page), page.next_cursor
            if cursor is None:
                break
    assert rows == 260 and len(seen) == 2
    q = dict(seen[0].url.params)
    assert (q["category"], q["intervalTime"], q["limit"], q["startTime"]) == (
        "linear", "5min", "200", "1000",
    )  # fmt: skip
    assert seen[1].url.params["cursor"] == PAGES[0]["result"]["nextPageCursor"]
    assert seen[0].url.path == "/v5/market/open-interest"
    assert "X-BAPI-API-KEY" not in seen[0].headers


@pytest.mark.parametrize(
    ("fixture", "status", "ret_code"),
    [("rest/error_10018.json", 200, 10018), ("rest/error_503.json", 503, None)],
)
async def test_oi_fetcher_maps_10018_and_5xx_to_retryable_fetch_failure(
    fixture: str, status: int, ret_code: int | None
) -> None:
    body = rest(fixture)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(http_status(fixture), json=body)

    async with _client(handler) as client:
        with pytest.raises(OiFetchFailed) as info:
            await BybitOpenInterestFetcher(client)("BTCUSDT", "5min", 0, 1_000_000, None)
    assert info.value.retryable and (info.value.http_status, info.value.ret_code) == (
        status, ret_code,
    )  # fmt: skip


@pytest.mark.parametrize(("symbol", "interval"), [("BTCUSDT\n", "5min"), ("BTCUSDT", "1s")])
async def test_oi_fetcher_refuses_bad_symbol_or_interval_before_any_request(
    symbol: str, interval: str
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=PAGES[1])

    async with _client(handler) as client:
        with pytest.raises(OiRowRejected):
            await BybitOpenInterestFetcher(client)(symbol, interval, 0, 1_000_000, None)
    assert seen == []
