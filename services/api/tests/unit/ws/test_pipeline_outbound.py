"""E17-T03 (#412, S2a-i): the budgeted outbound pipeline and its close path, flag on and off.

With `CV_WS_BACKPRESSURE_ENABLED` on, `_Connection.push` hands every frame to
`ws.pipeline.ConnectionPipeline`: it is encoded once in the negotiated subprotocol, queued on the
`OutboundQueue` lanes inside the 8 MiB / 2 000-frame budget, and sent as is by the writer. A close
takes the terminal slot and flushes under one deadline (`23-ws-protocol.md` §4.4, §8.4); a frame
that cannot be encoded fails closed (§10.1). The one encode at push is where a frame the hub
stamped feeds #2921's frame cost series, once. With the flag off nothing of this exists, and the
wire is byte-for-byte what it was: `test_flag_off_wire_transcript_is_unchanged` pins a transcript
recorded on the commit before this slice.

The real router runs on the test's own loop behind a fake socket (`_Wire`): no threads, no
sleeps, every wait bounded. Frames are queued in one synchronous turn when a test needs the writer
not to drain them meanwhile.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
import struct
from collections.abc import Callable
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
from candleviewer.ws import codec, gateway, outbound, pipeline
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.binary import encode_b64
from candleviewer.ws.cvwb_vectors import vector_frames
from candleviewer.ws.gateway import GatewayHub, _Connection, make_ws_router
from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.metrics import (
    JSON_ENCODE_SECONDS,
    JSON_FRAME_BYTES,
    JSON_KIND,
    MSGPACK_ENCODE_SECONDS,
    MSGPACK_FRAME_BYTES,
    MSGPACK_KIND,
    SAMPLE_EVERY,
    FastHistogramChild,
    cv_ws_closes_total,
    cv_ws_malformed_updates_total,
    cv_ws_overflow_total,
)
from candleviewer.ws.outbound import QUEUE_BYTES, QUEUE_FRAMES, Queued
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
from tests.unit.ws.test_frame_metrics import _Ticks, _writer
from tests.unit.ws.test_lifecycle_socket import BASE_MS, ORIGIN, SESSION, _Audit, _Clock

_DEADLINE_S = 5.0
_JSON, _MSGPACK = "cv.v1.json", "cv.v1.msgpack"
_ENCODINGS = pytest.mark.parametrize("encoding", [_JSON, _MSGPACK], ids=["json", "msgpack"])
_BOOK = "book.BTCUSDT.50"
_PERMS = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ})


async def _no_sleep(_s: float) -> None:
    return None


class _Hub(GatewayHub):
    """These tests feed the writer arbitrary `system` bodies, which SR-188's filter would drop."""

    def broadcast_system(self, body: dict[str, Any]) -> int:
        conns = self._authenticated()
        for conn in conns:
            conn.system_seq += 1
            frame = {"t": "d", "ch": "system", "s": conn.system_seq, "ts": conn.wall_ms(), "e": "j"}
            conn.push(frame | {"p": body})
        return len(conns)


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

    def __init__(
        self,
        backpressure: BackpressureConfig | None = None,
        *,
        system_notices: Callable[[], list[dict[str, Any]]] | None = None,
        tick_s: float = 0.005,
    ) -> None:
        self.clock = _Clock()
        self.paced = backpressure is not None  # flag on, the hub's deltas are paced (S3)
        self.audit = _Audit()
        self.hub = _Hub()
        self.revocation = RevocationHub()
        self.sequencing = SequencingHub()
        self.source = Source()
        book = Book("BTCUSDT")
        book.apply([["100.0", "1.000"]], [["101.0", "2.000"]])
        self.source.books["BTCUSDT"] = book
        self.source.bodies["orders"] = SnapshotBody({"orders": []})
        self.expires_at = datetime(2100, 1, 1, tzinfo=UTC)
        #: What `resolve` reads, so a test can change the principal mid-connection (§9.5).
        self.perms: frozenset[Permission] = _PERMS
        self.grants: tuple[AccountGrant, ...] = (AccountGrant(ACC_A, True, False, False),)

        async def resolve(uid: Any) -> PrincipalSnapshot:
            return PrincipalSnapshot(uid, frozenset({"manager"}), self.perms, self.grants)

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
            tick_s=tick_s,
            system_notices=system_notices,
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
        """One book delta; flag on, 50 ms after the last, so it leaves at once (D12)."""
        body = {"symbol": "BTCUSDT", "depth": 50, "bids": [[f"{100 + i}.0", "1.000"]], "asks": []}
        self.clock.now += 0.05 if self.paced else 0.0
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
    on 731f4820f, before S2a touched the gateway."""
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
    CVWB part raw on msgpack); only a non-finite number differs: with the flag on both codecs
    refuse it (below), and `send_frame`, the flag-off path, does not."""
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


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        *[
            (field, bad)
            for field in ("max_bytes", "max_frames", "classify_interval_ms")
            for bad in (0, -1, True, 1.0)
        ],
        ("max_bytes", QUEUE_BYTES + 1),
        ("max_frames", QUEUE_FRAMES + 1),
    ],
)
def test_a_raised_budget_or_one_that_is_not_a_positive_int_is_refused(field: str, bad: Any) -> None:
    """C-2.18, WS-D01 (#412, third review round): a config checks its budget as it is built, so
    no consumer runs on an unchecked one, hand-built or not. The budget may be lowered, never
    raised (E17 threat model §6): over its ceiling, zero, negative, a `bool` or a `float` fails
    closed. The floors stay with `Settings`, so a harness may still build a budget of one."""
    with pytest.raises(ValueError, match=field):
        BackpressureConfig(**{field: bad})
    assert getattr(BackpressureConfig(**{field: 1}), field) == 1


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
        if order == "armed_first":  # the close itself reschedules a scope that is armed
            early = scope.when()
            assert early is not None and before + 0.5 <= early <= after + 0.5
        await pipe.queue.ready.wait()  # the close wakes the writer, with nothing queued
        pipe.arm(scope)
        when = scope.when()
        assert when is not None and before + 0.5 <= when <= after + 0.5
        assert pipe.deadline == when
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


def _nested(depth: int) -> list[Any]:
    out: list[Any] = []
    for _ in range(depth):
        out = [out]
    return out


@pytest.mark.parametrize(
    ("encoding", "make", "error"),
    [
        (_JSON, lambda: _d("orders", bad={1}), "TypeError"),
        (_JSON, lambda: _d("system", x=float("inf")), "ValueError"),
        (
            _JSON,
            lambda: {"t": "sub_ok", "id": "s", "p": {"results": [{"x": float("nan")}]}},
            "ValueError",
        ),
        (_JSON, lambda: _d(_BOOK, x=float("nan")), "ValueError"),
        (_JSON, lambda: _d("system", x=_nested(100_000)), "RecursionError"),
        (_MSGPACK, lambda: _d("orders", n=2**70), "OverflowError"),
        (_MSGPACK, lambda: {"t": "d", "ch": "trades.BTCUSDT", "s": 1, "e": "b64"}, "KeyError"),
    ],
    ids=["orders", "system", "control", "market", "too_deep", "int_range", "b64_without_p"],
)
def test_an_unencodable_frame_fails_closed(
    encoding: str, make: Callable[[], dict[str, Any]], error: str
) -> None:
    """D9 (S2a-i): whatever the encoder raises closes the connection `internal_error`, logged by
    error class; it is never dropped silently and never raises into the caller (the fan-out). A
    throttled topic's `d` fails closed too before `attach`: no subscription to re-snapshot."""
    pipe, asked = _pipe(encoding)
    with capture_logs() as logs:
        pipe.push(make())
    assert asked == [("internal_error", None)]
    assert len(pipe.queue) == 0
    assert [e["error"] for e in logs if e["event"] == "ws frame unencodable"] == [error]


@_ENCODINGS
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")], ids=str)
@pytest.mark.parametrize("ch", ["orders", _BOOK], ids=["non_droppable", "droppable"])
def test_a_non_finite_number_fails_closed_on_either_codec(
    encoding: str, value: float, ch: str
) -> None:
    """§10.1 (the 23:55Z ruling on #412): with the flag on both encoders refuse a NaN or an
    infinity, a producer bug either way, so it is the encode failure above on either codec:
    `internal_error`, logged as `ValueError`, nothing queued. That holds at any depth, for a
    priority `orders` frame and, before `attach`, for a droppable `d` of a throttled topic (after
    it, that one drops its topic to a re-snapshot instead)."""
    assert outbound.encode(_d(ch, levels=[[1.5, 2.0]])).droppable is (ch == _BOOK)
    pipe, asked = _pipe(encoding)
    with capture_logs() as logs:
        pipe.push(_d(ch, levels=[[1.5, value]]))
    assert asked == [("internal_error", None)]
    assert len(pipe.queue) == 0
    assert [e["error"] for e in logs if e["event"] == "ws frame unencodable"] == ["ValueError"]


@_ENCODINGS
def test_a_non_finite_map_key_fails_closed_on_either_codec(encoding: str) -> None:
    """§10.1, the matrix above for a map key (#412, third review round): a NaN key fails closed
    on both codecs, as JSON refuses it and the MessagePack refusal walks map keys as well as
    values, so the two codecs never disagree on a frame."""
    pipe, asked = _pipe(encoding)
    with capture_logs() as logs:
        pipe.push(_d(_BOOK, levels={float("nan"): "1"}))
    assert asked == [("internal_error", None)]
    assert len(pipe.queue) == 0
    assert [e["error"] for e in logs if e["event"] == "ws frame unencodable"] == ["ValueError"]


@pytest.mark.parametrize(
    "frame",
    [
        pytest.param(
            {
                "t": "d",
                "ch": "trades.BTCUSDT",
                "s": 2,
                "ts": 1,
                "e": "b64",
                "p": base64.b64encode(b"\x00\xcb\x7f\xf8\x00" * 4).decode("ascii"),
            },
            id="binary_part",
        ),
        pytest.param(
            _d(_BOOK, n=int.from_bytes(bytes.fromhex("00cb7ff000000001"), "big")), id="integer"
        ),
        pytest.param(
            _d(_BOOK, px=struct.unpack(">d", bytes.fromhex("4009cb7ff8000000"))[0]),
            id="finite_float",
        ),
    ],
)
def test_bytes_that_only_look_non_finite_are_queued_unchanged_on_msgpack(
    frame: dict[str, Any],
) -> None:
    """The MessagePack refusal searches the packed bytes for a non-finite float and confirms on
    the frame itself: the same bytes inside a binary part, an integer or a finite float's
    mantissa refuse nothing, and the payload queued is `encode_server_frame`'s."""
    payload = codec.encode_server_frame(frame)
    assert pipeline._NON_FINITE_FLOAT64.search(payload) is not None  # the bytes do look non-finite
    pipe, asked = _pipe(_MSGPACK)
    pipe.push(frame)
    item = pipe.queue.pop()
    assert asked == [] and item is not None and item.payload == payload


@pytest.mark.parametrize("half", ["frames", "bytes"])
@pytest.mark.parametrize("flush", [True, False], ids=["flush", "bye_next"])
async def test_at_a_full_budget_a_close_admits_only_its_bye_and_close_marker(
    half: str, flush: bool
) -> None:
    """§8.4 (the 23:55Z ruling on #412): the `bye` and the close marker are the only items
    admitted past the budget, so the bound holds to within one small frame and the budget never
    refuses the `bye` (WS-D01). A queue filled to exactly its budget, by frames or by bytes,
    still takes the close; what the close keeps stays inside the budget, and nothing pushed after
    it is queued, on either lane."""
    frames = [_d("system", n=1), _d(_BOOK, n=2), _d("system", n=3), _d(_BOOK, n=4)]
    probe, _ = _pipe()
    for frame in frames:
        probe.push(frame)
    budget: dict[str, Any] = (
        {"max_frames": len(frames)} if half == "frames" else {"max_bytes": probe.queue.bytes}
    )
    pipe, asked = _pipe(**budget)
    for frame in frames:
        pipe.push(frame)
    queue = pipe.queue
    exactly_full = (
        len(queue) == queue.max_frames if half == "frames" else queue.bytes == queue.max_bytes
    )
    assert exactly_full and not queue.over_budget() and asked == []
    bye = bye_frame("shutdown", now_ms=BASE_MS)
    pipe.close(bye, 1001, flush=flush)
    for frame in frames:
        pipe.push(frame)
    assert pipe.terminal == Terminal(bye, 1001, flush)
    assert asked == [] and not queue.over_budget()
    assert [f["p"]["n"] for f in _queued(pipe)] == ([1, 3] if flush else [])


@_ENCODINGS
def test_the_byte_budget_alone_closes_slow_consumer(encoding: str) -> None:
    """C-2.18, WS-D01: the byte half of the budget binds on its own, at the configured
    `max_bytes`. Frames that fill it exactly stay queued; the push that leaves it, far under
    `max_frames`, asks for the step 3 close."""
    frame = _d(_BOOK, pad="x" * 1000)
    probe, _ = _pipe(encoding)
    probe.push(frame)
    size = probe.queue.bytes
    pipe, asked = _pipe(encoding, max_bytes=5 * size)
    for _ in range(5):
        pipe.push(frame)
    assert (asked, pipe.queue.bytes) == ([], pipe.queue.max_bytes)
    pipe.push(frame)
    assert asked == [("slow_consumer", slow_consumer_bye(BASE_MS, ()))]
    assert len(pipe.queue) == 6 and pipe.queue.max_frames == BackpressureConfig().max_frames


def test_the_budget_charges_each_codec_its_own_wire_bytes() -> None:
    """#2887: the budget counts the bytes the socket is sent. A CVWB part is base64 text on JSON
    and raw bytes on MessagePack, so a budget that one MessagePack frame fills exactly closes the
    JSON connection and not the MessagePack one."""
    part = dict(vector_frames())["trades"]
    frame = {"t": "d", "ch": "trades.BTCUSDT", "s": 2, "ts": 1, "e": "b64", "p": encode_b64(part)}
    sizes = {}
    for encoding in (_JSON, _MSGPACK):
        probe, _ = _pipe(encoding)
        probe.push(frame)
        sizes[encoding] = probe.queue.bytes
    assert sizes[_MSGPACK] < sizes[_JSON]
    closed = {}
    for encoding in (_JSON, _MSGPACK):
        pipe, asked = _pipe(encoding, max_bytes=sizes[_MSGPACK])
        pipe.push(frame)
        closed[encoding] = [reason for reason, _ in asked]
    assert closed == {_JSON: ["slow_consumer"], _MSGPACK: []}


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
    """§8.4 step 3 (nothing to drop): the push that leaves the budget closes the connection
    `slow_consumer`; both lanes are cleared, so the `bye` is next, with `retry_after_ms` and the
    generic message. Counted twice over (closes, `close_budget`) and audited at `warning`; the
    `bye` went out, so no flush expired."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire()
    closes, budget = _closes("slow_consumer"), _overflow("close_budget")
    expired = _overflow("close_flush_deadline")
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        for i in range(9):
            rig.hub.broadcast_system({"kind": "tick", "n": i})  # in one turn: one over
        (bye,) = await sock.next()
        await handler
    assert bye["p"] == {
        "code": 4429,
        "reason": "slow_consumer",
        "message": SLOW_CONSUMER_MESSAGE,
        "reconnect": True,
        "retry_after_ms": 3000,
        "hint": {"most_expensive_topics": []},
    }
    assert sock.closed_with == 4429 and sock.sent.empty()
    assert _closes("slow_consumer") == closes + 1
    assert (_overflow("close_budget"), _overflow("close_flush_deadline")) == (budget + 1, expired)
    assert _rows(rig) == [("ws.connection.closed", "slow_consumer", Severity.WARNING)]
    assert rig.audit.records[0]["after_state"] == {"trigger": "budget"}


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


@_ENCODINGS
async def test_the_default_8_mib_byte_budget_alone_closes_slow_consumer(encoding: str) -> None:
    """WS-D01 at the defaults: seven `system` frames of 1 MiB and a bit stay under the 8 MiB
    budget; the eighth leaves it, 1 992 frames under the frame budget, and closes the connection
    `slow_consumer` 4429. Both lanes are cleared, so the `bye` is next."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(encoding)
    mib = 1024 * 1024
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        assert conn.pipeline is not None
        queue = conn.pipeline.queue
        assert (queue.max_bytes, queue.max_frames) == (8 * mib, 2000)
        for i in range(7):  # in one turn: the writer drains nothing meanwhile
            rig.hub.broadcast_system({"kind": "big", "n": i, "pad": "x" * mib})
        assert 7 * mib < queue.bytes <= 8 * mib and len(queue) == 7 and not conn.closing
        rig.hub.broadcast_system({"kind": "big", "n": 7, "pad": "x" * mib})
        assert conn.closing
        (bye,) = await sock.next()
        await handler
    assert (bye["t"], bye["p"]) == ("bye", slow_consumer_bye(BASE_MS, ())["p"])
    assert sock.closed_with == 4429 and sock.sent.empty()


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
    assert sock.sent.empty() and "after_state" not in rig.audit.records[0]  # no trigger, no expiry


async def test_an_eviction_sends_the_step_3_bye_under_the_flag() -> None:
    """§8.4: with the flag on every `slow_consumer` `bye` is the step 3 one, the registry's
    eviction (a `permission_change` or `revoked` it could not send) included: `retry_after_ms`
    3 000 and the generic message. Both lanes are cleared, so it is next."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        rig.book_delta(1)
        rig.hub.broadcast_system({"kind": "tick"})
        await conn.evict()
        (bye,) = await sock.next()
        await handler
    assert bye["p"] == slow_consumer_bye(BASE_MS)["p"]
    assert sock.closed_with == 4429 and sock.sent.empty()


async def test_auth_ok_precedes_the_system_notices_after_it_under_the_flag() -> None:
    """§8.4 Lanes: `auth_ok` precedes the `system` frames after it, a notice queued in the same
    turn (E27-T02's degraded or read-only state) included: both ride the priority lane (D1)."""
    rig, sock = _Rig(BackpressureConfig(), system_notices=lambda: [{"kind": "notice"}]), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler = asyncio.create_task(rig.endpoint(sock))
        sock.feed({"t": "hello", "id": "h", "p": {"clock_ms": BASE_MS}})
        await sock.next()
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
        first, second = await sock.next(2)
        handler.cancel()
        await asyncio.wait({handler})
    assert [first["t"], second.get("ch")] == ["auth_ok", "system"]


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


async def test_a_close_at_a_full_budget_still_sends_its_bye_and_close_frame() -> None:
    """§8.4 (the 23:55Z ruling on #412), on the wire: with the budget exactly full, a close still
    gets its `bye` and close frame out. The priority lane it keeps goes first; the normal lane and
    everything pushed after the close never reach the socket."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire()
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        assert conn.pipeline is not None
        queue = conn.pipeline.queue
        for i in range(4):  # in one turn: exactly the budget, four frames on each lane
            rig.book_delta(i)
            rig.hub.broadcast_system({"kind": "tick", "n": i})
        assert len(queue) == queue.max_frames and not queue.over_budget() and not conn.closing
        conn.close_with("heartbeat_timeout")
        rig.hub.broadcast_system({"kind": "after"})
        rig.book_delta(4)
        sent = await sock.next(5)
        await handler
    assert [(f["ch"], f["p"]["n"]) for f in sent[:4]] == [("system", i) for i in range(4)]
    end = (sent[4]["t"], sent[4]["p"]["reason"], sock.closed_with)
    assert end == ("bye", "heartbeat_timeout", 1001)
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
    after = {"trigger": "flush_deadline", "flush_abandoned": True}  # §4.3: no step 3 trigger
    assert rig.audit.records[0]["after_state"] == after
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
    after = {"trigger": "budget", "flush_abandoned": True}  # §4.3: the trigger stays step 3's
    assert rig.audit.records[0]["after_state"] == after


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


async def test_a_fault_after_the_writers_expiry_counts_the_expiry_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.4 step 4, once per connection (#412, third review round): the writer's flush deadline
    expires, and the reader faults before the writer's end stops it (injected in that turn). The
    fault's `bye` gets what is left of that deadline, none, so its flush is abandoned too: both
    sites log, and `close_flush_deadline` grows by exactly one."""
    rig, sock = _Rig(BackpressureConfig(close_flush_s=0.01)), _Wire()
    expired = _overflow("close_flush_deadline")
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, conn = await rig.open(sock)
            pipe = conn.pipeline
            assert pipe is not None
            abandon = pipe.abandon

            def abandon_then_fault(reason: str | None) -> None:
                abandon(reason)
                if reason == "heartbeat_timeout":  # the writer's expiry: wake the reader first
                    sock.feed({"t": "ping", "id": "p", "p": {"client_ms": BASE_MS}})

            def reader_fault(_msg: Any, _limit: int) -> Any:
                raise RuntimeError("reader fault")

            monkeypatch.setattr(pipe, "abandon", abandon_then_fault)
            monkeypatch.setattr(conn, "decode", reader_fault)
            sock.hold()
            rig.hub.broadcast_system({"kind": "tick"})
            await sock.parked.wait()
            conn.close_with("heartbeat_timeout")
            await handler
    assert any(e["event"] == "ws connection fault" for e in logs) and sock.closed_with is None
    passed = [e["reason"] for e in logs if e["event"] == "ws close deadline passed"]
    assert passed == ["heartbeat_timeout", "internal_error"]
    assert _overflow("close_flush_deadline") == expired + 1


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


@_ENCODINGS
async def test_a_droppable_encode_failure_marks_backpressure_and_the_fanout_continues(
    encoding: str,
) -> None:
    """§10.1 (D9): a droppable frame its encoder refuses (a book delta with a NaN, on either codec)
    drops its topic to a `backpressure` re-snapshot and counts as a malformed update; the
    connection stays open and the fan-out reaches the next one. Logged at `warning` by type,
    family and error class, never the payload (C-12.6), at most once per family per interval."""
    rig, socks = _Rig(BackpressureConfig()), [_Wire(encoding), _Wire(encoding)]
    before = _closes("internal_error"), _counter(cv_ws_malformed_updates_total, topic="book")
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handlers = []
            for sock in socks:
                handlers.append((await rig.open(sock))[0])
                await rig.sub(sock)
            for i in (1, 2):  # the second refusal is counted, inside the first one's log window
                assert rig.book_delta(i, x=float("nan"), note=_MARK) == 2
                for sock in socks:
                    (snap,) = await sock.next()
                    assert (snap["t"], snap["meta"]["reason"]) == ("snap", "backpressure")
                    sock.feed({"t": "ping", "id": "p", "p": {"client_ms": BASE_MS}})
                    assert [f["t"] for f in await sock.next()] == ["pong"]
            for handler in handlers:
                handler.cancel()
            await asyncio.wait(handlers)
    after = _closes("internal_error"), _counter(cv_ws_malformed_updates_total, topic="book")
    assert after == (before[0], before[1] + 4)
    events = [e for e in logs if e["event"] == "ws frame unencodable"]
    named = [(e["t"], e["family"], e["error"], e["log_level"]) for e in events]
    assert named == [("d", "book", "ValueError", "warning")] * 2 and _MARK not in repr(logs)


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


# -- flag on: the frame cost series (#2921) ------------------------------------------------------

#: The frame cost children a connection's codec feeds (E17-T06), by a readable name.
_COST_NAMES = {
    JSON_ENCODE_SECONDS: "json seconds",
    JSON_FRAME_BYTES: "json bytes",
    MSGPACK_ENCODE_SECONDS: "msgpack seconds",
    MSGPACK_FRAME_BYTES: "msgpack bytes",
}


@_ENCODINGS
@pytest.mark.parametrize("case", ["stamped", "unstamped", "refused"])
def test_a_stamped_frame_is_observed_once_per_series_at_push(
    encoding: str, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2921 with the flag on: the pipeline encodes a frame once, at push, so that is where a
    frame the hub stamped (`received`) is timed, by a `perf_counter` pair around its serialiser
    alone (#3061's fourth review round), and sized at its wire length: one observation in each
    series of its codec's pair, weight `SAMPLE_EVERY`, and none anywhere else. An unstamped frame
    reads no timer and observes nothing; a stamped frame whose encode is refused observes nothing
    and closes instead."""
    ticks = _Ticks(0.25)  # each timer read is 0.25 s after the one before
    real = outbound.encode

    def slow_encode(frame: Any, dumps: Any, *, received: float | None = None) -> Queued:
        ticks.now += 7.0  # the lanes and the `Queued` take 7 s: outside the pair
        return real(frame, dumps, received=received)

    for name in ("json_payload", "msgpack_payload"):
        serialise = getattr(pipeline, name)

        def slow(frame: Any, serialise: Any = serialise) -> Any:
            ticks.now += 5.0  # the serialiser takes 5 s on the stand-in clock: inside the pair
            return serialise(frame)

        monkeypatch.setattr(pipeline, name, slow)
    monkeypatch.setattr(pipeline, "perf_counter", ticks)
    monkeypatch.setattr(pipeline, "encode", slow_encode)
    seen: list[tuple[str, float, int]] = []
    observe = FastHistogramChild.observe

    def spy(child: FastHistogramChild, value: float, weight: int = 1) -> None:
        seen.append((_COST_NAMES.get(child, "another series"), value, weight))
        observe(child, value, weight)

    monkeypatch.setattr(FastHistogramChild, "observe", spy)
    pipe, asked = _pipe(encoding)
    frame = _d(_BOOK, x=float("nan")) if case == "refused" else _d(_BOOK, bids=[["1.0", "2"]])
    pipe.push(frame, received=None if case == "unstamped" else 1.0)
    item = pipe.queue.pop()
    if case == "refused":
        assert (item, asked, seen) == (None, [("internal_error", None)], [])
        return
    assert item is not None and asked == []
    if case == "unstamped":
        assert (ticks.reads, seen) == (0, [])
        return
    codec_kind = "msgpack" if encoding == _MSGPACK else "json"
    assert ticks.reads == 2
    assert seen == [
        (f"{codec_kind} seconds", 5.0 + 0.25, SAMPLE_EVERY),
        (f"{codec_kind} bytes", item.size, SAMPLE_EVERY),
    ]


@_ENCODINGS
@pytest.mark.parametrize(
    "deltas", [2 * SAMPLE_EVERY - 1, SAMPLE_EVERY - 2], ids=["two_stamped", "none_stamped"]
)
async def test_the_budgeted_writer_sends_what_push_timed_and_sized(
    encoding: str, deltas: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2921 through the router with the flag on, as `test_frame_metrics` pins the flag-off
    writer: every frame is encoded once, at push, and sent as encoded; each data frame the hub
    stamped (`s` a multiple of `SAMPLE_EVERY`) is timed and sized once, under the connection's own
    kind only, and the send is not encode time. The writer does not observe a frame again, and a
    session of unstamped frames reads no timer and observes nothing."""
    ticks = _Ticks(1.0)  # the timer pair around the encode: exactly 1 s apart
    monkeypatch.setattr(pipeline, "perf_counter", ticks)
    real, send = outbound.encode, _Connection.send_payload
    encoded: list[str | bytes] = []
    sent: list[str | bytes] = []

    def recording(frame: Any, dumps: Any, *, received: float | None = None) -> Queued:
        item = real(frame, dumps, received=received)
        encoded.append(item.payload)
        return item

    async def slow_send(conn: Any, payload: str | bytes) -> None:
        ticks.now += 10.0  # a send takes 10 s on the stand-in clock: it is not encode time
        sent.append(payload)
        await send(conn, payload)

    monkeypatch.setattr(pipeline, "encode", recording)
    monkeypatch.setattr(_Connection, "send_payload", slow_send)
    kind, n = (MSGPACK_KIND if encoding == _MSGPACK else JSON_KIND), SAMPLE_EVERY
    rig, sock = _Rig(BackpressureConfig()), _Wire(encoding)
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        await rig.sub(sock)  # `sub_ok`, then the `snap`: `s` 1
        before = _writer()
        for i in range(deltas):  # `s` 2 on: the hub stamps `n` and 2 x `n`
            rig.book_delta(i)
        frames = await sock.next(deltas)
        after = _writer()
        handler.cancel()
        await asyncio.wait({handler})
    wire = [payload for _, payload in sock.raw]
    assert {how for how, _ in sock.raw} == {"bytes" if sock.msgpack else "text"}
    assert encoded == sent == wire  # once each, at push; the writer encoded nothing
    stamped = [i for i, f in enumerate(frames) if f["s"] % n == 0]
    assert [frames[i]["s"] for i in stamped] == ([n, 2 * n] if deltas > n else [])
    assert ticks.reads == 2 * len(stamped)  # a timer pair per stamped frame; none for any other
    assert {k for k in after if after[k] != before[k]} == ({kind} if stamped else set())
    (n0, t0), (c0, b0) = before[kind]
    (n1, t1), (c1, b1) = after[kind]
    assert (n1 - n0, c1 - c0) == (n * len(stamped),) * 2  # weight `n`, once each: never twice
    assert t1 - t0 == pytest.approx(n * len(stamped) * 1.0)
    data = wire[-deltas:]
    assert b1 - b0 == n * sum(len(data[i]) for i in stamped)


@_ENCODINGS
async def test_the_idle_budgeted_writer_holds_no_payload_it_sent(encoding: str) -> None:
    """As `test_frame_metrics` pins for the flag-off writer: a stamped frame's payload (up to 4
    MiB for a snapshot chunk) is let go once sent, not held until the next frame. By identity:
    no value the idle writer holds is one of the payloads it sent."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(encoding)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        for i in range(SAMPLE_EVERY - 1):  # `s` 2 to `n`: the last frame sent is the stamped one
            rig.book_delta(i)
        frames = await sock.next(SAMPLE_EVERY - 1)
        (task,) = [t for t in asyncio.all_tasks() if t.get_name() == f"{conn.connection_id}-writer"]
        outer = task.get_coro()
        assert inspect.iscoroutine(outer)
        inner = outer.cr_await  # with the flag on, `writer` awaits `budgeted_writer`
        assert inspect.iscoroutine(inner)
        code, held = inner.cr_code.co_name, dict(inspect.getcoroutinelocals(inner))
        handler.cancel()
        await asyncio.wait({handler})
    assert code == "budgeted_writer" and frames[-1]["s"] == SAMPLE_EVERY
    sent = [payload for _, payload in sock.raw]
    retained = sorted(name for name, value in held.items() if any(value is p for p in sent))
    assert not retained, f"the idle writer still holds a payload it sent, in: {retained}"


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
    assert conn.authz is not None and (conn.authz.on_drop, conn.authz.on_settle) == (None, None)
    pipe.push(_d("system"))
    assert len(pipe.queue) == 0
