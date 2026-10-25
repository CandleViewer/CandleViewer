# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The corpus venue answers only in the corpus's shapes (C-13.5; #843 A4 brief item 3)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from spike.oms_demo_path.offline import Corpus, CorpusVenue, default_corpus, patched
from spike.oms_demo_path.safety import Refused

CORPUS = Corpus(default_corpus())


def test_patched_refuses_a_key_the_corpus_shape_lacks() -> None:
    row = CORPUS.push("order")["data"][0]
    assert patched(row, orderStatus="New")["orderStatus"] == "New"
    with pytest.raises(KeyError, match="not in the corpus shape"):
        patched(row, invented="x")


async def test_every_answer_keeps_its_corpus_key_set() -> None:
    venue = CorpusVenue(CORPUS)
    sock = await venue.connect("wss://stream-demo.bybit.com/v5/private")
    body = {
        "category": "linear",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "orderType": "Limit",
        "qty": "0.002",
        "price": str(venue.bid),  # joins the touch: one step fills
        "timeInForce": "GTC",
        "orderLinkId": "cvd-0aaaaaaaaaaaaaaaaaaaaa-ab12-00en",
        "reduceOnly": False,
        "closeOnTrigger": False,
        "positionIdx": 0,
        "stopLoss": "60000",
        "slTriggerBy": "MarkPrice",
        "tpslMode": "Full",
    }
    request = httpx.Request("POST", "https://api-demo.bybit.com/v5/order/create", json=body)
    reply = json.loads((await venue.handle(request)).content)
    assert set(reply) == set(CORPUS.rest("trading-create-reply"))
    assert set(reply["result"]) == set(CORPUS.rest("trading-create-reply")["result"])
    frames = [json.loads(sock.inbox.get_nowait()) for _ in range(sock.inbox.qsize())]
    shapes = {
        "order": CORPUS.push("order"),
        "execution": CORPUS.push("execution"),
        "execution.fast": CORPUS.push("execution-fast"),
        "position": CORPUS.push("position"),
    }
    assert {f["topic"] for f in frames} == set(shapes)
    for frame in frames:
        shape = shapes[frame["topic"]]
        assert set(frame) == set(shape)
        expected = set(shape["data"][0]) | (
            {"category"} if frame["topic"] == "execution" else set()
        )
        assert set(frame["data"][0]) == expected
    assert venue.size == Decimal("0.001") and venue.stop == Decimal("60000")


async def test_the_venue_serves_the_demo_host_only_and_known_routes() -> None:
    venue = CorpusVenue(CORPUS)
    with pytest.raises(Refused, match="demo host"):
        await venue.handle(httpx.Request("GET", "https://api.bybit.com/v5/order/realtime"))
    with pytest.raises(Refused, match="no route"):
        await venue.handle(httpx.Request("GET", "https://api-demo.bybit.com/v5/asset/coin"))
    with pytest.raises(Refused, match="no offline public read"):
        await venue.get_public("/v5/market/tickers")


async def test_an_unknown_order_answers_the_transcribed_110001() -> None:
    venue = CorpusVenue(CORPUS)
    for path in ("/v5/order/amend", "/v5/order/cancel"):
        request = httpx.Request(
            "POST",
            f"https://api-demo.bybit.com{path}",
            json={"orderId": "nope", "symbol": "BTCUSDT"},
        )
        reply = json.loads((await venue.handle(request)).content)
        assert reply == CORPUS.rest("trading-error-110001")


async def test_a_refused_auth_and_a_dropped_socket() -> None:
    venue = CorpusVenue(CORPUS, refuse_auth=1)
    sock = await venue.connect("wss://stream-demo.bybit.com/v5/private")
    await sock.send(json.dumps({"op": "auth", "args": ["k", 1, "s"]}))
    assert json.loads(await sock.recv(1 << 20))["success"] is False
    await sock.send(json.dumps({"op": "unsubscribe"}))  # not answered
    await sock.close()
    with pytest.raises(ConnectionResetError):
        await sock.recv(1 << 20)
    with pytest.raises(ConnectionError):
        await sock.send(json.dumps({"op": "ping"}))


def test_the_default_corpus_is_the_recorded_one() -> None:
    root = default_corpus()
    assert root.name == "2026-10-05" and (root / "manifest.json").is_file()
    assert Path(root, "rest", "trading-create-reply.json").is_file()
