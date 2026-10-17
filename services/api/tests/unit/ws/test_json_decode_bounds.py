"""SR-184: malformed / deeply nested client JSON is a protocol violation, never a fault."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from candleviewer.ws.limits import MAX_JSON_CONTAINERS, MAX_JSON_DEPTH, json_depth_exceeds
from tests.unit.ws.test_gateway_limits import _client, _hello
from tests.unit.ws.test_lifecycle_socket import _bye_then_close, _recv


def _nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def _send_raw(ws: Any, frame: str | bytes) -> None:
    if isinstance(frame, str):
        ws.send_text(frame)
    else:
        ws.send_bytes(frame)


def test_depth_scan_limit_exact_accepted_and_plus_one_rejected() -> None:
    assert not json_depth_exceeds(_nested(MAX_JSON_DEPTH), MAX_JSON_DEPTH)
    assert json_depth_exceeds(_nested(MAX_JSON_DEPTH + 1), MAX_JSON_DEPTH)


def test_depth_scan_ignores_brackets_inside_strings() -> None:
    text = '{"a":"' + "[" * 100 + '\\"[[["}'
    assert not json_depth_exceeds(text, MAX_JSON_DEPTH)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # An escaped backslash right before the quote: the string closes, so the brackets
        # after it count.
        pytest.param('["\\\\"' + "[" * 3, True, id="escaped-backslash-closes-string"),
        # An escaped quote does not close the string: the brackets stay inside it.
        pytest.param('["\\"' + "[" * 3 + '"]', False, id="escaped-quote-stays-in-string"),
        # Closers decrement, so sibling containers never accumulate depth.
        pytest.param("[" + "[]," * 50 + "{}]", False, id="siblings-do-not-accumulate"),
        pytest.param("{" * 2 + "}" * 2 + "[" * 3, True, id="depth-after-closed-objects"),
    ],
)
def test_depth_scan_string_and_closer_state_matches_expected(text: str, expected: bool) -> None:
    assert json_depth_exceeds(text, 2) is expected


@pytest.mark.parametrize(
    "frame",
    [
        # One over the container cap, and within the 8 KiB frame cap that holds before `auth_ok`
        # (a longer run of brackets there is `frame_too_big`; see `test_inbound_frame_limits.py`).
        pytest.param("[" * (MAX_JSON_CONTAINERS + 1), id="containers-plus-one"),
        pytest.param(_nested(MAX_JSON_DEPTH + 1), id="limit-plus-one"),
        pytest.param('{"t":', id="malformed"),
        # Valid JSON that is no envelope. It decodes to `None`, which the reader once took for
        # "the oversize close is queued" and ended on, silently (#2905).
        pytest.param("null", id="null"),
    ],
)
def test_bad_text_frame_is_err_violation_and_socket_survives(
    frame: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_text(frame)
        assert _recv(ws)["p"]["code"] == "frame_malformed"
        ws.send_json({"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_100_000_brackets_after_auth_ok_is_err_violation_and_socket_survives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After `auth_ok` a frame may be 256 KiB, so these 100 000 bytes reach the container cap: one
    strike, never scanned or decoded. Before it they are past the 8 KiB cap."""
    caplog.set_level(logging.DEBUG)
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "ok"}})
        assert _recv(ws)["t"] == "auth_ok"
        ws.send_text("[" * 100_000)
        assert _recv(ws)["p"]["code"] == "frame_malformed"
        ws.send_json({"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_depth_limit_exactly_is_decoded_not_a_depth_violation() -> None:
    inner = '{"t":"ping","id":"p","p":' + _nested(MAX_JSON_DEPTH - 2) + "}"
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_text(inner)
        assert ws.receive_json()["t"] == "pong"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'{"t":"ping","id":"p"}', id="valid-json-envelope"),
        pytest.param(b'{"t":"\xff\xfe"}', id="invalid-utf8"),
        pytest.param(b"", id="empty"),
    ],
)
def test_binary_frame_on_json_is_a_strike_whatever_it_carries(payload: bytes) -> None:
    """§2.2, §3.6: `cv.v1.json` takes text frames, so a binary frame is `frame_malformed` and a
    strike by its kind alone. Valid JSON in one is never decoded, and an empty one is still a
    binary frame, not an empty text frame."""
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_bytes(payload)
        assert _recv(ws)["p"]["code"] == "frame_malformed"
        ws.send_json({"t": "ping", "id": "p"})  # a strike is not fatal
        assert _recv(ws)["t"] == "pong"


def test_three_bad_frames_close_bad_client_4400_without_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        for frame in ("[" * (MAX_JSON_CONTAINERS + 1), "{", _nested(MAX_JSON_DEPTH + 1)[:-1]):
            ws.send_text(frame)
            msg = ws.receive_json()
            if msg["t"] == "bye":
                break
        assert (msg["t"], msg["p"]["reason"]) == ("bye", "bad_client")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4400
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize(
    "frame",
    [pytest.param("null", id="null"), pytest.param(b"", id="empty-binary-frame")],
)
def test_frames_that_are_no_envelope_count_strikes_and_the_third_closes_4400(
    frame: str | bytes,
) -> None:
    """#2905: each is a strike like any malformed frame. `null` once ended the reader with no
    `err`, no strike and no `bye`, so a client saw 1006 (S11); an empty binary frame is a strike
    by its kind (§2.2)."""
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        for _ in range(2):
            _send_raw(ws, frame)
            assert _recv(ws)["p"]["code"] == "frame_malformed"
        _send_raw(ws, frame)
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("bad_client", 4400)


@pytest.mark.parametrize(
    "frame",
    [
        pytest.param("null", id="null"),
        pytest.param(b"", id="empty-binary-frame"),
        pytest.param(b'{"t":"hello","id":"h"}', id="binary-hello"),
    ],
)
def test_first_frame_that_is_no_text_hello_is_bye_protocol_violation_1002(
    frame: str | bytes,
) -> None:
    """§4.2, S11: before `hello`, any frame but a text `hello` gets `bye protocol_violation` and
    1002. A `hello` sent as a binary frame is no text frame (§2.2), though the code before #2897
    accepted it. The `bye` is the first frame the server sends, so no `welcome` came before it."""
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _send_raw(ws, frame)
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], bye["p"]["code"], code) == ("protocol_violation", 1002, 1002)
