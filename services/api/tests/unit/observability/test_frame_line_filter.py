"""#415 (E17-R-09, SR-122): a WebSocket frame line of `uvicorn.error` names the frame only.

The tokens have the shape `secrets.token_urlsafe(32)` returns (32 bytes, URL-safe base64, no
padding), their bytes fixed per draw so a run is repeatable (C-13.7), and each holds both `-` and
`_`. Each rides an `auth` frame, as `cv.v1.json` text and as `cv.v1.msgpack` bytes, logged
as the websockets server logs a frame (`< %s` with the frame) and formatted by the app's log config
at DEBUG: neither stdout nor the support bundle's buffer holds any run of 8 of its characters, or
of 4 of its bytes in hex.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import logging
import secrets
from typing import Any, Final

import msgpack
import pytest
from websockets.frames import Frame, Opcode

from candleviewer.observability.frame_lines import FrameLineFilter, frame_summary
from candleviewer.observability.logging import configure_logging, reset_logging
from tests.unit.observability.test_uvicorn_log_routing import _replay_boot


def _token(n: int) -> str:
    """Draw `n`, of the shape `secrets.token_urlsafe(32)` returns: its 32 bytes fixed by `n`."""
    digest = hashlib.sha256(f"draw-{n}".encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _draws(count: int) -> list[str]:
    """The first `count` draws that hold both `-` and `_`."""
    tokens = (_token(n) for n in itertools.count())
    return list(itertools.islice((t for t in tokens if {"-", "_"} <= set(t)), count))


TOKENS: Final = _draws(6)
_FRAMES: Final = {
    "json": lambda t: Frame(Opcode.TEXT, json.dumps(_auth(t), separators=(",", ":")).encode()),
    "msgpack": lambda t: Frame(Opcode.BINARY, msgpack.packb(_auth(t))),
}


def _auth(token: str) -> dict[str, Any]:
    return {"t": "auth", "id": "c-2", "p": {"access_token": token}}


def _record(msg: str, args: object) -> logging.LogRecord:
    return logging.makeLogRecord({"name": "uvicorn.error", "msg": msg, "args": args})


def test_the_draws_have_the_shape_of_token_urlsafe_32() -> None:
    assert {len(t) for t in TOKENS} == {len(secrets.token_urlsafe(32))}
    assert all({"-", "_"} <= set(t) for t in TOKENS)


@pytest.mark.parametrize("msg", ["< %s", "> %s"])
@pytest.mark.parametrize("encoding", sorted(_FRAMES))
def test_a_frame_argument_becomes_its_opcode_and_length(msg: str, encoding: str) -> None:
    frame = _FRAMES[encoding](TOKENS[0])
    record = _record(msg, (frame,))
    assert FrameLineFilter().filter(record) is True
    assert record.getMessage() == f"{msg[0]} {frame.opcode.name} [{len(frame.data)} bytes]"


def test_a_summary_names_a_fragment_and_a_single_byte() -> None:
    assert frame_summary(Frame(Opcode.CONT, b"x", fin=False)) == "CONT [1 byte, continued]"


@pytest.mark.parametrize(
    ("msg", "args"),
    [
        ("< %s", ("GET /ws HTTP/1.1",)),  # not a frame
        ("< %s: %s", ("cookie", "a=b")),
        ("> %s", (Frame(Opcode.TEXT, b"x"), "extra")),
        ("%s", (Frame(Opcode.TEXT, b"x"),)),
    ],
)
def test_any_other_line_or_argument_is_left_as_it_is(msg: str, args: tuple[Any, ...]) -> None:
    record = _record(msg, args)
    FrameLineFilter().filter(record)
    assert record.args is args


def _frame_filters() -> list[logging.Filter]:
    return [f for f in logging.getLogger("uvicorn.error").filters if isinstance(f, FrameLineFilter)]


def test_configure_logging_installs_one_frame_line_filter_and_reset_removes_it() -> None:
    configure_logging(env="ci")
    configure_logging(env="ci")
    try:
        assert len(_frame_filters()) == 1
    finally:
        reset_logging()
    assert _frame_filters() == []


@pytest.mark.parametrize("encoding", sorted(_FRAMES))
@pytest.mark.parametrize("token", TOKENS, ids=[f"draw-{i}" for i in range(len(TOKENS))])
def test_a_frame_line_at_debug_holds_no_part_of_the_token(encoding: str, token: str) -> None:
    frame = _FRAMES[encoding](token)
    got = _replay_boot(
        lambda: logging.getLogger("uvicorn.error").debug("< %s", frame), level="debug", ring=True
    )
    text = "\n".join((got.out, got.err, *got.ring))
    runs = {token[i : i + 8] for i in range(len(token) - 7)}
    runs |= {token.encode()[i : i + 4].hex() for i in range(len(token) - 3)}
    assert [run for run in runs if run in text] == []
    assert f"< {frame.opcode.name} [{len(frame.data)} bytes]" in got.out
