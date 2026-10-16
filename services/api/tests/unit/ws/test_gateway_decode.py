"""`_Connection.decode` (`23-ws-protocol.md` §2.2, §3.6): the frame kind picks the decoder.

A message is text or binary by which key it carries, never by whether its payload is empty. So an
empty binary frame on `cv.v1.json` is a binary frame, never read as JSON, and one on
`cv.v1.msgpack` goes to the msgpack decoder, which refuses it. Every refusal is the same `[]`, so
the answer cannot tell these paths apart: spies on the two decoders record which one ran. The
socket-level rows (strikes, 4400, 1002) live in `test_json_decode_bounds.py` and
`test_msgpack_socket.py`."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import msgpack
import pytest
from fastapi import WebSocket

import candleviewer.ws.gateway as gateway
from candleviewer.ws.codec import decode_client_frame
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES

_JSON, _MSGPACK = "cv.v1.json", "cv.v1.msgpack"
_PING = {"t": "ping", "id": "p"}
_JSON_PING = json.dumps(_PING)
_MSGPACK_PING: bytes = msgpack.packb(_PING)


def _conn(encoding: str) -> _Connection:
    return _Connection(
        cast(WebSocket, None),  # `decode` never touches the socket
        encoding=encoding,
        clock=lambda: 0.0,
        wall_ms=lambda: 0,
        auth_timeout_s=10.0,
    )


@pytest.fixture
def decoders(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Which decoders a `decode` call reached: `json` (the JSON parser) and `msgpack` (SR-185).
    Only the gateway module's own references are replaced, so no other thread sees a spy."""
    ran: list[str] = []
    loads = json.loads

    def spy_loads(raw: str | bytes) -> Any:
        ran.append("json")
        return loads(raw)

    def spy_decode(raw: bytes) -> Any:
        ran.append("msgpack")
        return decode_client_frame(raw)

    monkeypatch.setattr(gateway, "json", SimpleNamespace(loads=spy_loads, dumps=json.dumps))
    monkeypatch.setattr(gateway, "decode_client_frame", spy_decode)
    return ran


#: (subprotocol, ASGI `websocket.receive` message, decoders reached, the decoded frame)
_KIND_ROWS = [
    pytest.param(_JSON, {"text": _JSON_PING}, ["json"], _PING, id="json-text"),
    pytest.param(_JSON, {"text": "null"}, ["json"], None, id="json-null"),
    pytest.param(_JSON, {"text": ""}, ["json"], [], id="json-empty-text"),
    # A binary frame on JSON never reaches the parser, whatever its bytes: valid JSON, or none.
    pytest.param(_JSON, {"bytes": _JSON_PING.encode()}, [], [], id="json-binary"),
    pytest.param(_JSON, {"bytes": b""}, [], [], id="json-empty-binary"),
    # ASGI lets a message carry both keys with the other `None`: the key present is the kind.
    pytest.param(_JSON, {"bytes": b"", "text": None}, [], [], id="json-empty-binary-text-none"),
    pytest.param(_MSGPACK, {"bytes": _MSGPACK_PING}, ["msgpack"], _PING, id="msgpack-binary"),
    pytest.param(_MSGPACK, {"bytes": b"\xc0"}, ["msgpack"], None, id="msgpack-nil"),
    # The right kind, however short: it reaches the decoder, which refuses it as truncated.
    pytest.param(_MSGPACK, {"bytes": b""}, ["msgpack"], [], id="msgpack-empty-binary"),
    pytest.param(
        _MSGPACK, {"bytes": b"", "text": None}, ["msgpack"], [], id="msgpack-empty-binary-text-none"
    ),
    pytest.param(_MSGPACK, {"text": _JSON_PING}, [], [], id="msgpack-text"),
    pytest.param(_MSGPACK, {"text": ""}, [], [], id="msgpack-empty-text"),
    pytest.param(_MSGPACK, {"text": "", "bytes": None}, [], [], id="msgpack-empty-text-bytes-none"),
]


@pytest.mark.parametrize(("encoding", "msg", "reached", "frame"), _KIND_ROWS)
def test_decode_picks_the_decoder_by_frame_kind_not_by_payload(
    decoders: list[str], encoding: str, msg: dict[str, Any], reached: list[str], frame: Any
) -> None:
    got = _conn(encoding).decode({"type": "websocket.receive", **msg}, MAX_INBOUND_FRAME_BYTES)
    assert decoders == reached
    assert got == frame


def test_decode_over_the_cap_closes_1009_and_answers_with_something_no_frame_decodes_to() -> None:
    """The reader stops on this answer. `null` and nil decode to `None`, which must not stop it."""
    conn = _conn(_JSON)
    verdict = conn.decode({"type": "websocket.receive", "text": "x" * 11}, 10)
    assert conn.closing and conn.bye_frame is not None and conn.bye_frame["p"]["code"] == 1009
    assert verdict is not None
