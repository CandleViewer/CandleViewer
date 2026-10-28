"""E08-T08 (#4707): the venue-wide `GET /v5/market/tickers` read -> a neutral `TickerPage`.

Against the recorded replies (`tests/_tickers.py`: three recorded single-symbol replies, their items
joined in one recorded envelope for the venue-wide shape). A row is read as the stream reads a
frame's `data`: the same field table, bounds and crossed-book check, as a full snapshot at the
reply's `time`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.frame_guard import FrameRejectedError
from candleviewer.exchange.base.ticker_delta import TICKER_FIELDS
from candleviewer.exchange.base.universe import TickerPage
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, parse_ticker_row
from candleviewer.exchange.bybit.tickers import (
    MAX_ROWS,
    PATH,
    make_tickers_fetcher,
    parse_tickers_reply,
)
from tests import _tickers as t
from tests._corpus import rest

SYMBOLS = t.SYMBOLS
#: The recorded replies this pack reads, one per symbol (the feed-rot check needs each path here).
RECORDED = {
    "BTCUSDT": "rest/recorded_tickers_BTCUSDT.json",
    "ETHUSDT": "rest/recorded_tickers_ETHUSDT.json",
    "SOLUSDT": "rest/recorded_tickers_SOLUSDT.json",
}


def _page(rows: list[dict[str, Any]]) -> TickerPage:
    return parse_tickers_reply(t.reply(rows))


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_a_recorded_reply_maps_its_row_as_the_streams_snapshot_at_the_replys_time(
    symbol: str,
) -> None:
    reply = rest(RECORDED[symbol])
    assert reply == t.recorded(symbol)  # the helper serves this same recording
    page = parse_tickers_reply(reply)
    (row,) = reply["result"]["list"]
    frame = {"topic": f"tickers.{symbol}", "type": "snapshot", "ts": reply["time"], "data": row}
    stream = parse_ticker_frame(json.dumps(frame))  # the same recorded row as a frame's `data`
    assert stream is not None
    assert (page.ts_event_us, page.rejected, list(page.tickers)) == (
        reply["time"] * 1000,
        0,
        [symbol],
    )
    delta = page.tickers[symbol]
    assert (delta.is_snapshot, delta.ts_event_us) == (True, page.ts_event_us)
    assert dict(delta.fields) == dict(stream.fields)
    assert set(delta.fields) == set(TICKER_FIELDS)  # the 24 h range included
    high, low = Decimal(row["highPrice24h"]), Decimal(row["lowPrice24h"])
    assert (delta.fields["high_24h"], delta.fields["low_24h"]) == (high, low)


def test_the_recorded_rows_in_one_reply_keep_the_venues_order() -> None:
    page = _page([t.row(s) for s in SYMBOLS])
    assert (list(page.tickers), page.rejected) == (list(SYMBOLS), 0)
    assert all(d.ts_event_us == page.ts_event_us for d in page.tickers.values())


@pytest.mark.parametrize(
    ("wire", "field"), [("highPrice24h", "high_24h"), ("lowPrice24h", "low_24h")]
)
def test_a_zero_24h_high_or_low_is_left_out_and_the_row_stands(wire: str, field: str) -> None:
    """A 24 h high or low of `"0"` is no price: absent, as an empty value is, never a rejection."""
    page = _page([{**t.row("BTCUSDT"), wire: "0"}, t.row("ETHUSDT")])
    assert (list(page.tickers), page.rejected) == (["BTCUSDT", "ETHUSDT"], 0)
    fields = page.tickers["BTCUSDT"].fields
    assert set(fields) == set(TICKER_FIELDS) - {field}
    assert fields["last_price"] == Decimal(t.row("BTCUSDT")["lastPrice"])


@pytest.mark.parametrize(
    "bad",
    [
        {"lastPrice": "abc"},
        {"lastPrice": "-1"},
        {"bid1Price": "90000", "ask1Price": "80000"},  # crossed top of book
        {"symbol": "btcusdt"},
        {"symbol": None},
    ],
    ids=["unparseable", "negative", "crossed", "lowercase", "no-symbol"],
)
def test_a_malformed_row_is_skipped_and_counted_never_the_others(bad: dict[str, Any]) -> None:
    page = _page([t.row("BTCUSDT"), {**t.row("ETHUSDT"), **bad}, t.row("SOLUSDT")])
    assert (list(page.tickers), page.rejected) == (["BTCUSDT", "SOLUSDT"], 1)


@pytest.mark.parametrize("bound", ["length", "scale"])
@pytest.mark.parametrize("wire", ["lastPrice", "fundingRate"], ids=["price", "rate"])
def test_a_row_refuses_a_value_beyond_the_length_or_scale_bound(wire: str, bound: str) -> None:
    """Numeric fields are bounded in length and scale before they are stored, on this read as on
    the stream. The recorded ETHUSDT row with one value widened to the bound reads as recorded;
    one step past it, the row is refused `out_of_bounds`, then skipped and counted while the
    others stand, so nothing of it reaches the snapshot."""
    eth, ts = t.row("ETHUSDT"), t.recorded("ETHUSDT")["time"]
    at = parse_ticker_row({**eth, wire: t.widened(eth[wire], bound, 0)}, ts_ms=ts)
    assert at.fields == parse_ticker_row(eth, ts_ms=ts).fields
    past = {**eth, wire: t.widened(eth[wire], bound, 1)}
    with pytest.raises(FrameRejectedError) as refused:
        parse_ticker_row(past, ts_ms=ts)
    assert refused.value.reason == "out_of_bounds"
    page = _page([t.row("BTCUSDT"), past, t.row("SOLUSDT")])
    assert (list(page.tickers), page.rejected) == (["BTCUSDT", "SOLUSDT"], 1)


def test_a_row_that_is_no_object_or_repeats_a_symbol_is_counted() -> None:
    reply = t.reply([t.row("BTCUSDT"), t.row("BTCUSDT", "1")])
    reply["result"]["list"].insert(1, ["not", "an", "object"])
    page = parse_tickers_reply(reply)
    assert (list(page.tickers), page.rejected) == (["BTCUSDT"], 2)
    first = Decimal(t.row("BTCUSDT")["lastPrice"])
    assert page.tickers["BTCUSDT"].fields["last_price"] == first  # the first row stands


@pytest.mark.parametrize("symbol", ["BTCPERP", "BTCUSDT-26DEC25", "ETH-26DEC25"])
def test_a_linear_contract_outside_usdt_perpetuals_is_left_out_uncounted(symbol: str) -> None:
    page = _page([t.row("BTCUSDT"), t.row(symbol)])
    assert (list(page.tickers), page.rejected) == (["BTCUSDT"], 0)


def _without(payload: dict[str, Any], *path: str) -> dict[str, Any]:
    node = payload
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return payload


@pytest.mark.parametrize(
    "envelope",
    [
        lambda r: _without(r, "result"),
        lambda r: _without(r, "result", "list"),
        lambda r: {**r, "result": {**r["result"], "category": "inverse"}},
        lambda r: {**r, "result": {**r["result"], "list": {}}},
        lambda r: _without(r, "time"),
        lambda r: {**r, "time": True},
        lambda r: {**r, "time": 0},
        lambda r: {**r, "time": 10**15},  # past the plausible window
    ],
    ids=[
        *("no-result", "no-list", "not-linear", "list-not-array"),
        *("no-time", "bool-time", "zero-time", "future-time"),
    ],
)
def test_an_envelope_fault_fails_the_whole_read(envelope: Any) -> None:
    with pytest.raises(ValueError):
        parse_tickers_reply(envelope(t.reply([t.row()])))


def test_a_reply_over_the_row_bound_fails_the_whole_read() -> None:
    with pytest.raises(ValueError):
        parse_tickers_reply(t.reply([t.row()] * (MAX_ROWS + 1)))


class _Client:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any], EndpointClass]] = []

    async def get_public(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.MARKET_DATA,
    ) -> dict[str, Any]:
        self.calls.append((path, dict(params or {}), endpoint_class))
        answer: dict[str, Any] = json.loads(json.dumps(self.payload))  # as the client decodes it
        return answer


async def test_the_read_is_one_public_market_data_get_of_every_linear_ticker() -> None:
    """C-12.7: the `MARKET_DATA` bucket, never the stop/cancel/SL reserve; no symbol filter."""
    client = _Client(t.reply([t.row(s) for s in SYMBOLS]))
    page = await make_tickers_fetcher(client)()
    assert PATH == "/v5/market/tickers"
    assert client.calls == [(PATH, {"category": "linear"}, EndpointClass.MARKET_DATA)]
    assert list(page.tickers) == list(SYMBOLS)
