"""E24-T03 (#667): the Bybit `allLiquidation` push parser, over the corpus only: the docs
transcription (`ws/docs-all-liquidation.jsonl`) and the generated cascade
(`ws/allLiquidation_BTCUSDT_burst.jsonl`)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.frame_guard import FrameRejectedError
from candleviewer.exchange.bybit.liquidations import (
    MAX_PRINTS_PER_PUSH,
    liquidation_topic,
    parse_liquidation_frame,
)
from candleviewer.exchange.bybit.public_ws import frame_route, topic_kind
from tests._corpus import corpus_path

DOCS = corpus_path("ws/docs-all-liquidation.jsonl").read_text(encoding="utf-8").splitlines()
BURST = corpus_path("ws/allLiquidation_BTCUSDT_burst.jsonl").read_text("utf-8").splitlines()
NOW_US = 1_800_000_000_000_000


def _push(**over: Any) -> dict[str, Any]:
    msg: dict[str, Any] = json.loads(BURST[1])
    msg.update(over)
    return msg


def test_parse_docs_example_maps_every_field_and_computes_notional() -> None:
    (event,) = parse_liquidation_frame(DOCS[0], NOW_US) or []
    assert event.symbol == "ROSEUSDT"
    assert event.ts_event == 1739502302929 * 1000 and event.ts_ingest == NOW_US
    assert (event.price, event.qty) == (Decimal("0.04499"), Decimal("20000"))
    assert event.notional == Decimal("0.04499") * Decimal("20000")
    assert event.liquidated_side == "long"  # `Sell` closes a long (24 §2.5)
    assert (event.batch_index, event.ts_estimated, event.source) == (0, False, "live")


def test_parse_push_keeps_every_print_apart_by_batch_index() -> None:
    events = parse_liquidation_frame(BURST[1], NOW_US) or []
    assert [e.batch_index for e in events] == [0, 1, 2]
    twin_a, twin_b = events[0], events[1]
    assert (twin_a.ts_event, twin_a.price) == (twin_b.ts_event, twin_b.price)
    assert twin_a.qty == twin_b.qty
    wire = [row["S"] for row in json.loads(BURST[1])["data"]]
    closed = {"Buy": "short", "Sell": "long"}  # `Buy` closes a short, `Sell` a long (24 §2.5)
    assert [e.liquidated_side for e in events] == [closed[w] for w in wire]


def test_parse_print_without_own_time_takes_the_envelope_and_says_so() -> None:
    msg = _push()
    del msg["data"][0]["T"]
    (first, *_rest) = parse_liquidation_frame(json.dumps(msg), NOW_US) or []
    assert first.ts_event == msg["ts"] * 1000 and first.ts_estimated


@pytest.mark.parametrize("frame", ['{"op":"pong"}', '{"topic":"tickers.BTCUSDT"}', "[1]", "nope"])
def test_parse_non_liquidation_frame_is_none(frame: str) -> None:
    assert parse_liquidation_frame(frame, NOW_US) is None


@pytest.mark.parametrize(
    "msg",
    [
        _push(topic="allLiquidation.btc"),
        _push(type="delta"),
        _push(ts=0),
        _push(extra=1),
        _push(data=[{**_push()["data"][0], "x": 1}]),
        _push(data=[{**_push()["data"][0], "s": "ETHUSDT"}]),
        _push(data=[{**_push()["data"][0], "S": "buy"}]),
        _push(data=[{**_push()["data"][0], "p": "abc"}]),
        _push(data=[{**_push()["data"][0], "p": "-1"}]),
        _push(data=[{**_push()["data"][0], "v": "0"}]),
        _push(data=[{**_push()["data"][0], "v": 1}]),
        _push(data=[{**_push()["data"][0], "T": 0}]),
        _push(data=[{**_push()["data"][0], "T": _push()["ts"] + 10_000_000}]),
        _push(data=[_push()["data"][0]] * (MAX_PRINTS_PER_PUSH + 1)),
    ],
)
def test_parse_malformed_push_is_refused_whole(msg: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse_liquidation_frame(json.dumps(msg), NOW_US)


def test_parse_too_deep_frame_is_a_depth_rejection() -> None:
    deep = '{"topic":"allLiquidation.BTCUSDT","data":' + "[" * 5000 + "]" * 5000 + "}"
    with pytest.raises((FrameRejectedError, ValueError)):
        parse_liquidation_frame(deep, NOW_US)


def test_topic_routes_as_its_own_kind() -> None:
    assert liquidation_topic("BTCUSDT") == "allLiquidation.BTCUSDT"
    assert topic_kind("allLiquidation.BTCUSDT") == "liquidation"
    assert frame_route(BURST[0]) == ("allLiquidation.BTCUSDT", "liquidation", "BTCUSDT")
