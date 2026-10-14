"""SR-184: malformed / deeply nested client JSON is a protocol violation, never a fault."""

from __future__ import annotations

import logging

import pytest
from starlette.websockets import WebSocketDisconnect

from candleviewer.ws.limits import MAX_JSON_DEPTH, json_depth_exceeds
from tests.unit.ws.test_gateway_limits import _client, _hello


def _nested(depth: int) -> str:
    return "[" * depth + "]" * depth


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
        pytest.param("[" * 100_000, id="100k-open-brackets"),
        pytest.param(_nested(MAX_JSON_DEPTH + 1), id="limit-plus-one"),
        pytest.param('{"t":', id="malformed"),
    ],
)
def test_bad_text_frame_is_err_violation_and_socket_survives(
    frame: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_text(frame)
        assert ws.receive_json()["p"]["code"] == "frame_malformed"
        ws.send_json({"t": "ping", "id": "p"})
        assert ws.receive_json()["t"] == "pong"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_depth_limit_exactly_is_decoded_not_a_depth_violation() -> None:
    inner = '{"t":"ping","id":"p","p":' + _nested(MAX_JSON_DEPTH - 2) + "}"
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_text(inner)
        assert ws.receive_json()["t"] == "pong"


def test_invalid_utf8_bytes_frame_is_violation() -> None:
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_bytes(b'{"t":"\xff\xfe"}')
        assert ws.receive_json()["p"]["code"] == "frame_malformed"


def test_three_bad_frames_close_bad_client_4400_without_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        for frame in ("[" * 100_000, "{", _nested(MAX_JSON_DEPTH + 1)[:-1]):
            ws.send_text(frame)
            msg = ws.receive_json()
            if msg["t"] == "bye":
                break
        assert (msg["t"], msg["p"]["reason"]) == ("bye", "bad_client")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4400
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
