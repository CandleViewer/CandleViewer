"""E17-T03 (#412, S2a-i): the budgeted outbound pipeline and its close path, flag on and off.

With `CV_WS_BACKPRESSURE_ENABLED` on, `_Connection.push` hands every frame to
`ws.pipeline.ConnectionPipeline`: it is encoded once in the negotiated subprotocol, queued on the
`OutboundQueue` lanes inside the 8 MiB / 2 000-frame budget, and sent as is by the writer. A close
takes the terminal slot and flushes under one deadline (`23-ws-protocol.md` §4.4, §8.4); a frame
that cannot be encoded fails closed (§10.1). With the flag off nothing of this exists, and the
wire is byte-for-byte what it was: `test_flag_off_wire_transcript_is_unchanged` pins a transcript
recorded on the commit before this slice.

The real router runs on the test's own loop behind a fake socket (`_Wire`): no threads, no
sleeps, every wait bounded. Frames are queued in one synchronous turn when a test needs the writer
not to drain them meanwhile.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

import msgpack
import pytest
from fastapi.routing import APIWebSocketRoute
from structlog.testing import capture_logs

from candleviewer.audit.models import Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.settings import CLOSE_FLUSH_TIMEOUT_S, Settings
from candleviewer.ws import gateway, outbound, pipeline
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.binary import encode_b64
from candleviewer.ws.cvwb_vectors import vector_frames
from candleviewer.ws.gateway import GatewayHub, _Connection, make_ws_router
from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.metrics import cv_ws_closes_total, cv_ws_overflow_total
from candleviewer.ws.outbound import Queued
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.pipeline import (
    SLOW_CONSUMER_MESSAGE,
    ConnectionPipeline,
    Terminal,
    slow_consumer_bye,
)
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import MAX_OUTBOUND_FRAME_BYTES, SequencingHub, SnapshotBody
from candleviewer.ws.upstream import UpstreamRefs
from tests.unit.ws._seq_support import ACC_A, USER, Book, Source
from tests.unit.ws.test_lifecycle_socket import BASE_MS, ORIGIN, SESSION, _Audit, _Clock

_DEADLINE_S = 5.0
_JSON, _MSGPACK = "cv.v1.json", "cv.v1.msgpack"
_ENCODINGS = pytest.mark.parametrize("encoding", [_JSON, _MSGPACK], ids=["json", "msgpack"])
_BOOK = "book.BTCUSDT.50"
_PERMS = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ})


async def _no_sleep(_s: float) -> None:
    return None


class _Wire:
    """Starlette's `WebSocket`, the slice the handler uses: inbound frames are fed, every send is
    recorded raw (`raw`) and decoded (`sent`), and `hold()` parks sends like a peer that stopped
    reading."""

    def __init__(self, encoding: str = _JSON) -> None:
        self.scope: dict[str, Any] = {
            "headers": [(b"origin", ORIGIN.encode())],
            "subprotocols": [encoding],
            "client": ("127.0.0.1", 50000),
        }
        self.msgpack = encoding == _MSGPACK
        self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.raw: list[tuple[str, str | bytes]] = []
        self.closed_with: int | None = None
        self.parked = asyncio.Event()  # set once a send is held
        self._gate: asyncio.Event | None = None

    def hold(self) -> None:
        self._gate = asyncio.Event()

    def release(self) -> None:
        if self._gate is not None:
            self._gate.set()

    async def accept(self, subprotocol: str | None = None) -> None: ...

    async def receive(self) -> dict[str, Any]:
        return await self.inbound.get()

    async def send_text(self, text: str) -> None:
        await self._send("text", text)

    async def send_bytes(self, data: bytes) -> None:
        await self._send("bytes", data)

    async def _send(self, kind: str, payload: str | bytes) -> None:
        if self._gate is not None and not self._gate.is_set():
            self.parked.set()
            await self._gate.wait()
        self.raw.append((kind, payload))
        frame = msgpack.unpackb(payload) if isinstance(payload, bytes) else json.loads(payload)
        self.sent.put_nowait(frame)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    def feed(self, frame: dict[str, Any]) -> None:
        if self.msgpack:
            self.inbound.put_nowait({"type": "websocket.receive", "bytes": msgpack.packb(frame)})
        else:
            self.inbound.put_nowait({"type": "websocket.receive", "text": json.dumps(frame)})

    async def next(self, n: int = 1) -> list[dict[str, Any]]:
        return [await self.sent.get() for _ in range(n)]


class _Rig:
    """The real `/ws` router, a `SequencingHub` with a book source, and an audit sink."""

    def __init__(self, backpressure: BackpressureConfig | None = None) -> None:
        self.clock = _Clock()
        self.audit = _Audit()
        self.hub = GatewayHub()
        self.revocation = RevocationHub()
        self.sequencing = SequencingHub()
        self.source = Source()
        book = Book("BTCUSDT")
        book.apply([["100.0", "1.000"]], [["101.0", "2.000"]])
        self.source.books["BTCUSDT"] = book
        self.source.bodies["orders"] = SnapshotBody({"orders": []})
        self.expires_at = datetime(2100, 1, 1, tzinfo=UTC)

        async def resolve(uid: Any) -> PrincipalSnapshot:
            grants = (AccountGrant(ACC_A, True, False, False),)
            return PrincipalSnapshot(uid, frozenset({"manager"}), _PERMS, grants)

        async def authenticate(token: str) -> tuple[str, Any, datetime]:
            return SESSION, USER, self.expires_at

        services = SubscriptionServices(
            upstream=UpstreamRefs(), snapshots=self.source, sequencing=self.sequencing
        )
        self.registry = ConnectionRegistry(resolve, self.clock.wall_ms, services)
        router = make_ws_router(
            authenticate=authenticate,
            registry=self.registry,
            revocation_hub=self.revocation,
            allowed_origins=frozenset({ORIGIN}),
            hub=self.hub,
            audit=self.audit,
            clock=self.clock,
            wall_ms=self.clock.wall_ms,
            tick_s=0.005,
            backpressure=backpressure,
        )
        (route,) = router.routes
        assert isinstance(route, APIWebSocketRoute)
        self.endpoint = route.endpoint

    async def open(self, sock: _Wire) -> tuple[asyncio.Task[None], _Connection]:
        """Start the handler and take it through `hello` and `auth`."""
        others = set(self.hub.of_user(USER))
        handler = asyncio.create_task(self.endpoint(sock))
        sock.feed({"t": "hello", "id": "h", "p": {"clock_ms": BASE_MS}})
        assert [f["t"] for f in await sock.next()] == ["welcome"]
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
        assert [f["t"] for f in await sock.next()] == ["auth_ok"]
        (conn,) = [c for c in self.hub.of_user(USER) if c not in others]
        return handler, conn

    async def sub(self, sock: _Wire, ch: str = _BOOK, **opts: Any) -> list[dict[str, Any]]:
        """`sub` one topic; returns its `sub_ok` and its snapshot, as they arrived."""
        if ch == "orders":
            opts.setdefault("exchange_account_ids", [str(ACC_A)])
        else:
            opts.setdefault("encoding", "structured")
        sock.feed({"t": "sub", "id": "s", "p": {"topics": [{"ch": ch, "opts": opts}]}})
        return await sock.next(2)

    def book_delta(self, i: int, **extra: Any) -> int:
        body = {"symbol": "BTCUSDT", "depth": 50, "bids": [[f"{100 + i}.0", "1.000"]], "asks": []}
        return self.sequencing.publish(_BOOK, body | extra)


# -- flag off: the wire is unchanged ----------------------------------------------------------


async def _flag_off_session(encoding: str) -> list[Any]:
    """Three connections on the flag-off path: a session ending in a planned shutdown (welcome,
    auth, a book snapshot, 32 deltas including a sampled one and a non-finite number, a pong, a
    `system` notice), a backlog cut by a revocation (sealed), and a frame the writer cannot
    serialise (the fault path). Returns every send, raw, with the close code and audit row."""
    transcript: list[Any] = []
    for scenario in ("session", "sealed", "fault"):
        rig, sock = _Rig(backpressure=None), _Wire(encoding)
        async with asyncio.timeout(_DEADLINE_S):
            handler, conn = await rig.open(sock)
            assert getattr(conn, "pipeline", None) is None
            await rig.sub(sock)
            if scenario == "session":
                for i in range(31):
                    rig.book_delta(i)
                rig.book_delta(31, x=float("nan"))  # flag off: written as `NaN`, not refused
                await sock.next(32)
                sock.feed({"t": "ping", "id": "p", "p": {"client_ms": BASE_MS - 5}})
                await sock.next()
                rig.hub.broadcast_system({"kind": "tick"})
                await sock.next()
                await rig.hub.shutdown(grace_ms=0, sleep=_no_sleep)
            elif scenario == "sealed":
                for i in range(5):
                    rig.book_delta(i)
                    rig.hub.broadcast_system({"kind": "tick", "n": i})
                await rig.revocation.revoke(SESSION)
            else:
                rig.book_delta(0, bad={1, 2})  # neither codec serialises a set
            await handler
        sends = [[kind, _normalised(p, conn.connection_id)] for kind, p in sock.raw]
        rows = [(r["action"], r["reason"], str(r["severity"])) for r in rig.audit.records]
        transcript.append([scenario, sends, sock.closed_with, rows])
    return transcript


def _normalised(payload: str | bytes, connection_id: str) -> str:
    """The payload with the random connection id replaced (same length, so msgpack stays valid);
    bytes as hex."""
    if isinstance(payload, str):
        return payload.replace(connection_id, "ws_" + "0" * 12)
    return payload.replace(connection_id.encode(), b"ws_" + b"0" * 12).hex()


@_ENCODINGS
async def test_flag_off_wire_transcript_is_unchanged(encoding: str) -> None:
    """Flag off is byte-for-byte the gateway before #412 S2a: the transcript's digest was recorded
    on 731f4820f, the commit this slice starts from."""
    transcript = await _flag_off_session(encoding)
    digest = hashlib.sha256(json.dumps(transcript, sort_keys=True).encode()).hexdigest()
    kinds = {kind for _, sends, _, _ in transcript for kind, _ in sends}
    assert kinds == {"bytes" if encoding == _MSGPACK else "text"}
    assert [(name, code) for name, _, code, _ in transcript] == [
        ("session", 1001),
        ("sealed", 4401),
        ("fault", 1011),
    ]
    assert digest == _FLAG_OFF_DIGESTS[encoding], json.dumps(transcript)[:4000]


#: Recorded with `_flag_off_session` on 731f4820f (the S1 head, before S2a-i touched the gateway),
#: in the rebase from 65d480a2: main's #2890, in between, moved `sub_ok`'s `id` after its `p`.
_FLAG_OFF_DIGESTS = {
    _JSON: "c9c702e8629f7a4dd7ee157e3acddb6a8410db9c249a879f4d015dd8176bb21b",
    _MSGPACK: "134597ecbab2a0f1b5f68bcdd615fff0ec731dda2af32de52c0ecea40fc1403f",
}


# -- flag on: the pipeline alone -----------------------------------------------------------------

_MARK = "zz-payload-marker"  # only payloads carry it: no log line may


def _pipe(
    encoding: str = _JSON, **config: Any
) -> tuple[ConnectionPipeline, list[tuple[str, dict[str, Any] | None]]]:
    """A pipeline whose `close` only records what it was asked (`_Connection.close_with`)."""
    asked: list[tuple[str, dict[str, Any] | None]] = []

    def close(reason: str, *, bye: dict[str, Any] | None = None) -> None:
        asked.append((reason, bye))

    pipe = ConnectionPipeline(
        encoding=encoding,
        config=BackpressureConfig(**config),
        close=close,
        wall_ms=lambda: BASE_MS,
        connection_id="ws_test",
    )
    return pipe, asked


def _queued(pipe: ConnectionPipeline) -> list[dict[str, Any]]:
    out = []
    while (item := pipe.queue.pop()) is not None:
        out.append(json.loads(item.payload))
    return out


def _d(ch: str, **p: Any) -> dict[str, Any]:
    return {"t": "d", "ch": ch, "s": 1, "ts": 1, "e": "j", "p": p}


@_ENCODINGS
async def test_queued_payload_matches_send_frame(encoding: str) -> None:
    """#2897 parity: the payload queued at push is, byte for byte, what `send_frame` writes (a
    CVWB part raw on msgpack); only a non-finite number differs (JSON refuses it, below)."""
    part = dict(vector_frames())["trades"]
    frames: list[dict[str, Any]] = [
        {"t": "welcome", "id": "h", "ts": 1, "p": {"limits": {"a": 1}, "note": "é"}},
        {"t": "d", "ch": "trades.BTCUSDT", "s": 2, "ts": 1, "e": "b64", "p": encode_b64(part)},
        {"t": "snap", "id": "snap-1", "ch": _BOOK, "s": None, "ts": 1, "e": "j", "p": {"a": []}},
        _d("system", kind="tick"),
    ]
    wire = _Wire(encoding)
    conn = _Connection(
        cast(Any, wire), encoding=encoding, clock=float, wall_ms=int, auth_timeout_s=1
    )
    kind = "bytes" if wire.msgpack else "text"
    pipe, _ = _pipe(encoding)
    for frame in frames:
        pipe.push(frame)
        item = pipe.queue.pop()
        await conn.send_frame(frame)
        assert item is not None and wire.raw[-1] == (kind, item.payload)


def test_close_flush_s_can_only_be_lowered() -> None:
    """The stop budget counts `CLOSE_FLUSH_TIMEOUT_S` once (`MIN_DRAIN_TIMEOUT_S`): a config may
    lower the close deadline, never raise or zero it; `Settings` never sets it."""
    assert BackpressureConfig().close_flush_s == CLOSE_FLUSH_TIMEOUT_S == 2.0
    assert BackpressureConfig(close_flush_s=0.25).close_flush_s == 0.25
    for bad in (CLOSE_FLUSH_TIMEOUT_S + 0.001, 0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="close_flush_s"):
            BackpressureConfig(close_flush_s=bad)
    assert BackpressureConfig.from_settings(Settings()).close_flush_s == CLOSE_FLUSH_TIMEOUT_S


@pytest.mark.parametrize("order", ["closed_first", "armed_first"])
async def test_a_close_before_the_writer_starts_still_gets_its_deadline(order: str) -> None:
    """D3: the deadline runs from the first close whether the writer's scope exists yet or not,
    and a seal during the close never extends it."""
    pipe, _ = _pipe(close_flush_s=0.5)
    loop = asyncio.get_running_loop()
    async with asyncio.timeout(None) as scope:
        if order == "armed_first":
            pipe.arm(scope)
            assert scope.when() is None
        before = loop.time()
        pipe.close(slow_consumer_bye(BASE_MS), 4429, flush=True)
        after = loop.time()
        await pipe.queue.ready.wait()  # the close wakes the writer, with nothing queued
        pipe.arm(scope)
        when = scope.when()
        assert when is not None and before + 0.5 <= when <= after + 0.5
        pipe.seal()
        assert pipe.close(slow_consumer_bye(BASE_MS), 4429, flush=True) == 0  # the first stays
        assert scope.when() == when and pipe.terminal is not None and not pipe.terminal.flush
        pipe.disarm()


@pytest.mark.parametrize("flush", [True, False], ids=["flush", "bye_next"])
async def test_a_close_keeps_only_the_priority_lane_or_nothing_and_queues_nothing_after(
    flush: bool,
) -> None:
    """§8.4: a flushing close keeps the priority lane, any other keeps nothing; the writer is
    woken for the `bye`, and nothing pushed after the close is queued (WS-D01)."""
    pipe, _ = _pipe()
    pipe.push(_d(_BOOK, n=1))
    pipe.push(_d("system", n=1))
    assert pipe.close(slow_consumer_bye(BASE_MS), 4429, flush=flush) == (1 if flush else 2)
    pipe.push(_d("system", n=2))
    pipe.push(_d(_BOOK, n=2))
    assert pipe.queue.ready.is_set()
    assert [f["p"] for f in _queued(pipe)] == ([{"n": 1}] if flush else [])
    assert pipe.seal() == 0 and pipe.terminal is not None and not pipe.terminal.flush


async def test_a_seal_during_a_flushing_close_drops_the_priority_lane_too() -> None:
    """The identity ends while a close flushes: what the priority lane still holds goes too,
    and the first close's `bye` is next (§8.4)."""
    pipe, _ = _pipe()
    pipe.push(_d("system", n=1))
    bye = bye_frame("shutdown", now_ms=BASE_MS)
    pipe.close(bye, 1001, flush=True)
    assert pipe.seal() == 1
    assert _queued(pipe) == []
    assert pipe.terminal == Terminal(bye, 1001, flush=False)


@pytest.mark.parametrize(
    "frame",
    [
        _d("orders", bad={1}),
        _d("system", x=float("inf")),
        {"t": "sub_ok", "id": "s", "p": {"results": [{"x": float("nan")}]}},
        _d(_BOOK, x=float("nan")),
    ],
    ids=["orders", "system", "control", "market"],
)
def test_an_unencodable_frame_fails_closed(frame: dict[str, Any]) -> None:
    """D9 (S2a-i): a frame its encoder refuses closes the connection `internal_error`, never
    silently dropped. A market-data frame does too until the ladder can re-snapshot it."""
    pipe, asked = _pipe()
    pipe.push(frame)
    assert asked == [("internal_error", None)]
    assert len(pipe.queue) == 0


# -- flag on: through the socket -----------------------------------------------------------------


def _counter(metric: Any, **labels: str) -> float:
    value: float = metric.labels(**labels)._value.get()
    return value


def _closes(reason: str) -> float:
    return _counter(cv_ws_closes_total, reason=reason)


def _overflow(reason: str) -> float:
    return _counter(cv_ws_overflow_total, reason=reason)


def _rows(rig: _Rig) -> list[tuple[str, str, Severity]]:
    return [(r["action"], r["reason"], r["severity"]) for r in rig.audit.records]


@_ENCODINGS
async def test_frames_are_encoded_once_and_counted_at_wire_length(
    encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2887: each frame is encoded once, at push, in the connection's subprotocol; the queue
    counts the bytes the socket is then sent, and the writer sends them as they are."""
    encoded: list[Any] = []
    real = outbound.encode

    def counting(frame: Any, dumps: Any, *, received: float | None = None) -> Queued:
        encoded.append(frame["t"])
        return real(frame, dumps, received=received)

    monkeypatch.setattr(pipeline, "encode", counting)
    rig, sock = _Rig(BackpressureConfig()), _Wire(encoding)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        assert conn.pipeline is not None
        sock.hold()
        rig.hub.broadcast_system({"kind": "tick"})
        await sock.parked.wait()  # that frame is in the writer's hand; the next four queue
        encoded.clear()
        for i in range(3):
            rig.book_delta(i)
        rig.hub.broadcast_system({"kind": "tick", "n": 1})
        queued, start = conn.pipeline.queue.bytes, len(sock.raw)
        sock.release()
        await sock.next(5)
        handler.cancel()
        await asyncio.wait({handler})
    assert encoded == ["d"] * 4  # once each, at push; the writer encoded nothing
    assert sum(len(payload) for _, payload in sock.raw[start + 1 :]) == queued
    assert {kind for kind, _ in sock.raw} == {"bytes" if sock.msgpack else "text"}


async def test_over_budget_closes_slow_consumer_4429() -> None:
    """§8.4 step 3 (S2a: no drop step yet): the push that leaves the budget closes the connection
    `slow_consumer`; both lanes are cleared, so the `bye` is next, with `retry_after_ms` and the
    generic message. Counted twice over (closes, `close_budget`) and audited at `warning`; the
    `bye` went out, so no flush expired."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire()
    closes, budget = _closes("slow_consumer"), _overflow("close_budget")
    expired = _overflow("close_flush_deadline")
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        await rig.sub(sock)
        for i in range(9):
            rig.book_delta(i)  # in one turn: the ninth is one frame over
        (bye,) = await sock.next()
        await handler
    assert bye["p"] == {
        "code": 4429,
        "reason": "slow_consumer",
        "message": SLOW_CONSUMER_MESSAGE,
        "reconnect": True,
        "retry_after_ms": 3000,
    }
    assert sock.closed_with == 4429 and sock.sent.empty()
    assert _closes("slow_consumer") == closes + 1
    assert (_overflow("close_budget"), _overflow("close_flush_deadline")) == (budget + 1, expired)
    assert _rows(rig) == [("ws.connection.closed", "slow_consumer", Severity.WARNING)]


@pytest.mark.parametrize("family", ["orders", "system"])
async def test_a_priority_backlog_over_budget_closes_slow_consumer(family: str) -> None:
    """Both lanes count toward the one budget (C-2.18): a peer that cannot drain `orders` or
    `system` frames meets the same close as any other."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        if family == "orders":
            await rig.sub(sock, "orders")
        for i in range(9):
            if family == "orders":
                rig.sequencing.publish("orders", {"orders": [], "n": i}, account=ACC_A)
            else:
                rig.hub.broadcast_system({"kind": "tick", "n": i})
        (bye,) = await sock.next()
        await handler
    assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", "slow_consumer", 4429)


@pytest.mark.parametrize("ending", ["token_expired", "session_revoked"])
async def test_token_expiry_and_revocation_clear_both_lanes_under_the_flag(ending: str) -> None:
    """A close that ends the identity sends nothing it had queued, on either lane: the `bye` is
    next (§4.3, §9.5)."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    rig.expires_at = datetime.fromtimestamp((BASE_MS + 60_000) / 1000, tz=UTC)
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        await rig.sub(sock)
        for i in range(5):
            rig.book_delta(i)
            rig.hub.broadcast_system({"kind": "tick", "n": i})
        if ending == "token_expired":
            rig.clock.now = 60.0  # the writer's next step seals the close
        else:
            await rig.revocation.revoke(SESSION)
        (bye,) = await sock.next()
        await handler
    assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", ending, 4401)
    assert sock.sent.empty()


async def test_shutdown_notice_precedes_bye_1001_under_the_flag() -> None:
    """§9.4: a planned shutdown flushes the priority lane (its notice), then `bye` 1001; the market
    data still on the normal lane is discarded."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        await rig.sub(sock)
        for i in range(5):
            rig.book_delta(i)
        await rig.hub.shutdown(grace_ms=0, sleep=_no_sleep)
        notice, bye = await sock.next(2)
        await handler
    assert (notice["ch"], notice["p"]["kind"]) == ("system", "shutdown_notice")
    assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", "shutdown", 1001)
    assert sock.sent.empty()


async def test_nothing_but_bye_after_the_close() -> None:
    """WS-D01: after a close nothing more is queued, from any source: what the close kept, then
    its `bye`."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        rig.hub.broadcast_system({"kind": "before"})
        conn.close_with("heartbeat_timeout")
        rig.hub.broadcast_system({"kind": "after"})
        rig.book_delta(1)
        assert conn.pipeline is not None
        conn.pipeline.push({"t": "pong", "id": "late", "ts": 1, "p": {"server_ms": 1}})
        before, bye = await sock.next(2)
        await handler
    assert before["p"]["kind"] == "before"
    assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", "heartbeat_timeout", 1001)
    assert sock.sent.empty()


async def test_a_frame_taken_before_a_sealing_close_is_never_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The writer checks again after each pop: a frame it already took when the identity ended
    (the watchdog's check before the send) is dropped; the `bye` is next."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        assert conn.pipeline is not None
        pop = conn.pipeline.queue.pop

        def pop_then_expire() -> Queued | None:
            item = pop()
            if item is not None and not conn.closing:
                conn.close_with("token_expired", seal=True)  # as `watch` does at the expiry
            return item

        monkeypatch.setattr(conn.pipeline.queue, "pop", pop_then_expire)
        rig.book_delta(1)
        (bye,) = await sock.next()
        await handler
    assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", "token_expired", 4401)


async def test_a_parked_send_is_torn_down_within_the_close_deadline() -> None:
    """WS-D01 (D3): a peer that neither reads nor sends cannot hold a closing connection: past
    `close_flush_s` the writer abandons the flush with no `bye`, the handler tears down, and the
    audit row still reads the `bye`'s reason. The expiry is counted as `close_flush_deadline`
    and logged (§8.4). Without the deadline this test's own timeout fires."""
    rig, sock = _Rig(BackpressureConfig(close_flush_s=0.01)), _Wire()
    expired, budget = _overflow("close_flush_deadline"), _overflow("close_budget")
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, conn = await rig.open(sock)
            sock.hold()
            rig.hub.broadcast_system({"kind": "tick"})
            await sock.parked.wait()
            sent = len(sock.raw)
            conn.close_with("slow_consumer")
            await handler
    assert len(sock.raw) == sent and sock.closed_with is None and conn.close_code is None
    assert _rows(rig) == [("ws.connection.closed", "slow_consumer", Severity.WARNING)]
    assert (_overflow("close_flush_deadline"), _overflow("close_budget")) == (expired + 1, budget)
    (passed,) = [e for e in logs if e["event"] == "ws close deadline passed"]
    assert (passed["reason"], passed["queued"]) == ("slow_consumer", 0)
    assert passed["log_level"] == "warning"


async def test_a_step_3_close_whose_flush_expires_counts_under_both_reasons() -> None:
    """§8.4 step 4: a budget close whose flush also expires counts `close_budget` at the close
    and `close_flush_deadline` at the expiry; the audit row keeps `slow_consumer`."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8, close_flush_s=0.01)), _Wire()
    expired, budget = _overflow("close_flush_deadline"), _overflow("close_budget")
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        sock.hold()
        rig.hub.broadcast_system({"kind": "tick"})
        await sock.parked.wait()  # the writer holds that frame, and the queue is empty
        sent = len(sock.raw)
        for i in range(9):
            rig.hub.broadcast_system({"kind": "tick", "n": i})  # the ninth is one over
        await handler
    assert len(sock.raw) == sent and sock.closed_with is None
    assert _overflow("close_budget") == budget + 1
    assert _overflow("close_flush_deadline") == expired + 1
    assert _rows(rig) == [("ws.connection.closed", "slow_consumer", Severity.WARNING)]


async def test_a_fault_flush_during_a_close_gets_what_is_left_of_its_deadline() -> None:
    """§8.4, one deadline: a fault's `bye` while a close flushes is bounded by that close's
    deadline, not a second window; with no close under way it gets a fresh `close_flush_s`.
    Flag off it has no bound, as before."""
    loop = asyncio.get_running_loop()
    kw: dict[str, Any] = {"encoding": _JSON, "clock": float, "wall_ms": int, "auth_timeout_s": 1}
    async with gateway._fault_flush(_Connection(cast(Any, _Wire()), **kw)) as unbounded:
        assert unbounded is None
    conn = _Connection(cast(Any, _Wire()), **kw, backpressure=BackpressureConfig(close_flush_s=0.5))
    assert conn.pipeline is not None and conn.pipeline.deadline is None
    before = loop.time()
    async with gateway._fault_flush(conn) as fresh:
        assert isinstance(fresh, asyncio.Timeout)
        when = fresh.when()
    assert when is not None and before + 0.5 <= when <= loop.time() + 0.5
    conn.close_with("heartbeat_timeout")
    deadline = conn.pipeline.deadline
    async with gateway._fault_flush(conn) as rest:
        assert isinstance(rest, asyncio.Timeout) and deadline is not None
        assert rest.when() == deadline


async def test_the_fault_bye_is_bounded_by_the_close_deadline_under_the_flag() -> None:
    """A server fault's `bye` and 1011 go out under the same deadline, so a peer that stopped
    reading cannot park the fault path either (flag off it stays unbounded); its expiry is
    counted and logged like the writer's."""
    rig, sock = _Rig(BackpressureConfig(close_flush_s=0.01)), _Wire()
    rig.expires_at = datetime(2100, 1, 1)  # naive: an authenticator contract fault (1011)
    expired = _overflow("close_flush_deadline")
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler = asyncio.create_task(rig.endpoint(sock))
            sock.feed({"t": "hello", "id": "h"})
            await sock.next()
            sock.hold()
            sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
            await handler
    assert [kind for kind, _ in sock.raw] == ["text"] and sock.closed_with is None
    assert _overflow("close_flush_deadline") == expired + 1
    (passed,) = [e for e in logs if e["event"] == "ws close deadline passed"]
    assert passed["reason"] == "internal_error"


async def test_orders_encode_failure_closes_internal_error_audited_counted_redacted() -> None:
    """§10.1 (D9): an `orders` frame that cannot be encoded fails closed on either subprotocol:
    the priority lane is flushed, then `bye internal_error` and 1011; audited at `warning`,
    counted, and logged by type, family and error class only (C-12.6). `publish` raises nothing
    and goes on to the next connection."""
    rig, socks = _Rig(BackpressureConfig()), [_Wire(_JSON), _Wire(_MSGPACK)]
    before = _closes("internal_error")
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handlers = []
            for sock in socks:
                handlers.append((await rig.open(sock))[0])
                await rig.sub(sock, "orders")
            rig.hub.broadcast_system({"kind": "kept"})
            body = {"orders": [{"note": _MARK, "bad": {1, 2}}]}  # a set: neither codec has one
            assert rig.sequencing.publish("orders", body, account=ACC_A) == 2
            ends = [await sock.next(2) for sock in socks]
            await asyncio.wait(handlers)
    for (kept, bye), sock in zip(ends, socks, strict=True):
        assert kept["p"]["kind"] == "kept"
        assert (bye["t"], bye["p"]["reason"], sock.closed_with) == ("bye", "internal_error", 1011)
    assert _closes("internal_error") == before + 2
    assert _rows(rig) == [("ws.connection.closed", "internal_error", Severity.WARNING)] * 2
    events = [e for e in logs if e["event"] == "ws frame unencodable"]
    named = [(e["t"], e["family"], e["error"], e["log_level"]) for e in events]
    assert named == [("d", "orders", "TypeError", "error")] * 2
    assert _MARK not in repr(logs) and all("exc_info" not in e for e in events)


async def test_an_outbound_frame_over_4_mib_is_logged_and_sent() -> None:
    """#2818: a frame over the 4 MiB frame limit is logged by type, family and size, never its
    payload, and still sent: refusing it would cut a stream the client cannot recover."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, _ = await rig.open(sock)
            rig.hub.broadcast_system({"kind": "big", "pad": "x" * MAX_OUTBOUND_FRAME_BYTES})
            (frame,) = await sock.next()
            handler.cancel()
            await asyncio.wait({handler})
    assert frame["p"]["kind"] == "big"
    (event,) = [e for e in logs if e["event"] == "ws outbound frame over the frame limit"]
    assert (event["t"], event["family"], event["log_level"]) == ("d", "system", "warning")
    assert event["size"] > MAX_OUTBOUND_FRAME_BYTES and "x" * 64 not in repr(logs)


async def test_teardown_releases_the_pipeline() -> None:
    """The handler's tail frees the queue, and nothing can be queued afterwards (C-2.18)."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        sock.hold()
        for i in range(4):
            rig.book_delta(i)
        await sock.parked.wait()
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await handler
    pipe = conn.pipeline
    assert pipe is not None and pipe.released
    assert (len(pipe.queue), pipe.queue.bytes) == (0, 0)
    pipe.push(_d("system"))
    assert len(pipe.queue) == 0
