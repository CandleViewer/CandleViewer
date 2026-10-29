"""E08-Q02 P3 leakage test + parse-time smoke guard.

Principle P3 (`20-architecture.md` section 0): Bybit vocabulary never leaves `exchange/bybit/`.
Every payload the adapter's normalised events and the public REST serialisers emit is scanned
(recursively, keys and string values) for Bybit-native field names and wire enums.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Iterable
from typing import Any

import pytest

from candleviewer.api.orderbook import serialize_orderbook
from candleviewer.api.ticker import serialize_ticker
from candleviewer.api.trades import serialize_trade
from candleviewer.exchange.bybit.orderbook import parse_book_frame
from candleviewer.exchange.bybit.ticker import parse_ticker_frame
from candleviewer.exchange.bybit.trades import parse_trade_frame
from candleviewer.ingestion.ticker_stream import TickerMerger
from candleviewer.orderflow.bigtrade_tape import TapeItem, TapePrint
from tests._corpus import frames
from tests.contract.bybit._support import TradeHarness, tick_of

#: Wire-only keys (trade/ticker/book/kline/instrument frames). `u`/`seq` are deliberately absent:
#: they are also published internal/OpenAPI names (`BookSnapshot.update_id` is `u` on
#: `GET /market/orderbook`; `TradeEvent.seq`), so they cannot discriminate a leak.
BYBIT_KEYS = frozenset(
    {
        "T", "S", "v", "p", "BT", "L", "i", "s", "b", "a", "cts",
        "lastPrice", "markPrice", "indexPrice", "bid1Price", "bid1Size", "ask1Price",
        "ask1Size", "price24hPcnt", "volume24h", "turnover24h", "openInterest",
        "openInterestValue", "fundingRate", "nextFundingTime", "execId", "isBlockTrade",
        "retCode", "retMsg", "retExtInfo", "tickSize", "qtyStep", "priceFilter",
        "lotSizeFilter", "leverageFilter", "orderLinkId", "confirm",
    }
)  # fmt: skip
#: Wire enum spellings that must have been normalised to lower-case internal values.
BYBIT_VALUES = frozenset(
    {"Buy", "Sell", "PlusTick", "MinusTick", "ZeroPlusTick", "LinearPerpetual"}
)


def walk(node: Any) -> Iterable[tuple[str, str]]:
    """Yield ('key'|'value', text) for every key and string value in a JSON-like tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield "key", str(k)
            yield from walk(v)
    elif isinstance(node, list | tuple):
        for v in node:
            yield from walk(v)
    elif isinstance(node, str):
        yield "value", node


def leaks(payload: Any) -> list[str]:
    return [
        f"{kind} {text!r}"
        for kind, text in walk(payload)
        if (kind == "key" and text in BYBIT_KEYS) or (kind == "value" and text in BYBIT_VALUES)
    ]


def assert_clean(payload: Any) -> None:
    found = leaks(payload)
    assert not found, f"Bybit-native vocabulary leaked: {found}"


async def _trade_events() -> list[Any]:
    h = TradeHarness()
    for raw in frames("ws/publicTrade_BTCUSDT.jsonl"):
        await h.stream.handle_frame(raw)
    return h.drain()


async def test_trade_events_and_rest_rows_use_internal_vocabulary_only() -> None:
    events = await _trade_events()
    assert events
    for e in events:
        assert_clean(e.model_dump(mode="json"))
        assert_clean(serialize_trade(TapeItem(TapePrint(e, False, None), e.qty, 1, False)))


def test_book_events_and_rest_view_use_internal_vocabulary_only() -> None:
    snap = parse_book_frame(frames("ws/orderbook_BTCUSDT.jsonl")[0], tick_of)
    delta = parse_book_frame(frames("ws/orderbook_BTCUSDT.jsonl")[1], tick_of)
    assert snap is not None and delta is not None
    assert_clean(snap.model_dump(mode="json"))
    assert_clean(delta.model_dump(mode="json"))
    assert_clean(serialize_orderbook(snap, stale=False))  # type: ignore[arg-type]


def test_merged_ticker_events_and_rest_view_use_internal_vocabulary_only() -> None:
    merger = TickerMerger()
    for raw in frames("ws/tickers_BTCUSDT.jsonl"):
        delta = parse_ticker_frame(raw)
        assert delta is not None
        event = merger.apply(delta, ts_ingest_us=1_700_000_000_500_000)
        assert event is not None
        assert_clean(event.model_dump(mode="json"))
        assert_clean(serialize_ticker(event, stale=False))


def test_a_deliberate_violation_is_detected() -> None:
    """Scratch-branch check from the Gherkin: a payload carrying wire names must fail."""
    assert leaks({"lastPrice": "1"}) == ["key 'lastPrice'"]
    assert leaks({"side": "Buy"}) == ["value 'Buy'"]
    assert leaks({"items": [{"i": "x"}]}) == ["key 'i'"]
    assert leaks({"side": "buy", "price": "1"}) == []
    with pytest.raises(AssertionError, match="leaked"):
        assert_clean({"data": {"BT": False}})


# ---- performance smoke: parse budget (06-performance-and-load-standard section 4, <= 3 ms) --


def _median_ms(parse: Any, raw_frames: list[str], repeat: int = 5) -> float:
    samples = []
    for _ in range(repeat):
        for raw in raw_frames:
            t0 = time.perf_counter()
            parse(raw)
            samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


@pytest.mark.perf
def test_median_parse_time_per_stream_is_inside_the_3ms_budget() -> None:
    reps = {
        "trade": (parse_trade_frame, frames("ws/clean_publicTrade_BTCUSDT.jsonl")[:200]),
        "ticker": (parse_ticker_frame, frames("ws/burst_tickers_BTCUSDT.jsonl")[:200]),
        "book": (
            lambda f: parse_book_frame(f, tick_of),
            frames("ws/orderbook_BTCUSDT.jsonl")[:200],
        ),
    }
    for name, (parse, raw) in reps.items():
        assert _median_ms(parse, raw) <= 3.0, name


def test_frames_are_valid_json_envelopes_for_the_scan() -> None:
    for rel in ("ws/publicTrade_BTCUSDT.jsonl", "ws/tickers_BTCUSDT.jsonl"):
        assert all(isinstance(json.loads(f), dict) for f in frames(rel))
