"""#1955: the public subscribe-ack shape the ack tracker relies on, from the corpus file
`ws/public-subscribe-ack-derived.jsonl`.

The file is DERIVED, not a capture (its manifest entry says `source: derived`): no public
subscribe ack has been recorded, so it is `ws/private-subscribe-ok.jsonl` plus the documented
`req_id` echo, and its refused `ret_msg` value is not recorded anywhere (C-13.5 deviation, ruled
on #1955). A recorder-lane capture replaces it; this pack test then pins the recorded shape.
"""

from __future__ import annotations

import asyncio
import json
import random

from candleviewer.exchange.bybit.public_ws import topic_kind
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.watchdog import StalenessWatchdog
from tests import _corpus as corpus

FIXTURE = "ws/public-subscribe-ack-derived.jsonl"


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _Sock:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self, max_bytes: int) -> str:
        raise ConnectionError("eof")

    async def close(self) -> None:
        return None


def test_derived_acks_carry_the_fields_the_tracker_reads() -> None:
    accepted, refused = (json.loads(f) for f in corpus.frames(FIXTURE))
    for ack in (accepted, refused):
        assert ack["op"] == "subscribe" and isinstance(ack["req_id"], str)
        assert isinstance(ack["success"], bool)
    assert accepted["success"] is True and refused["success"] is False
    assert accepted["req_id"] != refused["req_id"]


async def test_derived_acks_settle_the_pending_subscribes_by_req_id() -> None:
    accepted, refused = corpus.frames(FIXTURE)
    clk, sock = _Clock(), _Sock()
    wd = StalenessWatchdog(clk, lambda _e: None, kind_of=topic_kind)
    m = ConnectionManager(
        lambda: asyncio.sleep(0, result=sock),
        SubscriptionPlanner(),
        wd,
        ReconnectPolicy(rng=random.Random(1)),  # noqa: S311  (deterministic jitter)
        ConnectionRateGuard(clk),
        lambda _f: None,
        clock=clk,
    )
    m._sock = sock
    await m._send_tracked(sock, "subscribe", ["publicTrade.ETHUSDT"])
    await m._send_tracked(sock, "subscribe", ["publicTrade.BTCUSDT"])
    assert [f["req_id"] for f in sock.sent] == ["cv-1", "cv-2"]  # the derived acks echo these
    m._on_ack(accepted)
    m._on_ack(refused)
    assert m._pending == {}
