"""#1955: topic-level subscribe/unsubscribe acks tracked by `req_id` (fake socket + clock).

No recorded PUBLIC-socket ack exists under packages/fixtures/bybit. The accepted and refused
acks come from `ws/public-subscribe-ack-derived.jsonl`: DERIVED (manifest `source` `derived`),
the recorded private ack plus the documented `req_id` echo, not a capture and not evidence.
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
from tests import _corpus as corpus

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
    assert not wd._forced  # a timeout only counts: it never forces the topic stale


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


async def test_reordered_ack_with_req_id_first_is_rejected_not_timeout() -> None:
    clk, sock = _Clock(), _Sock()
    seen: list[str] = []
    m, _ = _mgr(clk, sock, seen)
    m.set_desired({TOPIC})
    await m.subscribe()
    rid = sock.sent[0]["req_id"]
    sock._frames = [f'{{"req_id":"{rid}","success":false,"ret_msg":"x","op":"subscribe"}}']
    rej, tmo = _count("rejected"), _count("timeout")
    try:
        await m._read(sock)
    except ConnectionError:
        pass
    assert _count("rejected") == rej + 1 and m._pending == {}
    clk.t = conn_mod.ACK_TIMEOUT_S + 1
    m._expire_acks()
    assert _count("timeout") == tmo


async def test_refused_only_topic_set_does_not_recycle_the_socket() -> None:
    clk, sock = _Clock(), _Sock()
    m, wd = _mgr(clk, sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    m._on_ack(_ack(sock.sent[0]["req_id"], success=False))
    assert wd.check() == [TOPIC]
    assert not wd.all_stale()  # refused is not silence
    wd.touch(TOPIC)  # a frame arrives: the episode is over
    clk.t = 100.0
    assert wd.check() == [TOPIC] and wd.all_stale()  # genuine silence still recycles


def test_a_refused_topic_never_masks_a_dead_socket() -> None:
    """A refused topic leaves the set judged: when every other limited topic goes silent,
    the socket is suspect, however long the refused one stays forced."""
    clk = _Clock()
    wd = StalenessWatchdog(clk, lambda _e: None, kind_of=topic_kind)
    other = "orderbook.50.ETHUSDT"
    wd.watch(TOPIC)
    wd.watch(other)
    wd.force_stale(TOPIC)
    assert wd.check() == [TOPIC] and not wd.all_stale()  # only the refusal so far
    clk.t = 1_000.0  # the socket dies: the live topic goes silent past its limit
    assert wd.check() == [other]
    assert TOPIC in wd._forced and wd.all_stale()


async def test_stale_resubscribe_is_one_per_episode() -> None:
    clk, sock = _Clock(), _Sock()
    m, wd = _mgr(clk, sock)
    m.set_desired({TOPIC})
    await m.subscribe()
    m._on_ack(_ack(sock.sent[0]["req_id"], success=False))
    for _ in range(3):  # refused again each time: still one episode, one resubscribe
        for t in wd.check():
            await m._resubscribe_stale(t)
        if m._pending:
            m._on_ack(_ack(sock.sent[-1]["req_id"], success=False))
    assert m.topic_resubscribes == 1
    assert [f["op"] for f in sock.sent].count("subscribe") == 2


async def test_failed_send_leaves_no_pending_entry() -> None:
    class _Broken(_Sock):
        async def send(self, frame: str) -> None:
            raise ConnectionError("boom")

    sock = _Broken()
    m, _ = _mgr(_Clock(), sock)
    try:
        await m._send_tracked(sock, "subscribe", [TOPIC])
    except ConnectionError:
        pass
    else:
        raise AssertionError("send error swallowed")
    assert m._pending == {}


async def test_overflow_drops_oldest_unsubscribe_before_any_subscribe() -> None:
    sock = _Sock()
    m, _ = _mgr(_Clock(), sock)
    await m._send_tracked(sock, "subscribe", ["publicTrade.AUSDT"])  # cv-1, oldest overall
    await m._send_tracked(sock, "unsubscribe", ["publicTrade.BUSDT"])  # cv-2
    for i in range(conn_mod.MAX_PENDING_ACKS - 2):
        await m._send_tracked(sock, "subscribe", [f"publicTrade.S{i}USDT"])
    assert len(m._pending) == conn_mod.MAX_PENDING_ACKS
    await m._send_tracked(sock, "subscribe", ["publicTrade.NEWUSDT"])
    assert "cv-2" not in m._pending and "cv-1" in m._pending
    # no unsubscribe left: the oldest subscribe goes
    await m._send_tracked(sock, "subscribe", ["publicTrade.NEW2USDT"])
    assert "cv-1" not in m._pending


async def test_derived_fixture_acks_settle_by_req_id() -> None:
    """Accepted then refused public acks from the DERIVED corpus file (not a capture)."""
    accepted, refused = corpus.frames("ws/public-subscribe-ack-derived.jsonl")
    sock = _Sock()
    m, wd = _mgr(_Clock(), sock)
    topics = set(json.loads(refused)["ret_msg"].split("args:[")[1].rstrip("]").split(","))
    assert len(topics) == 10
    m.set_desired(topics)
    await m.subscribe()
    assert [f["req_id"] for f in sock.sent] == ["cv-1"]  # the fixtures echo cv-1 / cv-2
    rej = _count("rejected")
    m._on_ack(accepted)
    assert m._pending == {} and _count("rejected") == rej
    await m._send_tracked(sock, "subscribe", ["publicTrade.BTCUSDT"])  # cv-2
    assert refused.index('"req_id"') > 250  # long ret_msg: req_id sits far into the frame
    sock._frames = [refused]
    try:
        await m._read(sock)
    except ConnectionError:
        pass
    assert _count("rejected") == rej + 1 and m._pending == {}
    assert wd.check() == ["publicTrade.BTCUSDT"]


async def test_silent_socket_ack_timeout_still_recycles_at_the_staleness_limit() -> None:
    """Regression: a timeout once forced its topics stale, so `all_stale()` never fired for a
    socket silent from connect (trade limit == ACK_TIMEOUT_S) and the recycle was lost."""
    clk, sock = _Clock(), _Sock()
    m, wd = _mgr(clk, sock)
    trade = "publicTrade.BTCUSDT"
    m.set_desired({trade})
    await m.subscribe()
    clk.t = conn_mod.ACK_TIMEOUT_S  # ack deadline and the 10 s trade limit coincide
    before = _count("timeout")
    m._expire_acks()
    assert _count("timeout") == before + 1
    assert wd.check() == [trade] and wd.all_stale()
