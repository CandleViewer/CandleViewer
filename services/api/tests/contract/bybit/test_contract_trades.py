"""E08-Q02 / E08-TC-D01, E08-TC-D03, E08-TC-D05: `publicTrade` -> `TradePrint` -> `TradeEvent`."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.trades import parse_recent_trades, parse_trade_frame
from candleviewer.ingestion.metrics import (
    trade_duplicates_suppressed_total,
    trade_prints_rejected_total,
)
from tests._corpus import frames, rest
from tests.contract.bybit._support import TradeHarness, counter_value

BTC = "ws/publicTrade_BTCUSDT.jsonl"
CLEAN = "ws/clean_publicTrade_BTCUSDT.jsonl"
RECONNECT = "ws/reconnect_publicTrade_ETHUSDT.jsonl"
ETH = "ws/clean_publicTrade_ETHUSDT.jsonl"
SOL = "ws/clean_publicTrade_SOLUSDT.jsonl"
RECENT = "rest/recent_trade_BTCUSDT.json"


def test_print_fields_are_decimal_side_mapped_and_ms_become_us() -> None:
    raw = frames(BTC)[0]
    wire = json.loads(raw)["data"]
    prints = parse_trade_frame(raw)
    assert prints is not None and len(prints) == len(wire)
    for p, w in zip(prints, wire, strict=True):
        assert isinstance(p, TradePrint)
        assert isinstance(p.price, Decimal) and isinstance(p.qty, Decimal)
        assert p.price == Decimal(w["p"]) and p.qty == Decimal(w["v"])
        assert p.side == w["S"].lower()
        assert p.ts_event_us == w["T"] * 1000
        assert p.trade_id == w["i"]
        assert p.is_block_trade is False


def test_block_trade_flag_is_carried() -> None:
    flags = [p.is_block_trade for raw in frames(BTC) for p in parse_trade_frame(raw) or []]
    assert flags.count(True) == 1 and len(flags) == 4


@pytest.mark.parametrize("rel", [CLEAN, ETH, SOL])
def test_clean_windows_parse_without_rejection_and_keep_wire_order(rel: str) -> None:
    ids = [p.trade_id for raw in frames(rel) for p in parse_trade_frame(raw) or []]
    assert ids and len(ids) == len(set(ids))
    wire_ids = [d["i"] for raw in frames(rel) for d in json.loads(raw)["data"]]
    assert ids == wire_ids


async def test_trade_event_published_with_internal_vocabulary() -> None:
    h = TradeHarness()
    await h.stream.handle_frame(frames(BTC)[0])
    events = h.drain()
    assert events and all(isinstance(e, TradeEvent) for e in events)
    e = events[0]
    assert isinstance(e.price, Decimal) and e.price_ticks == int(e.price / Decimal("0.1"))
    assert e.notional == e.price * e.qty and e.source == "live"
    assert [x.seq for x in events] == list(range(1, len(events) + 1))


async def test_reconnect_replay_duplicates_are_published_once() -> None:
    """E08-TC-D03: the replayed prints after the socket drop appear exactly once."""
    h = TradeHarness("ETHUSDT")
    wire_ids = [d["i"] for raw in frames(RECONNECT) for d in json.loads(raw)["data"]]
    dups = len(wire_ids) - len(set(wire_ids))
    assert dups == 2
    before = counter_value(trade_duplicates_suppressed_total, symbol="ETHUSDT")
    for raw in frames(RECONNECT):
        await h.stream.handle_frame(raw)
    ids = [e.trade_id for e in h.drain()]
    assert len(ids) == len(set(ids)) == len(set(wire_ids))
    assert counter_value(trade_duplicates_suppressed_total, symbol="ETHUSDT") - before == dups


@given(repeat=st.integers(min_value=2, max_value=4))
@settings(max_examples=6, deadline=None)
async def test_replaying_a_fixture_n_times_is_idempotent(repeat: int) -> None:
    once, many = TradeHarness(), TradeHarness()
    for raw in frames(BTC):
        await once.stream.handle_frame(raw)
    for _ in range(repeat):
        for raw in frames(BTC):
            await many.stream.handle_frame(raw)

    def keyed(evs: list[Any]) -> list[tuple[str, Decimal, Decimal, str]]:
        return [(e.trade_id, e.price, e.qty, e.side) for e in evs]

    assert keyed(many.drain()) == keyed(once.drain())


def test_recent_trade_rest_page_maps_to_the_same_print_shape() -> None:
    """O-TRD oracle: the REST capture normalises to prints with identical semantics."""
    prints = parse_recent_trades("BTCUSDT", rest(RECENT))
    assert prints and all(isinstance(p.price, Decimal) for p in prints)
    wire = rest(RECENT)["result"]["list"]
    assert [p.ts_event_us for p in prints] == [int(w["time"]) * 1000 for w in wire]
    assert [p.side for p in prints] == [w["side"].lower() for w in wire]


def _set(key: str, value: object) -> Callable[[dict[str, Any]], None]:
    def apply(d: dict[str, Any]) -> None:
        d[key] = value

    return apply


@pytest.mark.parametrize(
    "mutate",
    [
        _set("p", "NaN"),
        _set("p", "-1"),
        _set("v", "0"),
        _set("S", "Hold"),
        _set("i", ""),
        _set("T", 0),
        _set("s", "ETHUSDT"),
    ],
)
async def test_malformed_print_is_rejected_counted_and_stream_continues(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """E08-TC-D05 (+ hostile-input rows of the ticket's security notes)."""
    msg = json.loads(frames(BTC)[0])
    mutate(msg["data"][0])
    bad = json.dumps(msg, separators=(",", ":"))
    with pytest.raises(ValueError):
        parse_trade_frame(bad)
    h = TradeHarness()
    before = counter_value(trade_prints_rejected_total)
    await h.stream.handle_frame(bad)
    await h.stream.handle_frame(frames(BTC)[2])
    assert counter_value(trade_prints_rejected_total) - before == 1
    assert len(h.drain()) == 1


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_a_trade_symbol_ending_in_a_newline_is_rejected(tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` took `publicTrade.BTCUSDT\\n`.
    The frame is a recorded batch whose topic and every record carry that symbol, so the symbol
    pattern is the check left to refuse it."""
    msg = json.loads(frames(BTC)[0])
    legal = parse_trade_frame(json.dumps(msg))
    assert legal is not None and {p.symbol for p in legal} == {"BTCUSDT"}
    msg["topic"] += tail
    for rec in msg["data"]:
        rec["s"] += tail
    with pytest.raises(ValueError, match="invalid symbol"):
        parse_trade_frame(json.dumps(msg))


@pytest.mark.parametrize(
    "junk", ["", "not json", "[]", '{"topic":"publicTrade.BTCUSDT"', '{"op":"pong"}']
)
def test_truncated_or_foreign_frames_never_crash_the_parser(junk: str) -> None:
    assert parse_trade_frame(junk) is None


def test_oversized_batch_is_rejected() -> None:
    one = json.loads(frames(BTC)[0])["data"][0]
    huge = json.dumps({"topic": "publicTrade.BTCUSDT", "ts": 1, "data": [one] * 2001})
    with pytest.raises(ValueError, match="batch cap"):
        parse_trade_frame(huge)
