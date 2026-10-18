"""E17-T06 (#571) slice D2: `sp` through the real `/ws` router, on both codecs and both writers
(flag off, and `CV_WS_BACKPRESSURE_ENABLED` on): a string on MessagePack too, left out of
`cv_ws_frame_bytes{json|msgpack}` (20 section 12.1) by exactly what the real encoders write for
it, the writer's debug span record, a client's `sp` ignored, and `CV_TELEMETRY_ENABLED` choosing
the id source. A fake clock times the span: the hub takes each delta at `t` and the writer sends it
at `t` + 0.25 s, one delta at a time, so flag on each comes past the book window and the pacer lets
it out at once (D12) and its span starts at that release (D7, #3269).
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import logging
import re
from contextlib import redirect_stdout
from typing import Any

import msgpack
import pytest
import structlog
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.observability.logging import configure_logging, reset_logging
from candleviewer.settings import Environment, Settings
from candleviewer.ws import gateway
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.binary import BOOK_DELTA, Frame
from candleviewer.ws.codec import encode_server_frame
from candleviewer.ws.metrics import (
    FANOUT_SECONDS,
    JSON_KIND,
    MSGPACK_KIND,
    SAMPLE_EVERY,
    frame_bytes,
)
from candleviewer.ws.outbound import Queued, Spanned, encode
from candleviewer.ws.sequencing import new_span_id
from tests.unit.ws.test_frame_metrics import _writer
from tests.unit.ws.test_pipeline_outbound import _BOOK, _DEADLINE_S, _JSON, _MSGPACK, _Rig, _Wire

N = SAMPLE_EVERY
SPAN = re.compile(r"[0-9a-f]{16}")
BODY = {"symbol": "BTCUSDT", "bids": [["100.0", "1.500"]], "asks": []}
PART = Frame(BOOK_DELTA, records=((0, 1000, 1500),), price_scale=1, qty_scale=3)
FLAGS = pytest.mark.parametrize("flag", [False, True], ids=["flag_off", "flag_on"])
ENCODINGS = pytest.mark.parametrize("encoding", [_JSON, _MSGPACK], ids=["json", "msgpack"])
SPAN_EVENT = "ws frame span"
#: A valid-looking id a client sends: only where it came from tells it apart.
CLIENT_SP = "c11e47c11e47c11e"


def _decoded(payload: str | bytes) -> dict[str, Any]:
    frame: dict[str, Any] = (
        msgpack.unpackb(payload) if isinstance(payload, bytes) else json.loads(payload)
    )
    return frame


async def _session(
    encoding: str, flag: bool, deltas: int, *, span_ids: bool = True
) -> tuple[_Wire, str]:
    """`hello`, `auth`, a binary `book` subscription (its `snap` is `s` 1) and `deltas` deltas,
    with span ids on unless `span_ids` is off; returns the wire and the connection id once the
    socket has closed. Delta k is taken at 1.0 + 0.25k s and sent 250 ms later: flag on, that is
    past the book window, so none of them waits in the pacer (#3329)."""
    rig = _Rig(BackpressureConfig() if flag else None)
    rig.registry.services.span_ids = new_span_id if span_ids else None
    sock = _Wire(encoding)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock, encoding="binary")
        rig.clock.now = 1.0
        for _ in range(deltas):
            assert rig.sequencing.publish(_BOOK, BODY, part=PART) == 1
            rig.clock.now += 0.25
            await sock.next()
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await handler
    return sock, conn.connection_id


def _carrying_sp(sock: _Wire) -> list[tuple[dict[str, Any], str | bytes]]:
    return [(f, p) for f, p in ((_decoded(p), p) for _, p in sock.raw) if "sp" in f]


def _written(frame: dict[str, Any], *, msgpack_codec: bool) -> str | bytes:
    """`frame` as the connection's codec writes it: the real encoders, not the size of `sp`."""
    if msgpack_codec:
        return encode_server_frame(frame)
    return json.dumps(frame, separators=(",", ":"))


def _without_sp(frame: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in frame.items() if k != "sp"}


@FLAGS
@ENCODINGS
async def test_sp_goes_out_as_a_string_and_is_left_out_of_the_frame_bytes(
    encoding: str, flag: bool
) -> None:
    msgpack_codec = encoding == _MSGPACK
    kind = MSGPACK_KIND if msgpack_codec else JSON_KIND
    before = _writer()[kind][1]
    sock, _ = await _session(encoding, flag, N - 1)  # `s` 2 to N: the hub stamps N
    after = _writer()[kind][1]
    ((frame, payload),) = _carrying_sp(sock)
    assert frame["s"] == N and type(frame["sp"]) is str and SPAN.fullmatch(frame["sp"])
    # §3.2: on MessagePack the b64 body goes out raw (`e: "b"`), and `sp` stays a string.
    wire = ("b", bytes) if msgpack_codec else ("b64", str)
    assert (frame["e"], type(frame["p"])) == wire
    # The series counts the frame as the same codec writes it without `sp` (20 section 12.1): the
    # difference is read off the encoders, whose output for the frame sent is the payload itself.
    assert _written(frame, msgpack_codec=msgpack_codec) == payload
    bare = len(_written(_without_sp(frame), msgpack_codec=msgpack_codec))
    assert frame_bytes(payload, frame["sp"], msgpack=msgpack_codec) == bare < len(payload)
    assert (after[0] - before[0], after[1] - before[1]) == (N, N * bare)


#: A delta, and the widest snapshot envelope the sizing allows (10 keys, 20-digit numbers), each
#: as it is before it gets an `sp`.
_SHAPES: dict[str, dict[str, Any]] = {
    "delta": {"t": "d", "ch": _BOOK, "s": N, "ts": 1789133000000, "e": "b64", "p": "AAECAw=="},
    "widest-snap": {
        "t": "snap",
        "id": f"snap-{2**64 - 1}",
        "ch": _BOOK,
        "s": 2**64 - 1,
        "ts": 2**64 - 1,
        "rs": "0a000000-0000-4000-8000-000000000001",
        "wt": 2**64 - 1,
        "meta": {"reason": "instrument_revision", "source": "replay", "previous_seq": 2**64 - 1},
        "e": "b64",
        "p": "AAECAw==",
    },
}


@pytest.mark.parametrize("shape", _SHAPES.values(), ids=list(_SHAPES))
@ENCODINGS
def test_frame_bytes_takes_off_exactly_what_sp_adds_under_each_codec(
    encoding: str, shape: dict[str, Any]
) -> None:
    """A 16-character `sp` adds what the codec's encoder says it does, whatever the envelope, and
    `frame_bytes` takes exactly that off: the frame as the same codec writes it without `sp`."""
    msgpack_codec = encoding == _MSGPACK
    stamped = shape | {"sp": new_span_id()}
    payload = _written(stamped, msgpack_codec=msgpack_codec)
    bare = len(_written(shape, msgpack_codec=msgpack_codec))
    assert bare < len(payload)
    assert frame_bytes(payload, stamped["sp"], msgpack=msgpack_codec) == bare


def test_frame_bytes_follows_the_callers_codec_not_the_type_the_serialiser_returns() -> None:
    """A JSON serialiser that returned bytes (orjson does) is still JSON: the size `sp` took off
    is the connection's codec's, never read off the payload's Python type."""
    shape = _SHAPES["delta"]
    stamped = shape | {"sp": new_span_id()}
    as_bytes = json.dumps(stamped, separators=(",", ":")).encode()
    bare = len(json.dumps(shape, separators=(",", ":")))
    assert frame_bytes(as_bytes, stamped["sp"], msgpack=False) == bare


def test_only_a_sampled_frame_that_carries_sp_is_queued_as_spanned() -> None:
    """Any other `Queued` keeps the fields it had before `sp` (23 section 3.1), so the 31 frames in
    32 that are not sampled cost what they did, and so does a sampled one with no id source. The
    sampled frame that carries `sp` is a `Spanned`, with `sp` and `s` for the writer's record."""
    names = [f.name for f in dataclasses.fields(Queued)]
    assert names == ["payload", "priority", "family", "key", "resnap", "received"]
    frame = {"t": "d", "ch": _BOOK, "s": N, "ts": 1, "e": "j", "p": {}}
    sp = new_span_id()
    assert type(encode(frame)) is Queued
    assert type(encode(frame, received=1.0)) is Queued
    item = encode(frame | {"sp": sp}, received=1.0)
    assert type(item) is Spanned and (item.sp, item.s, item.received) == (sp, N, 1.0)
    assert item.key == (_BOOK, None) and not item.priority


@FLAGS
async def test_the_writer_logs_one_debug_span_record_per_frame_that_carries_sp(
    flag: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """The exact entry, with the writer task's context merged in: it holds the connection id and
    no user or session id (bound after the writer was spawned)."""
    caplog.set_level(logging.DEBUG)
    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        sock, connection_id = await _session(_JSON, flag, 2 * N - 1)  # `s` 2 to 2N
    sent = [frame for frame, _ in _carrying_sp(sock)]
    assert [f["s"] for f in sent] == [N, 2 * N]
    assert [e for e in logs if e["event"] == SPAN_EVENT] == [
        {
            "event": SPAN_EVENT,
            "log_level": "debug",
            "connection_id": connection_id,
            "span_id": f["sp"],
            "ch": _BOOK,
            "s": f["s"],
            "fanout_ms": 250.0,
        }
        for f in sent
    ]


@FLAGS
async def test_a_sampled_frame_with_no_id_source_is_sent_without_sp_and_logs_no_record(
    flag: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Latency telemetry off, the process at debug: the stamped delta still goes out and counts for
    the fan-out series, the writer goes on to the next frame, and nothing names a span for it."""
    caplog.set_level(logging.DEBUG)
    before = FANOUT_SECONDS.reading()[0][-1]
    with capture_logs() as logs:
        sock, _ = await _session(_JSON, flag, N, span_ids=False)  # `s` 2 to N + 1
    assert FANOUT_SECONDS.reading()[0][-1] - before == N  # the stamped delta was observed
    sent = {f["s"] for f in (_decoded(p) for _, p in sock.raw) if f.get("t") == "d"}
    assert {N, N + 1} <= sent
    assert _carrying_sp(sock) == [] and [e for e in logs if e["event"] == SPAN_EVENT] == []


@FLAGS
async def test_no_span_record_unless_the_process_logs_at_debug(
    flag: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger=gateway.__name__)  # a module override cannot show it
    with capture_logs() as logs:
        sock, _ = await _session(_JSON, flag, N - 1)
    assert len(_carrying_sp(sock)) == 1
    assert [e for e in logs if e["event"] == SPAN_EVENT] == []


@pytest.mark.parametrize(
    ("level", "ws_level", "shown"),
    [("debug", logging.DEBUG, 1), ("info", logging.DEBUG, 0), ("debug", logging.INFO, 0)],
    ids=["debug", "info-with-ws-override-to-debug", "debug-with-ws-override-to-info"],
)
def test_the_span_record_shows_only_under_cv_log_level_debug(
    level: str, ws_level: int, shown: int
) -> None:
    """structlog drops `debug` at the level `configure_logging` set at start, so an E04-T02
    override of `candleviewer.ws` (stdlib levels only) can hide the record but cannot show it."""
    ws, buf = logging.getLogger("candleviewer.ws"), io.StringIO()
    previous = ws.level
    with redirect_stdout(buf):
        configure_logging(env="ci", level=level)
        ws.setLevel(ws_level)
        try:
            gateway._log_span("ws_test", "7c1e9a04d3b58f62", _BOOK, N, 0.004)
        finally:
            ws.setLevel(previous)
        reset_logging()  # stops the listener once its queue is written out
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if SPAN_EVENT in line]
    assert [(e["level"], e["span_id"], e["fanout_ms"]) for e in lines] == [
        ("debug", "7c1e9a04d3b58f62", 4.0)
    ] * shown


async def test_the_server_never_reads_echoes_or_logs_a_client_sp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """23 section 3.1 Inert: a client `sp` on every type of client frame (`hello`, `auth`, `sub`,
    `unsub`, `ctl`, `resync`, `ping`, `pong`), and on a `d` a client may not send, changes no reply
    and appears in no frame and no log entry."""
    caplog.set_level(logging.DEBUG)
    rig = _Rig()
    rig.registry.services.span_ids = new_span_id
    sock, sp = _Wire(_JSON), {"sp": CLIENT_SP}
    sub = {"topics": [{"ch": _BOOK, "opts": {"encoding": "structured"}}]}
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler = asyncio.create_task(rig.endpoint(sock))
            for frame in (
                {"t": "hello", "id": "h", "p": {"clock_ms": 1}},
                {"t": "auth", "id": "a", "p": {"access_token": "tok"}},
                {"t": "sub", "id": "s", "p": sub},
                {"t": "ctl", "id": "c", "ch": _BOOK, "p": {"paused": False}},
                {"t": "ping", "id": "p", "p": {"client_ms": 1}},
                {"t": "pong", "id": "s-hb-1", "p": {}},
                {"t": "resync", "id": "r", "ch": _BOOK, "p": {"reason": "manual"}},
                {"t": "d", "id": "x", "ch": _BOOK, "s": N, "ts": 1, "e": "j", "p": {}},
                {"t": "unsub", "id": "u", "p": {"topics": [_BOOK]}},
            ):
                sock.feed(frame | sp)
            replies = await sock.next(9)
            sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
            await handler
    assert [(f["t"], f.get("id")) for f in replies] == [
        ("welcome", "h"),
        ("auth_ok", "a"),
        ("sub_ok", "s"),
        ("snap", None),
        ("ctl_ok", "c"),
        ("pong", "p"),
        ("snap", None),
        ("err", "x"),
        ("unsub_ok", "u"),
    ]
    assert not any(CLIENT_SP in payload for _, payload in sock.raw)
    assert logs and not any(CLIENT_SP in repr(entry) for entry in logs)


@pytest.mark.parametrize("enabled", [True, False], ids=["telemetry_on", "telemetry_off"])
def test_create_app_draws_span_ids_only_while_latency_telemetry_is_on(enabled: bool) -> None:
    settings = Settings(
        environment=Environment.DEMO, allowed_origins="http://testserver", telemetry_enabled=enabled
    )
    span_ids = create_app(settings).state.ws_registry.services.span_ids
    assert span_ids is (new_span_id if enabled else None)
