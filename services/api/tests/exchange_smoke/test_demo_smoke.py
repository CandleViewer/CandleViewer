"""Opt-in demo connectivity smoke suite (E08-T05, 24-internal-schemas §14.2 rule 5).

Run manually only: `CV_EXCHANGE_SMOKE=1 uv run pytest -m exchange_smoke --no-cov`.
An opted-in run fails closed at session setup for now (#3826): see README.md.
No credentials; demo REST host + the public stream demo uses. Every test is
marked `exchange_smoke`, so the default CI lane (`-m "not exchange_smoke"`)
never selects it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.instruments import make_instruments_info_fetcher
from candleviewer.exchange.bybit.orderbook import book_topic
from candleviewer.exchange.bybit.public_ws import public_socket_factory
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.ticker import ticker_topic
from candleviewer.exchange.bybit.trades import trade_topic
from candleviewer.ingestion.clock import ClockGuard, rest_client_fetcher
from tests._corpus import normalize
from tests.exchange_smoke._guard import DEMO_REST_URL

pytestmark = pytest.mark.exchange_smoke
SYMBOL = "BTCUSDT"


def _client() -> BybitRestClient:
    return BybitRestClient(RestClientConfig(base_url=DEMO_REST_URL))


async def test_smoke_instrument_catalogue_fetch() -> None:
    async with _client() as client:
        result = await make_instruments_info_fetcher(client)(lambda: 0)
    assert any(i.symbol == SYMBOL for i in result.instruments)


async def test_smoke_server_time_offset() -> None:
    async with _client() as client:
        offset_us = await ClockGuard(rest_client_fetcher(client), sample_count=3).measure_once()
    assert abs(offset_us) < 5_000_000


async def test_smoke_one_kline_page() -> None:
    async with _client() as client:
        body = await client.get_public(
            "/v5/market/kline",
            params={"category": "linear", "symbol": SYMBOL, "interval": "1", "limit": 10},
        )
    assert body["retCode"] == 0 and len(body["result"]["list"]) == 10


@pytest.mark.parametrize(
    "topic", [trade_topic(SYMBOL), ticker_topic(SYMBOL), book_topic(SYMBOL, 50)]
)
async def test_smoke_public_ws_subscribe_receive_and_clean_shutdown(topic: str) -> None:
    sock = await public_socket_factory("demo", max_frame_bytes=4_000_000)()
    try:
        await sock.send(json.dumps({"op": "subscribe", "args": [topic]}))
        async with asyncio.timeout(30):
            while True:
                frame = await sock.recv(4_000_000)
                if json.loads(frame).get("topic") == topic:
                    break
        assert normalize(frame), f"no domain event parsed from a live {topic} frame"
    finally:
        await sock.close()  # clean shutdown: close must not raise
