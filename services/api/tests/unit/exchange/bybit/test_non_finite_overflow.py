"""#5040's siblings: an `Infinity` in a REST body or an archive row is a malformed value, so it is
refused with the module's own domain error, never an `OverflowError` or a decimal `Overflow`.

`json.loads` accepts `Infinity`, and `int()` of it overflows; a finite but huge `Decimal` overflows
the multiply that scales a timestamp. Each case below fails without its fix."""

from __future__ import annotations

import gzip
import math
from typing import Any

import httpx
import pytest

from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.bybit.archive import ArchiveParseFailed, BybitTradeArchive
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.instruments import InstrumentParseError, parse_instrument
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient, paginate_klines
from tests._corpus import rest
from tests.unit.exchange.bybit.test_archive import T0, _file, _gz, _row


def _btc() -> dict[str, Any]:
    rows = rest("rest/instruments_before.json", capture_date="2026-10-05")["result"]["list"]
    return dict(next(r for r in rows if r["symbol"] == "BTCUSDT"))


@pytest.mark.parametrize("field", ["priceScale", "launchTime"])
@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_an_instrument_with_a_non_finite_integer_field_is_a_parse_error(
    field: str, value: float
) -> None:
    with pytest.raises(InstrumentParseError):
        parse_instrument(_btc() | {field: value}, fetched_at_us=0)


async def test_a_reply_whose_return_code_is_infinite_has_no_usable_return_code() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = b'{"retCode": Infinity, "result": {}}'  # httpx's `json=` refuses to encode it
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    cfg = RestClientConfig(base_url="https://api-demo.bybit.com")  # a mock transport: no network
    async with BybitRestClient(
        cfg, governor=TokenBucketGovernor(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(UnknownStateError, match="no usable retCode"):
            await client.get_public("/v5/market/funding/history", params={"category": "linear"})


async def test_a_kline_page_with_an_infinite_start_is_a_value_error() -> None:
    async def fetch(start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        return [{"start": math.inf}]

    with pytest.raises(ValueError, match="non-integer start"):
        await paginate_klines(fetch, start_ms=0, end_ms=1_000)


def test_an_archive_row_with_a_huge_timestamp_fails_the_file() -> None:
    line = _row(T0 + 1)
    raw = _gz(line.replace(line.split(",")[0], "1e999999", 1))
    assert isinstance(raw, bytes) and gzip.decompress(raw)
    with pytest.raises(ArchiveParseFailed):
        list(BybitTradeArchive().parse(_file(), raw, 100))
