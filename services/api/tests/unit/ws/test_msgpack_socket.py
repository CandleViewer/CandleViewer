"""#2483: `cv.v1.msgpack` frames (`23-ws-protocol.md` §2.2, §3.2, §3.6; SR-184, SR-185, C-12.6),
mostly at the socket: the real gateway in the E17-S01 lifecycle rig, on a msgpack connection.

Each malformed frame below is a `ping` the gateway would answer with `pong` if the decoder let it
through, so an `err` proves the decoder refused it."""

from __future__ import annotations

import json
import logging
from typing import Any, Final

import msgpack
import pytest
from structlog.testing import capture_logs

from candleviewer.ws.binary import encode, encode_b64
from candleviewer.ws.codec import encode_server_frame
from candleviewer.ws.cvwb_vectors import vector_frames
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES
from tests.unit.ws.test_lifecycle_socket import (
    MSGPACK,
    _auth,
    _bye_then_close,
    _closed,
    _hello,
    _recv,
    _send,
    _World,
)
from tests.unit.ws.test_token_expiry import _USER, _bare_gateway, _Clock

_MARK: Final = "c4f9e2a1b7d3"  # only the fake token below carries it


def _ping(p: Any) -> bytes:
    packed: bytes = msgpack.packb({"t": "ping", "id": "p", "p": p})
    return packed


def _nested(depth: int) -> Any:
    value: Any = None
    for _ in range(depth):
        value = [value]
    return value


#: SR-185 refusals, each wrapped in an otherwise valid `ping`. A text frame is malformed here too.
MALFORMED: Final[dict[str, bytes | str]] = {
    "nesting-past-32": _ping(_nested(32)),  # the envelope is level 1
    "map-past-32-keys": _ping({str(i): 0 for i in range(33)}),
    "array-past-128": _ping([0] * 129),
    "trailing-bytes": _ping(None) + b"\xc0",
    "timestamp": _ping(msgpack.Timestamp(1, 0)),
    "binary-value": _ping(b"x"),
    "json-text-frame": json.dumps({"t": "ping", "id": "p"}),
}


def _send_raw(ws: Any, data: bytes | str) -> None:
    if isinstance(data, str):
        ws.send_text(data)
    else:
        ws.send_bytes(data)


@pytest.mark.parametrize("data", MALFORMED.values(), ids=MALFORMED.keys())
def test_msgpack_malformed_frame_is_a_strike_and_the_socket_survives(data: bytes | str) -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=MSGPACK) as ws:
        _hello(ws)
        _send_raw(ws, data)
        err = _recv(ws)
        assert (err["t"], err["p"]["code"]) == ("err", "frame_malformed")
        _send(ws, {"t": "ping", "id": "p2"})
        assert _recv(ws)["t"] == "pong"


def test_msgpack_three_malformed_frames_close_bad_client_4400() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=MSGPACK) as ws:
        _hello(ws)
        for name in ("nesting-past-32", "map-past-32-keys"):
            _send_raw(ws, MALFORMED[name])
            assert _recv(ws)["p"]["code"] == "frame_malformed"
        _send_raw(ws, MALFORMED["trailing-bytes"])
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("bad_client", 4400)


def test_msgpack_frame_over_the_inbound_cap_gets_bye_then_1009_before_decoding() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=MSGPACK) as ws:
        _hello(ws)
        ws.send_bytes(_ping("x" * MAX_INBOUND_FRAME_BYTES))
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("frame_too_big", 1009)


def test_msgpack_auth_with_trailing_bytes_is_a_strike_and_its_token_reaches_no_log(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """#2509 round 6 (C-12.6): the decoder's `ExtraData` holds the decoded `auth`, token and all.
    The frame is refused before `authenticate`, and no log line, stdlib or structlog, nor
    stdout/stderr, carries the token, not even the close that the third strike logs."""
    caplog.set_level(logging.DEBUG)
    auth = {"t": "auth", "id": "a", "p": {"access_token": f"good-{_MARK}"}}
    w = _World()
    with capture_logs() as events, w.client:
        with w.client.websocket_connect("/ws", subprotocols=MSGPACK) as ws:
            _hello(ws)
            for _ in range(2):
                ws.send_bytes(msgpack.packb(auth) + b"\xc0")
                err = _recv(ws)
                assert (err["t"], err["p"]["code"]) == ("err", "frame_malformed")
            ws.send_bytes(msgpack.packb(auth) + b"\xc0")
            bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("bad_client", 4400)
    assert w.tokens_seen == []  # never authenticated: the frame was refused whole
    out, err_out = capsys.readouterr()
    sinks = {"structlog": repr(events), "logging": caplog.text, "stdout/stderr": out + err_out}
    assert [name for name, text in sinks.items() if _MARK in text] == []
    assert any(e.get("event") == "ws close" and e.get("reason") == "bad_client" for e in events)


def test_msgpack_server_fault_sends_its_bye_in_msgpack_then_1011() -> None:
    """The fault path writes its `bye` in the negotiated encoding too: an authenticator that
    reports no token expiry is a server fault (#2259)."""
    client = _bare_gateway(("sess", _USER), _Clock()).client
    with client, client.websocket_connect("/ws", subprotocols=MSGPACK) as ws:
        _hello(ws)
        bye = _auth(ws)
        code = _closed(ws)
    assert (bye["t"], bye["p"]["reason"], code) == ("bye", "internal_error", 1011)


def test_msgpack_server_frame_carries_its_cvwb_payload_raw() -> None:
    """§3.2: what the emitter wraps for JSON (`e: "b64"`) goes out raw, as `e: "b"` with a `bin`
    `p`; any other frame is the same envelope."""
    part = dict(vector_frames())["trades"]
    frame = {"t": "d", "ch": "trades.BTCUSDT", "s": 1, "ts": 1, "e": "b64", "p": encode_b64(part)}
    assert msgpack.unpackb(encode_server_frame(frame)) == {**frame, "e": "b", "p": encode(part)}
    pong = {"t": "pong", "id": "p", "ts": 1, "p": {"server_ms": 1}}
    assert msgpack.unpackb(encode_server_frame(pong)) == pong
