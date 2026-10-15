"""MessagePack decoding of `cv.v1.msgpack` client frames (`23-ws-protocol.md` §2.2, SR-185).

A client frame reaches this decoder only below the 256 KiB inbound cap (SR-040), and the
decoder checks the cap again before decoding. msgpack's C unpacker keeps its own nesting
stack (1 024 levels) and bounds every length it reads by the input size, so decoding can
neither recurse nor over-allocate. The decoded value must then be something a JSON frame
could carry: maps with string keys, arrays, strings, finite numbers, booleans and nil,
nested at most `MAX_MSGPACK_DEPTH` deep. Anything else raises `MsgpackFrameError`:
- ext types and timestamps
- binary strings, as values or keys, and non-string keys
- NaN and infinities
- truncated input or trailing bytes
- invalid UTF-8

The gateway counts a `MsgpackFrameError` as `frame_malformed`, as it does for a malformed
JSON frame (SR-184).
"""

from __future__ import annotations

import math
from typing import Any, Final, NoReturn

import msgpack

from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES, MAX_JSON_DEPTH

#: SR-185: the nesting cap SR-184 sets for JSON client frames.
MAX_MSGPACK_DEPTH: Final = MAX_JSON_DEPTH
_SCALARS: Final = (str, int, type(None))  # a bool is an int


class MsgpackFrameError(ValueError):
    """A client frame that is not a valid `cv.v1` MessagePack envelope (`frame_malformed`)."""


def decode_client_frame(raw: bytes) -> Any:
    """One client frame's decoded value, or `MsgpackFrameError` (SR-185)."""
    if len(raw) > MAX_INBOUND_FRAME_BYTES:
        raise MsgpackFrameError("frame exceeds the inbound cap")
    try:
        value = msgpack.unpackb(raw, raw=False, strict_map_key=True, ext_hook=_refuse_ext)
    except MsgpackFrameError:
        raise
    except ValueError as exc:  # every unpackb failure: format, stack, extra data, UTF-8, lengths
        raise MsgpackFrameError(f"undecodable frame: {type(exc).__name__}") from exc
    _check(value)
    return value


def _refuse_ext(code: int, data: bytes) -> NoReturn:
    raise MsgpackFrameError(f"ext type {code} is not allowed")


def _check(value: Any) -> None:
    """Refuse what JSON could not carry and nesting deeper than the cap, without recursing."""
    stack: list[tuple[Any, int]] = [(value, 1)]  # (node, its level if it is a container)
    while stack:
        node, level = stack.pop()
        if isinstance(node, dict | list):
            if level > MAX_MSGPACK_DEPTH:
                raise MsgpackFrameError(f"nesting deeper than {MAX_MSGPACK_DEPTH}")
            if isinstance(node, dict):
                if not all(isinstance(key, str) for key in node):
                    raise MsgpackFrameError("map keys must be strings")
                stack.extend((item, level + 1) for item in node.values())
            else:
                stack.extend((item, level + 1) for item in node)
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise MsgpackFrameError("non-finite number")
        elif not isinstance(node, _SCALARS):
            raise MsgpackFrameError(f"{type(node).__name__} is not allowed")
