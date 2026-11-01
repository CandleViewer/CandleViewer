"""#1955: topic-level subscribe/unsubscribe acks tracked by `req_id` (fake socket + clock).

No recorded PUBLIC-socket ack exists under packages/fixtures/bybit; the shape used is the
recorded private ack (`private-subscribe-ok.jsonl`) plus the documented Bybit v5 `req_id` echo.
"""

from __future__ import annotations

import asyncio
import json
import random

from candleviewer.exchange.bybit.public_ws import topic_kind
from candleviewer.ingestion import connection as conn_mod
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.metrics import ingest_subscribe_rejected_total
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.watchdog import StalenessWatchdog

TOPIC = "orderbook.50.BTCUSDT"
OTHER = "publicTrade.ETHUSDT"


class _Clock:
    t = 0.0

    def __call__(self) -> float:
        return self.t


class _Sock:
    def __init__(self, frames: list[str] | None = None) -> None:
        self.sent: list[dict[str, object]] = []
        self._frames = list(frames or [])

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self, max_bytes: int) -> str:
        if self._frames:
            return self._frames.pop(0)
        raise ConnectionError("eof")

    async def close(self) -> None:
        return None


def _count(reason: str) -> float:
    return float(ingest_subscribe_rejected_total.labels(reason=reason)._value.get())


def _ack(req_id: object, *, success: bool, op: str = "subscribe") -> str:
    return json.dumps(
        {"success": success, "ret_msg": "" if success else "error:handler not found",
         "conn_id": "c-1", "req_id": req_id, "op": op}
    )  # fmt: skip


def _mgr(
    clk: _Clock, sock: _Sock, seen: list[str] | None = None
) -> tuple[ConnectionManager, StalenessWatchdog]:
    wd = StalenessWatchdog(clk, lambda _e: None, kind_of=topic_kind)
    m = ConnectionManager(
        lambda: asyncio.sleep(0, result=sock),
        SubscriptionPlanner(),
        wd,
        ReconnectPolicy(rng=random.Random(1)),  # noqa: S311  (deterministic jitter)
        ConnectionRateGuard(clk),
        (seen.append if seen is not None else lambda _f: None),
        clock=clk,
    )
    m._sock = sock
    return m, wd


async def test_subscribe_frames_carry_distinct_req_ids() -> None:
    sock = _Sock()
    m, _ = _mgr(_Clock(), sock)
    m.set_desired({TOPIC, OTHER})
    await m.subscribe()
    ids = [f["req_id"] for f in sock.sent]
    assert ids and all(isinstance(i, str) and len(i) <= 36 for i in ids)
    assert len(set(ids)) == len(ids)
    assert set(m._pending) == set(ids)


async def test_success_ack_clears_pending_without_metric() -> None:
    sock = _Sock()
    m, _ = _mgr(_Clock(), sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    before = _count("rejected")
    m._on_ack(_ack(sock.sent[0]["req_id"], success=True))
    assert m._pending == {}
    assert _count("rejected") == before


async def test_rejected_subscribe_counts_and_marks_topic_stale() -> None:
    clk, sock = _Clock(), _Sock()
    m, wd = _mgr(clk, sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    clk.t = 0.5  # well inside the book staleness limit
    before = _count("rejected")
    m._on_ack(_ack(sock.sent[0]["req_id"], success=False))
    assert _count("rejected") == before + 1
    assert m._pending == {}
    assert wd.check() == [TOPIC]  # the next watch tick resubscribes it via the stale path
    await m._resubscribe_stale(TOPIC)
    assert [f["op"] for f in sock.sent[-2:]] == ["unsubscribe", "subscribe"]
    assert all("req_id" in f for f in sock.sent[-2:])


async def test_rejected_unsubscribe_counts_but_does_not_mark_stale() -> None:
    clk, sock = _Clock(), _Sock()
    m, wd = _mgr(clk, sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    m.set_desired({OTHER})
    await m.subscribe()  # diff: unsubscribe TOPIC, subscribe OTHER
    unsub = next(f for f in sock.sent if f["op"] == "unsubscribe")
    before = _count("rejected")
    m._on_ack(_ack(unsub["req_id"], success=False, op="unsubscribe"))
    assert _count("rejected") == before + 1
    clk.t = 1.0
    assert wd.check() == []


async def test_unanswered_ack_times_out_once() -> None:
    clk, sock = _Clock(), _Sock()
    m, wd = _mgr(clk, sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    before = _count("timeout")
    clk.t = conn_mod.ACK_TIMEOUT_S - 0.1
    m._expire_acks()
    assert _count("timeout") == before and len(m._pending) == 1
    clk.t = conn_mod.ACK_TIMEOUT_S
    m._expire_acks()
    m._expire_acks()
    assert _count("timeout") == before + 1 and m._pending == {}
    assert wd.check() == [TOPIC]


async def test_pending_map_is_bounded_dropping_oldest() -> None:
    sock = _Sock()
    m, _ = _mgr(_Clock(), sock)
    before = _count("overflow")
    for i in range(conn_mod.MAX_PENDING_ACKS + 3):
        await m._send_tracked(sock, "subscribe", [f"publicTrade.S{i}USDT"])
    assert len(m._pending) == conn_mod.MAX_PENDING_ACKS
    assert _count("overflow") == before + 3
    assert "cv-1" not in m._pending and "cv-4" in m._pending


async def test_unknown_malformed_and_pong_frames_are_ignored() -> None:
    sock = _Sock()
    m, _ = _mgr(_Clock(), sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    before = (_count("rejected"), _count("timeout"))
    m._on_ack(_ack("nope", success=False))
    m._on_ack(_ack(None, success=False))
    m._on_ack('{"success": false')
    m._on_ack('{"success":true,"ret_msg":"pong","op":"ping"}')
    m._on_ack("[1]")
    assert len(m._pending) == 1
    assert (_count("rejected"), _count("timeout")) == before


async def test_reader_routes_acks_and_still_forwards_frames() -> None:
    clk = _Clock()
    seen: list[str] = []
    sock = _Sock()
    m, wd = _mgr(clk, sock, seen)
    m.set_desired({TOPIC})
    await m.subscribe()
    bad = _ack(sock.sent[0]["req_id"], success=False)
    sock._frames = [bad, '{"topic":"x","data":{}}']
    before = _count("rejected")
    try:
        await m._read(sock)
    except ConnectionError:
        pass
    assert seen == [bad, '{"topic":"x","data":{}}']
    assert _count("rejected") == before + 1
    assert wd.check() == [TOPIC]


async def test_fresh_socket_drops_pending_acks() -> None:
    sock = _Sock()
    m, _ = _mgr(_Clock(), sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    await m.open_socket()
    assert m._pending == {}
